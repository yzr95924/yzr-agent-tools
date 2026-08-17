"""Tests for the per-tool control scripts (scripts/<tool>.sh install|uninstall).

Each tool has ONE self-contained script that takes install|uninstall as a
subcommand. install writes that tool's wrapper + bash/fish completion symlinks
AND its own per-tool PATH block in the shell rc; uninstall reverses all of it.
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


def test_model_switch_install_writes_its_own_path_block(tmp_path):
    """install writes a per-tool PATH block (not the old shared one)."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "model-switch.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    bashrc = fake_home / ".bashrc"
    assert bashrc.exists(), "install must create/touch the shell rc"
    text = bashrc.read_text()
    assert "# yzr-agent-tools model-switch PATH begin" in text
    assert "# yzr-agent-tools model-switch PATH end" in text
    assert "export PATH=" in text


def test_model_switch_uninstall_strips_its_path_block(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    sh = fake_repo / "scripts" / "model-switch.sh"
    assert _run(sh, "install", env).returncode == 0
    assert (fake_home / ".bashrc").exists()

    r = _run(sh, "uninstall", env)
    assert r.returncode == 0, f"uninstall failed:\n{r.stderr}"
    text = (fake_home / ".bashrc").read_text()
    assert "# yzr-agent-tools model-switch PATH begin" not in text


def test_model_switch_uninstall_removes_wrapper_and_completions(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    sh = fake_repo / "scripts" / "model-switch.sh"
    _run(sh, "install", env)

    r = _run(sh, "uninstall", env)
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


def test_mcp_plugin_mgr_install_writes_its_own_path_block(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "mcp-plugin-mgr.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    text = (fake_home / ".bashrc").read_text()
    assert "# yzr-agent-tools mcp-plugin-mgr PATH begin" in text
    assert "# yzr-agent-tools mcp-plugin-mgr PATH end" in text


# --- yzr-agent-style.sh (thin: no wrapper / PATH / completions) ---------------

def test_yzr_agent_style_script_is_executable():
    p = ROOT / "scripts" / "yzr-agent-style.sh"
    assert p.exists(), "scripts/yzr-agent-style.sh missing"
    assert p.stat().st_mode & stat.S_IXUSR, "scripts/yzr-agent-style.sh must be executable"


def test_yzr_agent_style_script_is_thin(tmp_path):
    """The thin shell must NOT write a bin wrapper / PATH block / completions."""
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    # Agent config dirs don't exist yet, so install skips everything.
    r = _run(fake_repo / "scripts" / "yzr-agent-style.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    assert not (fake_repo / "bin" / "yzr-agent-style").exists()
    assert not (fake_home / ".bashrc").exists()
    assert not (Path(env["XDG_DATA_HOME"]) / "bash-completion").exists()
    assert not (Path(env["XDG_CONFIG_HOME"]) / "fish").exists()


def test_yzr_agent_style_install_writes_three_targets(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    (fake_home / ".claude").mkdir()
    (fake_home / ".config" / "opencode").mkdir(parents=True)
    (fake_home / ".qoder").mkdir()

    r = _run(fake_repo / "scripts" / "yzr-agent-style.sh", "install", env)
    assert r.returncode == 0, f"install failed:\n{r.stderr}"

    for target in (
        fake_home / ".claude" / "CLAUDE.md",
        fake_home / ".config" / "opencode" / "AGENTS.md",
        fake_home / ".qoder" / "AGENTS.md",
    ):
        assert target.exists(), f"missing {target}"
        assert "<!-- yzr-agent-style begin -->" in target.read_text()


def test_yzr_agent_style_uninstall_removes_targets(tmp_path):
    fake_home, fake_repo, env = _prepare_fake_env(tmp_path)
    (fake_home / ".claude").mkdir()
    sh = fake_repo / "scripts" / "yzr-agent-style.sh"
    assert _run(sh, "install", env).returncode == 0

    r = _run(sh, "uninstall", env)
    assert r.returncode == 0, f"uninstall failed:\n{r.stderr}"
    assert not (fake_home / ".claude" / "CLAUDE.md").exists()


def test_yzr_agent_style_unknown_subcommand_exits_nonzero(tmp_path):
    _, fake_repo, env = _prepare_fake_env(tmp_path)
    r = _run(fake_repo / "scripts" / "yzr-agent-style.sh", "bogus", env)
    assert r.returncode != 0
