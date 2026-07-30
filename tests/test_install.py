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


def test_pyproject_declares_model_switch_metadata():
    text = PYPROJECT.read_text()

    # Project identity
    assert 'name = "model-switch"' in text
    # Console-script entry — keeps the `pip install model-switch` path viable,
    # even though install.sh doesn't use pip.
    assert 'model-switch = "model_switch.cli:main"' in text
    # Old yzr alias should not leak through
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
    assert "# model-switch PATH begin" in text, (
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
    assert "# model-switch PATH begin" in text
    assert "# model-switch PATH end" in text
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
    assert "# model-switch PATH begin" in text, (
        f"PATH marker should be in the newly-created .bashrc; got: {text!r}"
    )
    assert "# model-switch PATH end" in text


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

    install_sh = str(fake_repo / "scripts" / "install.sh")

    # First run
    r1 = subprocess.run(
        ["bash", install_sh], check=False, capture_output=True, text=True, env=env,
    )
    assert r1.returncode == 0, f"first run failed:\n{r1.stderr}"
    first_bashrc = (fake_home / ".bashrc").read_text()
    first_count = first_bashrc.count("# model-switch PATH begin")
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
    second_count = second_bashrc.count("# model-switch PATH begin")
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
    assert "# model-switch PATH begin" not in bashrc_text, (
        f"uninstall.sh should have stripped the marker; bashrc now: {bashrc_text!r}"
    )

    wrapper = fake_repo / "bin" / "model-switch"
    assert not wrapper.exists(), "uninstall.sh should have removed the wrapper"
