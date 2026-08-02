"""Tests for the per-tool install/uninstall contract.

Each tool ships ONE self-contained script (``scripts/<tool>.sh
install|uninstall``) that writes the ``bin/<tool>`` wrapper, links bash/fish
completions, and manages a per-tool PATH block in the user's shell rc. There is
no aggregator and no shared helper. These tests pin that contract so a future
change can't silently reintroduce venv/pip machinery, duplicate PATH blocks,
resurrect the old multi-script layout, or clobber user files.
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
MS_SH = ROOT / "scripts" / "model-switch.sh"
MCP_SH = ROOT / "scripts" / "mcp-plugin-mgr.sh"
SCRIPTS = (MS_SH, MCP_SH)
WRAPPER = ROOT / "bin" / "model-switch"
PYPROJECT = ROOT / "pyproject.toml"


# --- pyproject.toml contract -----------------------------------------------


def test_pyproject_has_no_publish_metadata():
    """pyproject.toml is pytest-only by design (no pip / no PyPI)."""
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
            assert '"src"' in line or "'src'" in line, (
                f"pytest pythonpath must list 'src'; got: {line!r}"
            )
    assert found_pythonpath, "pyproject has no [tool.pytest.ini_options] pythonpath line"


# --- file-mode + layout contract ---------------------------------------------------


def test_per_tool_scripts_and_wrapper_are_executable():
    for path in (*SCRIPTS, WRAPPER):
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR, f"{path} is not executable"


def test_no_aggregator_or_helper_scripts_remain():
    """The old install.sh / uninstall.sh / _common.sh must be gone — one script
    per tool, nothing else to (mis)invoke directly."""
    for gone in ("install.sh", "uninstall.sh", "_common.sh"):
        assert not (ROOT / "scripts" / gone).exists(), (
            f"scripts/{gone} should be removed (one self-contained script per tool)"
        )


# --- no-pip / no-venv contract -----------------------------------------------------


def test_scripts_do_not_invoke_pip_or_venv():
    """The install flow must not create a venv or run pip install.

    If a future change reintroduces venv / pip, this assertion is the canary —
    the rest of the design (shell wrapper, PYTHONPATH, tests finding src/
    directly) depends on there being no venv at all.
    """
    for sh in SCRIPTS:
        code = _strip_comments_and_heredocs(sh.read_text())

        assert "python3 -m venv" not in code, f"{sh.name} must not create a virtualenv"
        assert not re.search(r"(?:^|[\s\"$/])pip\s+install\s", code, re.MULTILINE), (
            f"{sh.name} must not invoke pip"
        )
        assert "bin/pip" not in code and "VENV_DIR" not in code, (
            f"{sh.name} must not reference a venv-installed pip"
        )


def test_scripts_have_idempotent_per_tool_path_setup():
    """Each script carries a per-tool PATH marker + an idempotency guard."""
    for sh in SCRIPTS:
        text = sh.read_text()
        assert "PATH begin" in text and "PATH end" in text
        assert "grep" in text, f"{sh.name} must guard the PATH block with grep"
        assert "export PATH=" in text
        assert "BIN_DIR" in text


# --- wrapper runtime contract ------------------------------------------------------------


def test_wrapper_source_uses_pythonpath_and_module_invocation():
    """The committed bin/model-switch must be the PYTHONPATH+`python -m` form."""
    text = WRAPPER.read_text()

    assert "PYTHONPATH=" in text, "wrapper must export PYTHONPATH"
    assert '/src"' in text or "src${PYTHONPATH" in text, (
        "wrapper must point PYTHONPATH at the repo's src/ directory"
    )
    assert "exec python3" in text, "wrapper must exec python3"
    assert ' -m model_switch' in text, "wrapper must invoke via `python3 -m model_switch`"
    assert ".venv" not in text, "wrapper must no longer reference .venv"


def test_wrapper_forwards_arguments_with_correct_pythonpath(tmp_path):
    """End-to-end: stub src/model_switch + run wrapper.

    Verifies that running bin/model-switch with argv results in:
      - `python3 -m model_switch` being invoked with the same argv
      - PYTHONPATH including $REPO/src
    """
    wrapper_dst = tmp_path / "bin" / "model-switch"
    wrapper_dst.parent.mkdir()
    wrapper_dst.write_bytes(WRAPPER.read_bytes())
    wrapper_dst.chmod(0o755)

    fake_pkg_dir = tmp_path / "src" / "model_switch"
    fake_pkg_dir.mkdir(parents=True)
    (fake_pkg_dir / "__init__.py").write_text("")
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
    assert payload["argv"] == ["model", "use", "glm-z1"]

    paths = payload["pythonpath"].split(os.pathsep)
    expected_src = os.path.realpath(str(wrapper_dst.parent.parent / "src"))
    assert any(os.path.realpath(p) == expected_src for p in paths), (
        f"PYTHONPATH must include {expected_src}; got {paths}"
    )


# --- behavior helpers ------------------------------------------------------------


def _prepare_fake_env(tmp_path):
    """Return (fake_home, fake_repo, env) for running a script hermetically."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_repo = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        fake_repo,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", ".pytest_cache", "*.egg-info",
        ),
    )
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["SHELL"] = "/bin/bash"
    # Pin XDG dirs under fake HOME so completion symlinks never leak into the
    # real user dirs.
    env["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(fake_home / ".config")
    return fake_home, fake_repo, env


def _run(script, env, *args):
    return subprocess.run(
        ["bash", str(script), *args], check=False, capture_output=True, text=True, env=env,
    )


# --- fresh-env / idempotency / install+uninstall cycle ---------------------------


def test_install_creates_rc_when_home_has_no_bashrc_dir(tmp_path):
    """install must succeed when $HOME has no .bashrc parent dir yet, and write
    a fresh .bashrc containing the per-tool PATH marker."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    assert not (fake_home / ".bashrc").exists()

    r = _run(fake_repo / "scripts" / "model-switch.sh", env, "install")
    assert r.returncode == 0, (
        f"install failed in missing-bashrc scenario: rc={r.returncode}\n{r.stderr!r}"
    )

    bashrc = fake_home / ".bashrc"
    assert bashrc.exists(), "install should have created $HOME/.bashrc"
    text = bashrc.read_text()
    assert "# yzr-agent-tools model-switch PATH begin" in text, (
        f"per-tool PATH marker should be in the new .bashrc; got: {text!r}"
    )
    assert "# yzr-agent-tools model-switch PATH end" in text


def test_install_is_idempotent(tmp_path):
    """Running install twice must not duplicate the PATH block."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    sh = fake_repo / "scripts" / "model-switch.sh"

    assert _run(sh, env, "install").returncode == 0
    first = (fake_home / ".bashrc").read_text().count("# yzr-agent-tools model-switch PATH begin")
    assert first == 1, f"first run should write the marker once; got {first}"

    assert _run(sh, env, "install").returncode == 0
    second = (fake_home / ".bashrc").read_text().count("# yzr-agent-tools model-switch PATH begin")
    assert second == 1, f"second run must not duplicate the marker; got {second}"


def test_uninstall_strips_marker_after_install(tmp_path):
    """End-to-end: install then uninstall → marker block gone, wrapper gone."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    sh = fake_repo / "scripts" / "model-switch.sh"

    assert _run(sh, env, "install").returncode == 0
    assert _run(sh, env, "uninstall").returncode == 0

    bashrc = fake_home / ".bashrc"
    text = bashrc.read_text() if bashrc.exists() else ""
    assert "# yzr-agent-tools model-switch PATH begin" not in text, (
        f"uninstall should have stripped the marker; bashrc now: {text!r}"
    )
    assert not (fake_repo / "bin" / "model-switch").exists(), "wrapper should be gone"


# --- per-tool block independence --------------------------------------------------


def test_each_tool_owns_its_own_path_block(tmp_path):
    """model-switch and mcp-plugin-mgr keep independent PATH blocks: installing
    or uninstalling one never creates or removes the other's marker."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    ms = fake_repo / "scripts" / "model-switch.sh"
    mcp = fake_repo / "scripts" / "mcp-plugin-mgr.sh"
    MS_MARK = "# yzr-agent-tools model-switch PATH begin"
    MCP_MARK = "# yzr-agent-tools mcp-plugin-mgr PATH begin"

    def bashrc():
        return (fake_home / ".bashrc").read_text()

    assert _run(ms, env, "install").returncode == 0
    assert MS_MARK in bashrc() and MCP_MARK not in bashrc()

    assert _run(mcp, env, "install").returncode == 0
    assert MS_MARK in bashrc() and MCP_MARK in bashrc()

    # Uninstalling model-switch leaves mcp-plugin-mgr's block intact.
    assert _run(ms, env, "uninstall").returncode == 0
    assert MS_MARK not in bashrc() and MCP_MARK in bashrc()


# --- legacy block migration -------------------------------------------------------


def test_install_migrates_legacy_shared_block(tmp_path):
    """A legacy shared `# yzr-agent-tools PATH begin` block (old aggregator) is
    cleared and replaced by this tool's own per-tool block (with the completion
    source line inside it)."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    (fake_home / ".bashrc").write_text(
        "# yzr-agent-tools PATH begin\n"
        f"export PATH=\"{fake_repo}/bin:$PATH\"\n"
        "# yzr-agent-tools PATH end\n"
    )

    r = _run(fake_repo / "scripts" / "model-switch.sh", env, "install")
    assert r.returncode == 0, r.stderr

    bashrc = (fake_home / ".bashrc").read_text()
    assert "# yzr-agent-tools PATH begin" not in bashrc, "legacy shared block must be removed"
    assert bashrc.count("# yzr-agent-tools model-switch PATH begin") == 1
    assert "completions/model-switch.bash" in bashrc


def test_install_migrates_ancient_model_switch_block(tmp_path):
    """The ancient `# model-switch PATH begin` block is also cleared."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    (fake_home / ".bashrc").write_text(
        "# model-switch PATH begin\n"
        f"export PATH=\"{fake_repo}/bin:$PATH\"\n"
        "# model-switch PATH end\n"
    )

    r = _run(fake_repo / "scripts" / "model-switch.sh", env, "install")
    assert r.returncode == 0, r.stderr

    bashrc = (fake_home / ".bashrc").read_text()
    assert "# model-switch PATH begin" not in bashrc
    assert bashrc.count("# yzr-agent-tools model-switch PATH begin") == 1


# --- completion contract ----------------------------------------------------------


def test_install_links_bash_and_fish_completions(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "model-switch.sh", env, "install")
    assert r.returncode == 0, r.stderr

    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert bash_link.is_symlink(), f"bash completion symlink missing: {bash_link}"
    assert bash_link.resolve() == (fake_repo / "completions" / "model-switch.bash").resolve()
    assert fish_link.is_symlink(), f"fish completion symlink missing: {fish_link}"
    assert fish_link.resolve() == (fake_repo / "completions" / "model-switch.fish").resolve()

    # The per-tool PATH block sources this tool's bash completion (covers setups
    # without the bash-completion package).
    bashrc = (fake_home / ".bashrc").read_text()
    assert "/completions/" in bashrc and ".bash" in bashrc, (
        f"bashrc should source a bash completion inside the marker block; got: {bashrc!r}"
    )


def test_install_leaves_user_owned_completion_files_alone(tmp_path):
    """A pre-existing regular file at the completion path is not overwritten."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)

    fish_dir = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions"
    fish_dir.mkdir(parents=True)
    user_file = fish_dir / "model-switch.fish"
    user_file.write_text("# my own completion\n")

    r = _run(fake_repo / "scripts" / "model-switch.sh", env, "install")
    assert r.returncode == 0, r.stderr
    assert user_file.read_text() == "# my own completion\n", (
        "install must not clobber a user-owned completion file"
    )
    assert not user_file.is_symlink()


def test_uninstall_removes_completion_links(tmp_path):
    """uninstall removes the completion symlinks install created."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    sh = fake_repo / "scripts" / "model-switch.sh"

    assert _run(sh, env, "install").returncode == 0
    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert bash_link.is_symlink() and fish_link.is_symlink()

    assert _run(sh, env, "uninstall").returncode == 0
    assert not bash_link.exists() and not bash_link.is_symlink(), (
        "uninstall should remove the bash completion symlink"
    )
    assert not fish_link.exists() and not fish_link.is_symlink(), (
        "uninstall should remove the fish completion symlink"
    )
