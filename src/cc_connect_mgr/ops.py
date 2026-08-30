"""Operations behind the four subcommands.

Everything that crosses a machine boundary goes through a Runner
(subprocess seam) and every path comes from paths.py (env-overridable),
so the whole module is testable against tmp dirs with a FakeRunner.
"""
import getpass
import os
import sys
import time
from typing import Dict, List, Optional

from cc_connect_mgr import paths
from cc_connect_mgr.runner import Runner

CONNECTED_MARKERS = ("telegram: connected", "dingtalk: stream connected")

DINGTALK_BLOCK = """\
  [[projects.platforms]]
    type = "dingtalk"

    [projects.platforms.options]
      client_id = "${DINGTALK_CLIENT_ID}"
      client_secret = "${DINGTALK_CLIENT_SECRET}"
      # reaction_emoji = "🤔Thinking"
      # done_emoji = "none"

"""


def _atomic_write(path, content: str, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


# ---- env file ---------------------------------------------------------------


def read_env(path) -> Dict[str, str]:
    """Parse KEY=VALUE lines; comments and blanks skipped. Missing → {}."""
    if not path.exists():
        return {}
    out = {}  # type: Dict[str, str]
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def write_env(path, updates: Dict[str, str]) -> List[str]:
    """Merge updates into an existing env file (preserving unknown keys),
    written atomically with 0600. Returns the keys actually changed."""
    current = read_env(path)
    changed = sorted(k for k, v in updates.items() if current.get(k) != v)
    if not changed:
        return []
    merged = dict(current)
    merged.update(updates)
    lines = [
        "# cc-connect daemon secrets (managed by cc-connect-mgr). chmod 600.",
        "# One bot per host — two daemons sharing a Telegram token steal updates.",
    ]
    for k in sorted(merged):
        lines.append("{0}={1}".format(k, merged[k]))
    _atomic_write(path, "\n".join(lines) + "\n", mode=0o600)
    return changed


# ---- deps / binary ----------------------------------------------------------


def check_deps(runner: Runner) -> List[str]:
    """Return a list of human-readable problems (empty = all good)."""
    problems = []
    for binary, why in (
        ("tmux", "pane driver sends keys through tmux"),
        ("opencode", "the llmw agent backend"),
        ("npm", "installs the cc-connect binary"),
        ("systemctl", "daemon supervision (skip with --no-systemd)"),
    ):
        if not runner.which(binary):
            problems.append("missing dependency: {0} ({1})".format(binary, why))
    return problems


def _binary_version(runner: Runner, path: str) -> str:
    r = runner.run([path, "--version"])
    first = (r.out or r.err).strip().splitlines()
    return first[0] if first else ""


def _version_token(version_line: str) -> str:
    """'cc-connect v1.5.0-llmw.2' → '1.5.0-llmw.2' (for registry compare)."""
    return version_line.split()[-1].lstrip("v") if version_line else ""


def _registry_latest(runner: Runner) -> str:
    """Best-effort latest version from npm; empty string when unreachable."""
    r = runner.run(["npm", "view", paths.NPM_PACKAGE, "version"])
    if not r.ok:
        return ""
    lines = [l.strip() for l in (r.out or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def ensure_binary(runner: Runner) -> str:
    """Return the path of the llmw-fork cc-connect, npm-installing if absent.

    Provenance is verified via --version: the upstream npm package also
    installs a `cc-connect` binary, and silently supervising the wrong
    daemon (no llmw agent) is worse than failing here.
    """
    found = runner.which("cc-connect")
    if found:
        ver = _binary_version(runner, found)
        if "llmw" in ver:
            print("binary: {0} ({1})".format(found, ver))
            return found
        print("found cc-connect at {0} but it is NOT the llmw fork ({1})"
              .format(found, ver or "no version output"))
    print("installing the llmw fork via npm ({0}@latest) ...".format(paths.NPM_PACKAGE))
    r = runner.run(["npm", "install", "-g", paths.NPM_PACKAGE + "@latest"])
    if not r.ok:
        sys.stderr.write("npm install failed:\n{0}{1}\n".format(r.out, r.err))
        raise SystemExit(1)
    found = runner.which("cc-connect")
    if not found:
        sys.stderr.write("npm install finished but cc-connect still not on PATH "
                         "(check your npm global prefix / PATH)\n")
        raise SystemExit(1)
    ver = _binary_version(runner, found)
    if "llmw" not in ver:
        sys.stderr.write(
            "npm install finished but the cc-connect on PATH is still not the "
            "llmw fork ({0} at {1}) — another cc-connect shadows it in PATH\n"
            .format(ver or "?", found))
        raise SystemExit(1)
    print("binary: {0} ({1})".format(found, ver))
    return found


# ---- config -----------------------------------------------------------------


def _prompt_secret(label: str, current_set: bool) -> Optional[str]:
    """Prompt for a secret; empty answer keeps the existing value."""
    if current_set:
        v = getpass.getpass("{0} already set — re-enter to replace, empty to keep: ".format(label))
        return v.strip() or None
    return getpass.getpass("{0}: ".format(label))


def _can_prompt() -> bool:
    return sys.stdin.isatty()


def render_config(with_dingtalk: bool, allow_from: str = "*") -> str:
    body = paths.template("config.toml.tmpl").read_text(encoding="utf-8")
    body = body.replace("{DINGTALK_BLOCK}", DINGTALK_BLOCK if with_dingtalk else "")
    return body.replace('allow_from = "*"', 'allow_from = "{0}"'.format(allow_from))


def generate_config(path, with_dingtalk: bool, allow_from: str = "*") -> None:
    _atomic_write(path, render_config(with_dingtalk, allow_from))


def _insert_platform_block(cfg_path, block: str) -> bool:
    """Insert a [[projects.platforms]] block inside the LAST [[projects]]
    table of an existing config.toml: anchored right before the first
    top-level [table] that follows it, else at EOF. A .bak backup of the
    original is written first. Returns False when no [[projects]] table
    exists (caller falls back to printing the snippet)."""
    lines = cfg_path.read_text(encoding="utf-8").splitlines(keepends=True)
    last_proj = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("[[projects]]"):
            last_proj = i
    if last_proj == -1:
        return False
    insert_at = len(lines)
    for i in range(last_proj + 1, len(lines)):
        s = lines[i].strip()
        if s.startswith("[") and not s.startswith("[[") and not s.startswith("[projects"):
            insert_at = i
            break
    cfg_path.with_name(cfg_path.name + ".bak").write_text(
        "".join(lines), encoding="utf-8")
    _atomic_write(cfg_path, "".join(lines[:insert_at] + block.splitlines(keepends=True)
                                    + lines[insert_at:]))
    return True


def _consistency_warnings(env_path, cfg_path) -> List[str]:
    """Cross-check env credentials vs config.toml platform blocks — the
    classic half-configured state (credentials written, block never pasted)
    otherwise fails silently: the platform simply never starts."""
    have = read_env(env_path)
    cfg_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    warns = []
    dt_env = "DINGTALK_CLIENT_ID" in have and "DINGTALK_CLIENT_SECRET" in have
    dt_cfg = "dingtalk" in cfg_text
    if dt_env and not dt_cfg:
        warns.append("env 有钉钉凭据但 config.toml 无 dingtalk 平台块 — 钉钉平台不会启动")
    if dt_cfg and not dt_env:
        warns.append("config.toml 有 dingtalk 块但 env 缺 DINGTALK_CLIENT_ID/SECRET — 启动会拿到空值")
    if "telegram" in cfg_text and "TELEGRAM_BOT_TOKEN" not in have:
        warns.append("config.toml 有 telegram 平台但 env 缺 TELEGRAM_BOT_TOKEN")
    return warns


_PROC_ENV_TEMPLATE = "/proc/{0}/environ"


def _daemon_env_drifted(runner: Runner, env_path) -> bool:
    """True when the running daemon holds different env values than the file.

    systemd loads EnvironmentFile only at process start — a manual edit of
    the env file leaves the daemon running with stale credentials (e.g.
    a rotated bot token keeps 401-looping). Detect via /proc/<pid>/environ."""
    if not runner.is_root():
        return False
    r = runner.run(["systemctl", "show", "cc-connect", "-p", "MainPID", "--value"])
    pid = (r.out or "").strip()
    if not pid.isdigit() or pid == "0":
        return False
    try:
        with open(_PROC_ENV_TEMPLATE.format(pid), "rb") as f:
            raw = f.read()
    except OSError:
        return False
    proc_env = {}
    for line in raw.split(b"\0"):
        if b"=" in line:
            k, _, v = line.partition(b"=")
            proc_env[k] = v
    for k, v in read_env(env_path).items():
        if proc_env.get(k.encode("utf-8")) != v.encode("utf-8"):
            return True
    return False


def do_config(
    runner: Runner,
    telegram_token: Optional[str] = None,
    dingtalk: bool = False,
    dingtalk_id: Optional[str] = None,
    dingtalk_secret: Optional[str] = None,
    yes: bool = False,
    allow_from: Optional[str] = None,
    restart: bool = True,
    verify_timeout: int = 20,
) -> int:
    """Collect + persist credentials/env, generate config.toml if absent.

    When something actually changed and the daemon runs under systemd,
    restart it and verify the platform re-connects (bad credentials fail
    loudly here instead of crash-looping silently). `install` nests this
    with restart=False — it owns the service lifecycle itself."""
    env_path = paths.env_file()
    cfg_path = paths.config_file()
    updates = {}  # type: Dict[str, str]
    mutated = False
    interactive = _can_prompt() and not yes

    have = read_env(env_path)

    # Telegram (required platform for this fork's workflow).
    if telegram_token:
        updates["TELEGRAM_BOT_TOKEN"] = telegram_token
    elif "TELEGRAM_BOT_TOKEN" not in have:
        if not interactive:
            sys.stderr.write(
                "error: TELEGRAM_BOT_TOKEN missing — pass --telegram-token "
                "(non-interactive) or run in a terminal to prompt\n")
            return 1
        tok = getpass.getpass("Telegram bot token (from @BotFather): ")
        if not tok.strip():
            sys.stderr.write("no token given — nothing to configure\n")
            return 1
        updates["TELEGRAM_BOT_TOKEN"] = tok.strip()
    else:
        print("telegram: token present (keep; pass --telegram-token to replace)")

    # DingTalk (optional branch).
    want_dingtalk = dingtalk or bool(dingtalk_id) or bool(dingtalk_secret)
    if want_dingtalk:
        if dingtalk_id:
            updates["DINGTALK_CLIENT_ID"] = dingtalk_id
        if dingtalk_secret:
            updates["DINGTALK_CLIENT_SECRET"] = dingtalk_secret
        need = [k for k in ("DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET")
                if k not in updates and k not in have]
        if need and not interactive:
            sys.stderr.write(
                "error: dingtalk requested non-interactively but credentials "
                "incomplete — pass both --dingtalk-id and --dingtalk-secret "
                "(or put them in the env file first)\n")
            return 1
        if interactive:
            for key, flag_val, label in (
                ("DINGTALK_CLIENT_ID", dingtalk_id, "DingTalk client_id (AppKey)"),
                ("DINGTALK_CLIENT_SECRET", dingtalk_secret, "DingTalk client_secret (AppSecret)"),
            ):
                if flag_val or key in updates:
                    continue
                v = _prompt_secret(label, key in have)
                if v:
                    updates[key] = v

    if updates:
        changed = write_env(env_path, updates)
        mutated = mutated or bool(changed)
        for k in changed:
            print("env: {0} → {1} (updated, 0600)".format(k, env_path))
        if not changed:
            print("env: values already current ({0})".format(env_path))
    else:
        print("env: nothing to change ({0})".format(env_path))

    # config.toml: generate when absent; insert/advise on existing ones.
    if cfg_path.exists():
        if allow_from:
            print("config: {0} exists — edit allow_from in the telegram "
                  "platform options manually".format(cfg_path))
        if want_dingtalk and "dingtalk" not in cfg_path.read_text(encoding="utf-8"):
            # Insert the block for the user (anchored, with backup) instead of
            # the old print-only path — the snippet was too easy to lose.
            auto = yes or not _can_prompt()
            if interactive:
                ans = input("config.toml 没有 dingtalk 平台块 — 自动插入（备份 .bak）? [Y/n] ")
                auto = ans.strip().lower() != "n"
            if auto:
                if _insert_platform_block(cfg_path, DINGTALK_BLOCK):
                    mutated = True
                    print("config: dingtalk 块已插入 {0}（原文件备份为 .bak）".format(cfg_path))
                else:
                    print("config: 未找到 [[projects]] 表，无法自动插入 — 手动粘贴以下块"
                          "到 [[projects]] 内（任何顶级 [表] 之前）：\n")
                    print(DINGTALK_BLOCK.rstrip("\n"))
    else:
        effective_allow = allow_from or "*"
        if interactive:
            print("allow_from=\"*\" lets ANYONE who finds the bot drive this "
                  "host's opencode — lock it to your Telegram user id when "
                  "sharing hosts.")
            ans = input("telegram allow_from [default *]: ").strip()
            if ans:
                effective_allow = ans
        elif allow_from is None:
            print("config: allow_from defaults to \"*\" (anyone can message the "
                  "bot) — pass --telegram-allow-from to lock it down")
        if want_dingtalk and interactive:
            ans = input("create {0} with telegram+dingtalk? [Y/n] ".format(cfg_path))
            if ans.strip().lower() == "n":
                print("skipped config generation")
                return 0
        generate_config(cfg_path, with_dingtalk=want_dingtalk,
                        allow_from=effective_allow)
        mutated = True
        print("config: generated {0} (secrets stay in env file)".format(cfg_path))

    # Half-configured state check (credentials vs platform blocks).
    for w in _consistency_warnings(env_path, cfg_path):
        print("warning: {0}".format(w))

    # Drift check: the env file changed outside the tool (manual edit) while
    # the daemon kept the old values — restart to converge even when this
    # run itself mutated nothing.
    if restart and not mutated and _daemon_env_drifted(runner, env_path):
        print("env: 运行中的 daemon 与 env 文件不一致（手动编辑过?）→ 对齐")
        mutated = True

    # Apply: restart the daemon when anything changed and it is running.
    if restart and mutated:
        active = runner.run(["systemctl", "is-active", "cc-connect"])
        if runner.is_root() and active.ok:
            r = runner.run(["systemctl", "restart", "cc-connect"])
            if not r.ok:
                sys.stderr.write("systemctl restart failed: {0}\n".format(r.err))
                return 1
            print("service: 配置已变化 → restarted")
            return 0 if verify_daemon(runner, timeout_s=verify_timeout) else 1
        print("提示: 配置已更新;daemon 未运行或无权限 — 手动 "
              "`systemctl restart cc-connect` 生效")
    return 0


# ---- systemd ----------------------------------------------------------------

SERVICE_PATH_DEFAULT = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin"


def service_path(runner: Runner) -> str:
    """systemd's minimal default PATH + dirs of detected agent dependencies.

    The daemon shells out to llmw / opencode / tmux, which often live in
    user bin dirs (~/.local/bin) that systemd's PATH omits — without this
    the agent fails with `llmw: executable file not found in $PATH`."""
    parts = SERVICE_PATH_DEFAULT.split(":")
    for binary in ("llmw", "opencode", "tmux"):
        found = runner.which(binary)
        if found:
            d = os.path.dirname(found)
            if d and d not in parts:
                parts.append(d)
    return ":".join(parts)


def render_unit(exec_start: str, work_dir: str, env_file: str,
                config_path: Optional[str] = None,
                path_env: Optional[str] = None) -> str:
    # -config is passed explicitly: under systemd $HOME may be unset, and
    # cc-connect's discovery (flag → ./config.toml → ~/.cc-connect/…)
    # would otherwise fall back to a default template in WorkingDirectory.
    body = paths.template("cc-connect.service").read_text(encoding="utf-8")
    if config_path is None:
        config_path = str(paths.config_file())
    if path_env is None:
        path_env = SERVICE_PATH_DEFAULT
    return (body
            .replace("{EXEC_START}", exec_start)
            .replace("{CONFIG_PATH}", config_path)
            .replace("{SERVICE_PATH}", path_env)
            .replace("{WORK_DIR}", work_dir)
            .replace("{ENV_FILE}", env_file))


def install_unit(runner: Runner, exec_start: str) -> str:
    """Write the unit if content changed; daemon-reload. Returns status."""
    unit = paths.unit_path()
    content = render_unit(exec_start, str(paths.data_dir().parent),
                          str(paths.env_file()), str(paths.config_file()),
                          service_path(runner))
    # WorkingDirectory must exist and be accessible; use the data dir's
    # parent (= home in the default layout).
    if unit.exists() and unit.read_text(encoding="utf-8") == content:
        return "unchanged"
    _atomic_write(unit, content)
    r = runner.run(["systemctl", "daemon-reload"])
    if not r.ok:
        sys.stderr.write("systemctl daemon-reload failed: {0}\n".format(r.err))
        raise SystemExit(1)
    return "written"


def verify_daemon(runner: Runner, timeout_s: int = 20) -> bool:
    """Poll journald until a platform reports connected. systemd mode only."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = runner.run(["journalctl", "-u", "cc-connect", "-n", "80",
                        "--no-pager", "--output", "cat"])
        text = (r.out or "") + (r.err or "")
        if any(m in text for m in CONNECTED_MARKERS):
            for m in CONNECTED_MARKERS:
                if m in text:
                    print("verify: {0}".format(m))
            return True
        time.sleep(1)
    sys.stderr.write("daemon did not reach 'connected' within {0}s — check: "
                     "journalctl -u cc-connect -n 100\n".format(timeout_s))
    return False


# ---- subcommand entry points --------------------------------------------------


def do_install(runner: Runner, args) -> int:
    problems = check_deps(runner)
    if args.no_systemd:
        problems = [p for p in problems if "systemctl" not in p]
    if problems:
        for p in problems:
            sys.stderr.write("error: {0}\n".format(p))
        return 1

    exec_path = ensure_binary(runner)

    rc = do_config(runner,
                   telegram_token=args.telegram_token,
                   dingtalk=args.dingtalk,
                   dingtalk_id=args.dingtalk_id,
                   dingtalk_secret=args.dingtalk_secret,
                   yes=args.yes,
                   allow_from=args.telegram_allow_from,
                   restart=False)
    if rc != 0:
        return rc

    if args.no_systemd or not runner.is_root():
        if not args.no_systemd:
            sys.stderr.write("warning: not running as root — printing unit + "
                             "steps instead of installing (use sudo, or "
                             "--no-systemd to silence)\n")
        unit = render_unit(exec_path, str(paths.data_dir().parent),
                           str(paths.env_file()), str(paths.config_file()),
                           service_path(runner))
        print("\n--- {0} ---\n{1}\n".format(paths.unit_path(), unit))
        print("manual steps:")
        print("  sudo cp <unit> {0}".format(paths.unit_path()))
        print("  sudo systemctl daemon-reload && sudo systemctl enable --now cc-connect")
        return 0

    was_active = runner.run(["systemctl", "is-active", "cc-connect"]).ok
    status = install_unit(runner, exec_path)
    print("unit: {0} ({1})".format(status, paths.unit_path()))
    r = runner.run(["systemctl", "enable", "--now", "cc-connect"])
    if not r.ok:
        sys.stderr.write("systemctl enable failed: {0}{1}\n".format(r.out, r.err))
        return 1
    if status == "written" and was_active:
        # A rewritten unit is not picked up by the already-running service —
        # converge it so re-running install actually applies changes.
        r = runner.run(["systemctl", "restart", "cc-connect"])
        if r.ok:
            print("service: unit rewritten → restarted to apply")
    print("service: enabled + started")
    return 0 if verify_daemon(runner, timeout_s=args.verify_timeout) else 1


def do_upgrade(runner: Runner, args) -> int:
    current = runner.which("cc-connect")
    if not current:
        sys.stderr.write("cc-connect is not installed — run `cc-connect-mgr install` first\n")
        return 1
    before = _binary_version(runner, current)
    if "llmw" not in before:
        sys.stderr.write("cc-connect on PATH is not the llmw fork ({0} at {1}) — "
                         "run `cc-connect-mgr install` to fix\n"
                         .format(before or "?", current))
        return 1

    # Check-first: skip the npm round trip AND the daemon restart when the
    # installed version already matches the registry latest.
    latest = _registry_latest(runner)
    if latest and _version_token(before) == latest:
        print("already at latest: {0} (no restart)".format(before))
        return 0

    r = runner.run(["npm", "install", "-g", paths.NPM_PACKAGE + "@latest"])
    if not r.ok:
        sys.stderr.write("npm install failed:\n{0}{1}\n".format(r.out, r.err))
        return 1
    found = runner.which("cc-connect") or current
    after = _binary_version(runner, found)
    if "llmw" not in after:
        sys.stderr.write("cc-connect on PATH is not the llmw fork ({0} at {1})\n"
                         .format(after or "?", found))
        return 1
    print("upgraded: {0} → {1}".format(before, after))
    r = runner.run(["systemctl", "restart", "cc-connect"])
    if not r.ok:
        sys.stderr.write("systemctl restart failed (is the unit installed?): {0}\n".format(r.err))
        return 1
    return 0 if verify_daemon(runner, timeout_s=args.verify_timeout) else 1


def do_uninstall(runner: Runner, args) -> int:
    r = runner.run(["systemctl", "disable", "--now", "cc-connect"])
    print("service: {0}".format("stopped+disabled" if r.ok
                                else "not active/installed ({0})".format(r.err.strip())))
    unit = paths.unit_path()
    if unit.exists():
        unit.unlink()
        print("unit: removed {0}".format(unit))
    runner.run(["systemctl", "daemon-reload"])
    if args.remove_npm:
        r = runner.run(["npm", "uninstall", "-g", paths.NPM_PACKAGE])
        print("npm: {0}".format("package removed" if r.ok else r.err.strip()))
    data = paths.data_dir()
    if args.purge:
        import shutil
        shutil.rmtree(data)
        print("purged: {0} (config/env/sessions deleted)".format(data))
    else:
        print("data kept: {0} (use --purge to delete)".format(data))
    return 0
