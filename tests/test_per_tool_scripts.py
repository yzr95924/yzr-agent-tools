"""Tests for the per-tool control scripts (scripts/<tool>.sh install|uninstall).

These pin the refactored contract: each tool has ONE script that takes
install|uninstall as a subcommand (mirroring scripts/html-mcp.sh), managing
only that tool's wrapper + completion symlinks — without touching the shell rc
(which remains scripts/install.sh's job).
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _prepare_fake_env(tmp_path):
    """Return (fake_home, fake_repo, env) for running scripts hermetically."""
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


def _run(script, sub, env):
    return subprocess.run(
        ["bash", str(script), sub], check=False, capture_output=True, text=True, env=env,
    )


# --- model-switch.sh ---------------------------------------------------------

def test_model_switch_script_is_executable():
    p = ROOT / "scripts" / "model-switch.sh"
    assert p.exists(), "scripts/model-switch.sh missing"
    assert p.stat().st_mode & stat.S_IXUSR, "scripts/model-switch.sh must be executable"


def test_model_switch_install_creates_wrapper_and_completions(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "model-switch.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    wrapper = fake_repo / "bin" / "model-switch"
    assert wrapper.exists() and (wrapper.stat().st_mode & stat.S_IXUSR)
    text = wrapper.read_text()
    assert "PYTHONPATH=" in text
    assert "exec python3" in text
    assert " -m model_switch" in text

    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert bash_link.is_symlink()
    assert bash_link.resolve() == (fake_repo / "completions" / "model-switch.bash").resolve()
    assert fish_link.is_symlink()
    assert fish_link.resolve() == (fake_repo / "completions" / "model-switch.fish").resolve()


def test_model_switch_install_does_not_touch_shell_rc(tmp_path):
    """A single-tool install must NOT write the repo PATH block — that's install.sh's job."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "model-switch.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"
    bashrc = fake_home / ".bashrc"
    assert not bashrc.exists(), "per-tool install must not create/touch the shell rc"


def test_model_switch_uninstall_removes_wrapper_and_completions(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    _run(fake_repo / "scripts" / "model-switch.sh", "install", env)

    r = _run(fake_repo / "scripts" / "model-switch.sh", "uninstall", env)
    assert r.returncode == 0, f"uninstall failed:\n{r.stderr}"

    assert not (fake_repo / "bin" / "model-switch").exists()
    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "model-switch"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "model-switch.fish"
    assert not bash_link.exists() and not bash_link.is_symlink()
    assert not fish_link.exists() and not fish_link.is_symlink()


def test_model_switch_unknown_subcommand_exits_nonzero(tmp_path):
    _, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "model-switch.sh", "bogus", env)
    assert r.returncode != 0


# --- mcp-plugin-mgr.sh -------------------------------------------------------

def test_mcp_plugin_mgr_install_creates_wrapper_and_completions(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "mcp-plugin-mgr.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    wrapper = fake_repo / "bin" / "mcp-plugin-mgr"
    assert wrapper.exists() and (wrapper.stat().st_mode & stat.S_IXUSR)
    text = wrapper.read_text()
    assert " -m mcp_plugin_mgr" in text

    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "mcp-plugin-mgr"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "mcp-plugin-mgr.fish"
    assert bash_link.is_symlink()
    assert fish_link.is_symlink()


# --- html-mcp.sh gains install/uninstall -------------------------------------

def test_html_mcp_script_supports_install_subcommand(tmp_path):
    """html-mcp.sh is the ONE script for html-mcp: install/uninstall alongside start/stop."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "html-mcp.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    wrapper = fake_repo / "bin" / "html-mcp"
    assert wrapper.exists() and (wrapper.stat().st_mode & stat.S_IXUSR)
    text = wrapper.read_text()
    assert " -m html_mcp" in text

    bash_link = Path(env["XDG_DATA_HOME"]) / "bash-completion" / "completions" / "html-mcp"
    fish_link = Path(env["XDG_CONFIG_HOME"]) / "fish" / "completions" / "html-mcp.fish"
    assert bash_link.is_symlink()
    assert fish_link.is_symlink()

    # uninstall cleans up
    r = _run(fake_repo / "scripts" / "html-mcp.sh", "uninstall", env)
    assert r.returncode == 0, f"uninstall failed:\n{r.stderr}"
    assert not (fake_repo / "bin" / "html-mcp").exists()
    assert not bash_link.exists() and not bash_link.is_symlink()


# --- _common.sh is a library, not a command ----------------------------------

def test_common_sh_is_not_executable():
    """_common.sh is meant to be sourced; it must not carry the +x bit."""
    p = ROOT / "scripts" / "_common.sh"
    assert p.exists()
    assert not (p.stat().st_mode & stat.S_IXUSR), (
        "_common.sh is a sourced library; it should not be executable"
    )
