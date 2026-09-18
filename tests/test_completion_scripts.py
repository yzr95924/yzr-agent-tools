"""End-to-end tests for the shell completion scripts.

The scripts are exercised as black boxes in a real bash / zsh / fish process,
driven through the same entry points an interactive shell would use:

  bash: source the script, set COMP_WORDS/COMP_CWORD, call _model_switch,
        then inspect COMPREPLY.
  zsh:  drive tests/zsh_capture.zsh, which spawns a real interactive zsh
        under zpty and records every compadd candidate (see that file's
        header for the technique and its accepted noise).
  fish: source the script, call `complete --do-complete="<line>"`.

Hermeticity: the scripts resolve dynamic candidates by shelling out to
`<tool> _complete ...`, so the subprocess env points PATH at the repo's
bin/ and XDG_CONFIG_HOME at a tmp dir holding fixture models.toml /
servers.toml. The real user config is never touched (conftest's teardown
integrity check would fail the suite otherwise).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPLETIONS = ROOT / "completions"
BIN = ROOT / "bin"
ZSH_CAPTURE = ROOT / "tests" / "zsh_capture.zsh"

MODELS_TOML = """\
[[models]]
model_id = "glm-z1"
name = "glm-4"
base_url = "https://api.example.com"
api_key = "GLM_API_KEY"

[[models]]
model_id = "kimi-k2"
name = "kimi-k2-0905"
base_url = "https://api.moonshot.cn/anthropic"
api_key = "MOONSHOT_API_KEY"
"""

SERVERS_TOML = """\
[servers.outline]
transport = "http"
url = "https://outline.example.com"

[servers.memos]
transport = "http"
url = "https://memos.example.com"
"""


@pytest.fixture
def comp_env(tmp_path):
    """Subprocess env: tmp XDG config with two models, repo bin on PATH."""
    xdg = tmp_path / "xdg"
    cfg = xdg / "model-switch"
    cfg.mkdir(parents=True)
    (cfg / "models.toml").write_text(MODELS_TOML)
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg)
    env["PATH"] = "{}{}{}".format(BIN, os.pathsep, env.get("PATH", ""))
    return env


@pytest.fixture
def mcp_env(tmp_path):
    """Subprocess env: tmp XDG config with two MCP servers, repo bin on PATH."""
    xdg = tmp_path / "xdg"
    cfg = xdg / "mcp-plugin-mgr"
    cfg.mkdir(parents=True)
    (cfg / "servers.toml").write_text(SERVERS_TOML)
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(xdg)
    env["PATH"] = "{}{}{}".format(BIN, os.pathsep, env.get("PATH", ""))
    return env


def _bash_quote(word):
    return "'" + word.replace("'", "'\\''") + "'"


def bash_complete(env, words, cword, cwd=None, script="model-switch", func="_model_switch"):
    """Simulate readline: set COMP_WORDS/COMP_CWORD, run the completion function."""
    script_text = (
        'source "{}/{}.bash"\n'.format(COMPLETIONS, script)
        + "COMP_WORDS=({})\n".format(" ".join(_bash_quote(w) for w in words))
        + "COMP_CWORD={}\n".format(cword)
        + "{}\n".format(func)
        + 'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    r = subprocess.run(
        ["bash", "-c", script_text], env=env, cwd=cwd, capture_output=True, text=True,
    )
    assert r.returncode == 0, "bash completion failed: {}".format(r.stderr)
    # printf emits one bare "\n" for an empty COMPREPLY — drop empty lines.
    return [l for l in r.stdout.splitlines() if l]


FISH_AVAILABLE = shutil.which("fish") is not None
needs_fish = pytest.mark.skipif(not FISH_AVAILABLE, reason="fish not installed")


def fish_complete(env, line, cwd=None):
    script = 'source "{}/model-switch.fish"; complete --do-complete={}'.format(
        COMPLETIONS, _fish_quote(line),
    )
    r = subprocess.run(
        ["fish", "-c", script], env=env, cwd=cwd, capture_output=True, text=True,
    )
    assert r.returncode == 0, "fish completion failed: {}".format(r.stderr)
    # Output lines are "candidate\tdescription".
    return [l.split("\t")[0] for l in r.stdout.splitlines() if l.strip()]


def _fish_quote(word):
    return "'" + word.replace("'", "\\'") + "'"


ZSH_AVAILABLE = shutil.which("zsh") is not None
needs_zsh = pytest.mark.skipif(not ZSH_AVAILABLE, reason="zsh not installed")


def zsh_complete(env, line, cwd=None):
    """Drive tests/zsh_capture.zsh: capture what a real zsh would offer.

    The harness can block if something goes wrong internally (zpty reads are
    blocking), so guard with a subprocess timeout and fail loudly.
    """
    try:
        r = subprocess.run(
            ["zsh", "-f", str(ZSH_CAPTURE), str(COMPLETIONS), line],
            env=env, cwd=cwd, capture_output=True, text=True, timeout=90,
        )
    except subprocess.TimeoutExpired as e:
        partial_out = (e.stdout or b"")
        partial_err = (e.stderr or b"")
        if isinstance(partial_out, bytes):
            partial_out = partial_out.decode("utf-8", "replace")
        if isinstance(partial_err, bytes):
            partial_err = partial_err.decode("utf-8", "replace")
        pytest.fail(
            "zsh completion harness timed out on: {!r}\n"
            "harness stderr: {}\nharness stdout: {}".format(
                line, partial_err[-2000:], partial_out[-2000:],
            )
        )
    assert r.returncode == 0, "zsh completion failed: {}{}".format(
        r.stderr, "(stdout: {!r})".format(r.stdout) if r.stdout else "",
    )
    return [l for l in r.stdout.splitlines() if l]

# --- bash ---------------------------------------------------------------------


def test_bash_top_level_commands(comp_env):
    got = bash_complete(comp_env, ["model-switch", ""], 1)
    assert set(got) == {"init", "model", "status"}


def test_bash_top_level_prefix_filter(comp_env):
    assert bash_complete(comp_env, ["model-switch", "m"], 1) == ["model"]


def test_bash_model_actions(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", ""], 2)
    assert set(got) == {"add", "list", "show", "remove", "use", "import", "probe"}


def test_bash_model_action_prefix_filter(comp_env):
    assert bash_complete(comp_env, ["model-switch", "model", "u"], 2) == ["use"]


def test_bash_use_completes_model_names(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "use", ""], 3)
    assert set(got) == {"glm-z1", "kimi-k2"}


def test_bash_remove_completes_model_names_with_prefix(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "remove", "gl"], 3)
    assert got == ["glm-z1"]


def test_bash_use_completes_flags(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "use", "--"], 3)
    assert set(got) == {"--driver", "--all-drivers", "--help"}


def test_bash_driver_value_completes_driver_names(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "use", "--driver", ""], 4)
    assert set(got) == {"claude-code", "opencode"}


def test_bash_status_completes_flags(comp_env):
    got = bash_complete(comp_env, ["model-switch", "status", ""], 2)
    assert set(got) == {"--driver", "--all-drivers", "--help"}


def test_bash_add_completes_flags(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "add", ""], 3)
    assert "--base-url" in got
    assert "--api-key" in got
    assert "--model-name" in got
    assert "--context-window" in got
    assert "--provider" in got


def test_bash_add_flag_value_offers_nothing(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "add", "--base-url", ""], 4)
    assert got == []


def test_bash_init_offers_nothing(comp_env):
    assert bash_complete(comp_env, ["model-switch", "init", ""], 2) == []


def test_bash_probe_completes_flags_and_models(comp_env):
    flags = bash_complete(comp_env, ["model-switch", "model", "probe", "--"], 3)
    assert set(flags) == {"--budgets", "--catalog-source", "--catalog-provider",
                          "--json", "--out", "--apply", "--help"}
    models = bash_complete(comp_env, ["model-switch", "model", "probe", ""], 3)
    assert set(models) == {"glm-z1", "kimi-k2"}


def test_bash_import_completes_files(comp_env, tmp_path):
    (tmp_path / "sample.toml").write_text("")
    (tmp_path / "notes.txt").write_text("")
    got = bash_complete(comp_env, ["model-switch", "model", "import", ""], 3, cwd=tmp_path)
    assert "sample.toml" in got


# --- fish ---------------------------------------------------------------------


@needs_fish
def test_fish_top_level_commands(comp_env):
    got = fish_complete(comp_env, "model-switch ")
    assert set(got) == {"init", "model", "status"}


@needs_fish
def test_fish_model_actions(comp_env):
    got = fish_complete(comp_env, "model-switch model ")
    assert set(got) == {"add", "list", "show", "remove", "use", "import", "probe"}


@needs_fish
def test_fish_use_completes_model_names(comp_env):
    got = fish_complete(comp_env, "model-switch model use ")
    assert set(got) == {"glm-z1", "kimi-k2"}


@needs_fish
def test_fish_remove_completes_model_names_with_prefix(comp_env):
    assert fish_complete(comp_env, "model-switch model remove gl") == ["glm-z1"]


@needs_fish
def test_fish_use_completes_flags(comp_env):
    got = fish_complete(comp_env, "model-switch model use --")
    assert {"--driver", "--all-drivers", "--help"} <= set(got)


@needs_fish
def test_fish_driver_value_completes_driver_names(comp_env):
    got = fish_complete(comp_env, "model-switch model use --driver ")
    assert set(got) == {"claude-code", "opencode"}


@needs_fish
def test_fish_no_file_fallback_after_positional(comp_env, tmp_path):
    """Once the model name is given, an empty token must not offer files."""
    (tmp_path / "stray.toml").write_text("")
    got = fish_complete(comp_env, "model-switch model use glm-z1 ", cwd=tmp_path)
    assert got == []


@needs_fish
def test_fish_status_completes_flags(comp_env):
    got = fish_complete(comp_env, "model-switch status --")
    assert {"--driver", "--all-drivers", "--help"} <= set(got)


@needs_fish
def test_fish_import_completes_toml_files(comp_env, tmp_path):
    (tmp_path / "sample.toml").write_text("")
    (tmp_path / "notes.txt").write_text("")
    got = fish_complete(comp_env, "model-switch model import ", cwd=tmp_path)
    assert "sample.toml" in got


# --- zsh ----------------------------------------------------------------------


@needs_zsh
def test_zsh_top_level_commands(comp_env):
    got = zsh_complete(comp_env, "model-switch ")
    assert set(got) == {"init", "model", "status"}


@needs_zsh
def test_zsh_top_level_prefix_filter(comp_env):
    assert zsh_complete(comp_env, "model-switch m") == ["model"]


@needs_zsh
def test_zsh_model_actions(comp_env):
    got = zsh_complete(comp_env, "model-switch model ")
    assert set(got) == {"add", "list", "show", "remove", "use", "import", "probe"}


@needs_zsh
def test_zsh_model_action_prefix_filter(comp_env):
    assert zsh_complete(comp_env, "model-switch model u") == ["use"]


@needs_zsh
def test_zsh_use_completes_model_names(comp_env):
    got = zsh_complete(comp_env, "model-switch model use ")
    assert set(got) == {"glm-z1", "kimi-k2"}


@needs_zsh
def test_zsh_remove_completes_model_names_with_prefix(comp_env):
    assert zsh_complete(comp_env, "model-switch model remove gl") == ["glm-z1"]


@needs_zsh
def test_zsh_use_completes_flags(comp_env):
    got = zsh_complete(comp_env, "model-switch model use --")
    assert set(got) == {"--driver", "--all-drivers", "--help"}


@needs_zsh
def test_zsh_driver_value_completes_driver_names(comp_env):
    got = zsh_complete(comp_env, "model-switch model use --driver ")
    assert set(got) == {"claude-code", "opencode"}


@needs_zsh
def test_zsh_status_completes_flags(comp_env):
    got = zsh_complete(comp_env, "model-switch status --")
    assert set(got) == {"--driver", "--all-drivers", "--help"}


@needs_zsh
def test_zsh_add_completes_flags(comp_env):
    got = zsh_complete(comp_env, "model-switch model add --")
    assert "--base-url" in got
    assert "--api-key" in got
    assert "--model-name" in got
    assert "--context-window" in got


@needs_zsh
def test_zsh_add_flag_value_offers_nothing(comp_env):
    got = zsh_complete(comp_env, "model-switch model add --base-url ")
    assert got == []


@needs_zsh
def test_zsh_init_offers_nothing(comp_env):
    assert zsh_complete(comp_env, "model-switch init ") == []


@needs_zsh
def test_zsh_import_completes_toml_files(comp_env, tmp_path):
    # Membership only: the harness's compadd shadow also observes one
    # unfiltered _files fallback round (see tests/zsh_capture.zsh header).
    (tmp_path / "sample.toml").write_text("")
    (tmp_path / "notes.txt").write_text("")
    got = zsh_complete(comp_env, "model-switch model import ", cwd=tmp_path)
    assert "sample.toml" in got


# --- mcp-plugin-mgr: test subcommand + --auto-allow (bash/zsh) ----------------


def _mcp_bash(env, words, cword, cwd=None):
    return bash_complete(env, words, cword, cwd=cwd,
                         script="mcp-plugin-mgr", func="_mcp_plugin_mgr")


def test_bash_mcp_top_level_includes_test(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", ""], 1)
    # The bash script's top-level word list also offers --help (pre-existing).
    assert set(got) == {"init", "add", "list", "remove", "presets", "status",
                        "test", "enable", "disable", "--help"}


def test_bash_mcp_disable_completes_servers(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "disable", ""], 2)
    assert set(got) == {"outline", "memos"}


def test_bash_mcp_enable_completes_servers(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "enable", ""], 2)
    assert set(got) == {"outline", "memos"}


def test_bash_mcp_test_completes_servers(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "test", ""], 2)
    assert set(got) == {"outline", "memos"}


def test_bash_mcp_test_completes_flags(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "test", "--"], 2)
    assert set(got) == {"--url", "--token", "--header", "--timeout", "--help"}


def test_bash_mcp_add_flags_include_auto_allow(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "add", "--auto"], 2)
    assert got == ["--auto-allow"]


def test_bash_mcp_remove_flags_include_auto_allow(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "remove", "--auto"], 2)
    assert got == ["--auto-allow"]


def test_bash_mcp_test_flag_value_offers_nothing(mcp_env):
    got = _mcp_bash(mcp_env, ["mcp-plugin-mgr", "test", "--timeout", ""], 3)
    assert got == []


@needs_zsh
def test_zsh_mcp_top_level_includes_test(mcp_env):
    got = zsh_complete(mcp_env, "mcp-plugin-mgr ")
    assert set(got) == {"init", "add", "list", "remove", "presets", "status",
                        "test", "enable", "disable"}


@needs_zsh
def test_zsh_mcp_test_completes_servers(mcp_env):
    got = zsh_complete(mcp_env, "mcp-plugin-mgr test ")
    assert set(got) == {"outline", "memos"}


@needs_zsh
def test_zsh_mcp_add_flags_include_auto_allow(mcp_env):
    got = zsh_complete(mcp_env, "mcp-plugin-mgr add --auto")
    assert got == ["--auto-allow"]


@needs_zsh
def test_zsh_mcp_remove_flags_include_auto_allow(mcp_env):
    got = zsh_complete(mcp_env, "mcp-plugin-mgr remove --auto")
    assert got == ["--auto-allow"]


@needs_zsh
def test_zsh_llmw_commands_and_flags():
    env = os.environ.copy()
    env["PATH"] = "{}{}{}".format(BIN, os.pathsep, env.get("PATH", ""))
    got = zsh_complete(env, "llmw-connect-mgr ")
    assert set(got) == {"install", "config", "upgrade", "uninstall"}
    got = zsh_complete(env, "llmw-connect-mgr uninstall --")
    assert set(got) == {"--remove-npm", "--purge", "--help"}
