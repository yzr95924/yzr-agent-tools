"""Tests for the install/wrapper contract.

The project follows a "shell wrapper + PYTHONPATH" install flow modeled on
llm-workspace-cli: no virtualenv, no `pip install`. install.sh writes a thin
bash wrapper into bin/model-switch plus an idempotent PATH block in the
user's shell rc. These tests pin that contract so a future change can't
silently reintroduce venv / pip machinery without flipping them red.
"""
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


def _strip_comments_and_heredocs(text: str) -> str:
    """Reduce bash source to just its executable lines.

    Drops:
      - Lines that are shell comments (start with `#` after optional indent).
      - Body lines of any heredoc (`<<'EOF'`, `<<EOF`, `<<-EOF`, quoted or not),
        so prose like "pip install --user tomli" inside `cat <<'NOTE'` blocks
        doesn't false-positive our pip/venv presence check.

    Keeps heredoc start and terminator lines (they're still part of the
    control flow we want to inspect).
    """
    out = []
    heredoc_marker = None  # when set, body lines are dropped
    for line in text.splitlines():
        if heredoc_marker is not None:
            if line.strip() == heredoc_marker:
                heredoc_marker = None
                out.append(line)
            # else: body line, dropped.
            continue
        # Detect heredoc opener on this line.
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            heredoc_marker = m.group(1)
            out.append(line)
            continue
        out.append(line)
    # Now strip `^#` comment lines (any indentation).
    return "\n".join(
        line for line in out if not line.lstrip().startswith("#")
    )


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "scripts" / "install.sh"
UNINSTALL_SH = ROOT / "scripts" / "uninstall.sh"
WRAPPER = ROOT / "bin" / "model-switch"
PYPROJECT = ROOT / "pyproject.toml"


# --- pyproject.toml contract -----------------------------------------------


def test_pyproject_has_no_publish_metadata():
    """pyproject.toml is pytest-only by design (no pip / no PyPI).

    当前没有发布计划——安装走 scripts/install.sh,包用 PYTHONPATH=$REPO/src 直接
    import src/。pyproject.toml 只留 [tool.pytest.ini_options] 让 pytest 能
    找到 src/ 与 tests/。如果以后重新引入发布路径,要先把这条断言去掉,并改回
    上一个版本的 `test_pyproject_declares_model_switch_metadata` 风格。
    """
    text = PYPROJECT.read_text()

    # No [project] / [project.scripts] / [build-system] / setuptools config.
    assert "[project]" not in text, (
        "pyproject.toml must not declare [project] — there is no publish plan"
    )
    assert "[project.scripts]" not in text, (
        "pyproject.toml must not declare [project.scripts] — no console_scripts entry"
    )
    assert "[build-system]" not in text, (
        "pyproject.toml must not declare [build-system] — no wheel build"
    )
    assert "[tool.setuptools" not in text, (
        "pyproject.toml must not configure setuptools packages"
    )
    # And the literal old CLI entry must not leak back.
    assert 'model-switch = "model_switch.cli:main"' not in text
    assert 'yzr = "model_switch.cli:main"' not in text


def test_pyproject_pytest_pythonpath_includes_src():
    """pytest must discover src/model_switch without a venv-installed .pth file."""
    text = PYPROJECT.read_text()

    # Find the [tool.pytest.ini_options] pythonpath line and check it lists 'src'.
    in_pytest_block = False
    found_pythonpath = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_pytest_block = s == "[tool.pytest.ini_options]"
            continue
        if not in_pytest_block:
            continue
        if s.startswith("pythonpath"):
            found_pythonpath = True
            # accept either list-literal or comma-separated form
            assert '"src"' in line or "'src'" in line, (
                f"pytest pythonpath must list 'src'; got: {line!r}"
            )
            # 'tests' may stay or go; assertion is just about src being present.
    assert found_pythonpath, "pyproject has no [tool.pytest.ini_options] pythonpath line"


# --- file-mode contract ---------------------------------------------------


def test_install_and_uninstall_scripts_and_wrapper_are_executable():
    for path in (INSTALL_SH, UNINSTALL_SH, WRAPPER):
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{path} is not executable"


def test_uninstall_script_exists():
    """install.sh + uninstall.sh must come as a pair."""
    assert UNINSTALL_SH.exists(), "scripts/uninstall.sh missing"
    text = UNINSTALL_SH.read_text()
    assert "# yzr-agent-tools PATH begin" in text, (
        "uninstall.sh must reference the same marker install.sh writes, "
        "so it can strip the PATH block"
    )
    assert "rm" in text, "uninstall.sh must actually remove things"


# --- install.sh content contract ------------------------------------------


def test_install_script_does_not_invoke_pip_or_venv():
    """The new install flow must not create a venv or run pip install.

    If a future change reintroduces venv / pip into install.sh, this
    assertion is the canary — the rest of the design (shell wrapper,
    PYTHONPATH, tests finding src/ directly) depends on there being
    no venv at all.

    We strip heredoc bodies and comment lines before scanning so prose
    like "no `pip install`" in docs and `pip install --user tomli` in
    user-facing NOTE blocks doesn't false-positive.
    """
    raw = INSTALL_SH.read_text()
    code = _strip_comments_and_heredocs(raw)

    assert "python3 -m venv" not in code, (
        "install.sh must not create a virtualenv"
    )
    # Actual pip invocation as a real command:
    #   pip install ...
    #   "$VENV/bin/pip" install ...
    #   $VENV_DIR/bin/pip install ...
    assert not re.search(r"(?:^|[\s\"$/])pip\s+install\s", code, re.MULTILINE), (
        "install.sh must not invoke pip"
    )
    # VENV_DIR/bin/pip call (the concrete form the old script used)
    assert "bin/pip" not in code and "VENV_DIR" not in code, (
        "install.sh must not reference a venv-installed pip"
    )


def test_install_script_has_idempotent_path_setup():
    text = INSTALL_SH.read_text()

    # marker-based idempotency (in comment form, since the literal block
    # is constructed via cat <<'WRAPPER' or local var assignment).
    assert "# yzr-agent-tools PATH begin" in text
    assert "# yzr-agent-tools PATH end" in text
    # idempotency check (any grep variant)
    assert "grep" in text
    # actually emits a `export PATH=...` line (escaped, via local var)
    assert "export PATH=" in text
    assert "BIN_DIR" in text


def test_install_script_warns_on_legacy_venv():
    """If a previous install left a .venv behind, install.sh must warn."""
    text = INSTALL_SH.read_text()
    assert ".venv" in text, (
        "install.sh should mention .venv so users see the legacy warning"
    )


# --- wrapper runtime contract --------------------------------------------


def test_wrapper_source_uses_pythonpath_and_module_invocation():
    """The committed bin/model-switch must be the PYTHONPATH+`python -m` form."""
    text = WRAPPER.read_text()

    assert "PYTHONPATH=" in text, "wrapper must export PYTHONPATH"
    assert '/src"' in text or "src${PYTHONPATH" in text, (
        "wrapper must point PYTHONPATH at the repo's src/ directory"
    )
    assert "exec python3" in text, "wrapper must exec python3"
    assert ' -m model_switch' in text, "wrapper must invoke via `python3 -m model_switch`"
    # Old form must NOT remain
    assert ".venv" not in text, "wrapper must no longer reference .venv"


def test_wrapper_forwards_arguments_with_correct_pythonpath(tmp_path):
    """End-to-end: stub src/model_switch + run wrapper.

    Verifies that running bin/model-switch with argv results in:
      - `python3 -m model_switch` being invoked with the same argv
      - PYTHONPATH including $REPO/src
    """
    # 1. Copy wrapper verbatim into tmp/bin/
    wrapper_dst = tmp_path / "bin" / "model-switch"
    wrapper_dst.parent.mkdir()
    wrapper_dst.write_bytes(WRAPPER.read_bytes())
    wrapper_dst.chmod(0o755)

    # 2. Stub src/model_switch/ under tmp_path (the wrapper resolves REPO
    #    relative to its own location, so REPO = tmp_path).
    fake_pkg_dir = tmp_path / "src" / "model_switch"
    fake_pkg_dir.mkdir(parents=True)
    (fake_pkg_dir / "__init__.py").write_text("")
    # __main__.py prints argv + PYTHONPATH as JSON for the test to inspect.
    (fake_pkg_dir / "__main__.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "    'argv': sys.argv[1:],\n"
        "    'pythonpath': os.environ.get('PYTHONPATH', ''),\n"
        "    'cwd': os.getcwd(),\n"
        "}))\n"
    )

    result = subprocess.run(
        [str(wrapper_dst), "model", "use", "glm-z1"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"wrapper exited non-zero: rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )

    payload = json.loads(result.stdout.strip())

    # argv forwarding
    assert payload["argv"] == ["model", "use", "glm-z1"]

    # PYTHONPATH must contain $REPO/src (so `model_switch` is importable)
    paths = payload["pythonpath"].split(os.pathsep)
    expected_src = os.path.realpath(str(repo_root_for(wrapper_dst) / "src"))
    assert any(os.path.realpath(p) == expected_src for p in paths), (
        f"PYTHONPATH must include {expected_src}; got {paths}"
    )


def repo_root_for(wrapper_path: Path) -> Path:
    """Where the wrapper resolves REPO to: one level up from bin/."""
    return wrapper_path.parent.parent


# --- install.sh behavior in fresh environments ----------------------------


def test_install_script_creates_rc_when_home_has_no_bashrc_dir(tmp_path):
    """install.sh must succeed when $HOME has no .bashrc parent dir.

    Some fresh environments (CI containers, chroots, $HOME points at a
    brand-new dir) ship a $HOME that has no $HOME/.bashrc subdirectory yet.
    Before the mkdir hardening this errored out at the `: > "$rc_path"`
    redirect. With the fix, install.sh runs cleanly and writes a fresh
    .bashrc containing the PATH marker.
    """
    # Bare $HOME with no .bashrc / .zshrc.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    assert not (fake_home / ".bashrc").exists()

    # Copy the repo into a tmp PROJECT_ROOT so install.sh's writes land in
    # tmp, not on the real working tree.
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache",
            "*.egg-info",
        ),
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    # Pin XDG dirs under the fake HOME so completion symlinks written by
    # install.sh can never leak into the real user dirs, whatever the
    # outer environment happens to export.
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")

    result = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "install.sh")],
        check=False, capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, (
        f"install.sh failed in missing-bashrc scenario: "
        f"rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )

    bashrc = fake_home / ".bashrc"
    assert bashrc.exists(), (
        "install.sh should have created $HOME/.bashrc "
        "(the mkdir -p hardening makes this work)"
    )
    text = bashrc.read_text()
    assert "# yzr-agent-tools PATH begin" in text, (
        f"PATH marker should be in the newly-created .bashrc; got: {text!r}"
    )
    assert "# yzr-agent-tools PATH end" in text


def test_install_script_idempotent(tmp_path):
    """Running install.sh twice must not duplicate the PATH block."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache",
            "*.egg-info",
        ),
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    # Pin XDG dirs under the fake HOME so completion symlinks written by
    # install.sh can never leak into the real user dirs, whatever the
    # outer environment happens to export.
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")

    install_sh = str(fake_repo / "scripts" / "install.sh")

    # First run
    r1 = subprocess.run(
        ["bash", install_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert r1.returncode == 0, f"first run failed:\n{r1.stderr}"
    first_bashrc = (fake_home / ".bashrc").read_text()
    first_count = first_bashrc.count("# yzr-agent-tools PATH begin")
    assert first_count == 1, (
        f"first run should write the marker once; got {first_count} occurrences "
        f"in {first_bashrc!r}"
    )

    # Second run (must be idempotent)
    r2 = subprocess.run(
        ["bash", install_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert r2.returncode == 0, f"second run failed:\n{r2.stderr}"
    second_bashrc = (fake_home / ".bashrc").read_text()
    second_count = second_bashrc.count("# yzr-agent-tools PATH begin")
    assert second_count == 1, (
        f"second run must not duplicate the marker; got {second_count} occurrences "
        f"in {second_bashrc!r}"
    )


def test_uninstall_script_strips_marker_after_install(tmp_path):
    """End-to-end: install then uninstall, marker block removed from bashrc."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache",
            "*.egg-info",
        ),
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    # Pin XDG dirs under the fake HOME so completion symlinks written by
    # install.sh can never leak into the real user dirs, whatever the
    # outer environment happens to export.
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")

    install_sh = str(fake_repo / "scripts" / "install.sh")
    uninstall_sh = str(fake_repo / "scripts" / "uninstall.sh")

    install_r = subprocess.run(
        ["bash", install_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert install_r.returncode == 0, f"install failed: {install_r.stderr}"

    install_r = subprocess.run(
        ["bash", uninstall_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert install_r.returncode == 0, f"uninstall failed: {install_r.stderr}"

    bashrc_text = (fake_home / ".bashrc").read_text() if (fake_home / ".bashrc").exists() else ""
    assert "# yzr-agent-tools PATH begin" not in bashrc_text, (
        f"uninstall.sh should have stripped the marker; bashrc now: {bashrc_text!r}"
    )

    wrapper = fake_repo / "bin" / "model-switch"
    assert not wrapper.exists(), "uninstall.sh should have removed the wrapper"


# --- shell completion install contract --------------------------------------


def _prepare_fake_env(tmp_path):
    """Return (fake_home, fake_repo, env) for running install.sh hermetically."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache",
            "*.egg-info",
        ),
    )
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")
    return fake_home, fake_repo, env


def test_install_links_bash_and_fish_completions(tmp_path):
    """install.sh must symlink both completion scripts into the XDG dirs.

    Every shipped tool gets its own symlinks.
    """
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)

    r = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "install.sh")],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    # model-switch links
    ms_bash = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    ms_fish = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert ms_bash.is_symlink(), f"model-switch bash completion symlink missing: {ms_bash}"
    assert ms_bash.resolve() == (fake_repo / "completions" / "model-switch.bash").resolve()
    assert ms_fish.is_symlink(), f"model-switch fish completion symlink missing: {ms_fish}"
    assert ms_fish.resolve() == (fake_repo / "completions" / "model-switch.fish").resolve()

    # bashrc marker block should source a bash completion (covers setups
    # without the bash-completion package). We don't pin which tool —
    # install.sh picks the first one in its tool list.
    bashrc = (fake_home / ".bashrc").read_text()
    assert "/completions/" in bashrc and ".bash" in bashrc, (
        f"bashrc should source a bash completion inside the marker block; got: {bashrc!r}"
    )


def test_install_completion_upgrade_splices_source_line(tmp_path):
    """An old marker block (no completion line) gets the source line spliced in."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)

    old_block = (
        "# model-switch PATH begin\n"
        f"export PATH=\"{fake_repo}/bin:$PATH\"\n"
        "# model-switch PATH end\n"
    )
    (fake_home / ".bashrc").write_text(old_block)

    r = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "install.sh")],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    bashrc = (fake_home / ".bashrc").read_text()
    assert bashrc.count("# yzr-agent-tools PATH begin") == 1, (
        f"upgrade must not duplicate the marker block; got: {bashrc!r}"
    )
    assert "completions/model-switch.bash" in bashrc, (
        f"upgrade should splice the completion source line in; got: {bashrc!r}"
    )
    # The spliced line must sit INSIDE the marker block so uninstall strips it.
    begin_i = bashrc.index("# yzr-agent-tools PATH begin")
    end_i = bashrc.index("# yzr-agent-tools PATH end")
    line_i = bashrc.index("completions/model-switch.bash")
    assert begin_i < line_i < end_i, (
        f"completion source line must be inside the marker block; got: {bashrc!r}"
    )


def test_install_leaves_user_owned_completion_files_alone(tmp_path):
    """A pre-existing regular file at the completion path is not overwritten."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)

    fish_dir = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions"
    fish_dir.mkdir(parents=True)
    user_file = fish_dir / "model-switch.fish"
    user_file.write_text("# my own completion\n")

    r = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "install.sh")],
        check=False, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed:\n{r.stderr}"
    assert user_file.read_text() == "# my own completion\n", (
        "install.sh must not clobber a user-owned completion file"
    )
    assert not user_file.is_symlink()


def test_uninstall_removes_completion_links(tmp_path):
    """uninstall.sh removes the completion symlinks it created."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)

    install_sh = str(fake_repo / "scripts" / "install.sh")
    uninstall_sh = str(fake_repo / "scripts" / "uninstall.sh")

    r = subprocess.run(["bash", install_sh], check=False, capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert bash_link.is_symlink() and fish_link.is_symlink()

    r = subprocess.run(["bash", uninstall_sh], check=False, capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"uninstall failed:\n{r.stderr}"

    assert not bash_link.exists() and not bash_link.is_symlink(), (
        "uninstall.sh should remove the bash completion symlink"
    )
    assert not fish_link.exists() and not fish_link.is_symlink(), (
        "uninstall.sh should remove the fish completion symlink"
    )
