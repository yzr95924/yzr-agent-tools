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


# --- per-shell adapters -------------------------------------------------------
#
# Every shell is driven through the same shape: a token list whose last
# element is the (possibly empty) token being completed. The adapters
# translate that into the shell's native driver call, so one behavior is
# written once and parametrized across shells.

def _bash_tokens(env, tokens, cwd=None):
    return bash_complete(env, list(tokens), len(tokens) - 1, cwd=cwd)


def _zsh_tokens(env, tokens, cwd=None):
    return zsh_complete(env, " ".join(tokens), cwd=cwd)


def _fish_tokens(env, tokens, cwd=None):
    return fish_complete(env, " ".join(tokens), cwd=cwd)


_SHELL_FUNCS = {"bash": _bash_tokens, "zsh": _zsh_tokens, "fish": _fish_tokens}
_SHELL_MARKS = {"bash": (), "zsh": (needs_zsh,), "fish": (needs_fish,)}


def shell_params(*names):
    """Fresh pytest.params for the named shells (bash always available)."""
    return [
        pytest.param(_SHELL_FUNCS[n], id=n, marks=_SHELL_MARKS[n]) for n in names
    ]


# --- model-switch: shared behaviors, parametrized across shells --------------


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_top_level_commands(comp_env, shell):
    got = shell(comp_env, ["model-switch", ""])
    assert set(got) == {"init", "model", "status"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh"))
def test_top_level_prefix_filter(comp_env, shell):
    assert shell(comp_env, ["model-switch", "m"]) == ["model"]


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_model_actions(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", ""])
    assert set(got) == {"add", "list", "show", "remove", "use", "import", "align"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh"))
def test_model_action_prefix_filter(comp_env, shell):
    assert shell(comp_env, ["model-switch", "model", "u"]) == ["use"]


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_use_completes_model_names(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "use", ""])
    assert set(got) == {"glm-z1", "kimi-k2"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_remove_completes_model_names_with_prefix(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "remove", "gl"])
    assert got == ["glm-z1"]


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_use_completes_flags(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "use", "--"])
    assert set(got) == {"--driver", "--all-drivers", "--help"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_driver_value_completes_driver_names(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "use", "--driver", ""])
    assert set(got) == {"claude-code", "opencode"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_status_completes_flags(comp_env, shell):
    got = shell(comp_env, ["model-switch", "status", "--"])
    assert set(got) == {"--driver", "--all-drivers", "--help"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh"))
def test_add_completes_flags(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "add", "--"])
    assert set(got) == {
        "--base-url", "--api-key", "--model-name", "--description",
        "--context-window", "--provider", "--catalog-provider",
        "--no-catalog", "--yes", "--help",
    }


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_remove_completes_flags(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "remove", "--"])
    assert set(got) == {"--yes", "--help"}


@pytest.mark.parametrize("shell", shell_params("bash", "zsh"))
def test_add_flag_value_offers_nothing(comp_env, shell):
    got = shell(comp_env, ["model-switch", "model", "add", "--base-url", ""])
    assert got == []


@pytest.mark.parametrize("shell", shell_params("bash", "zsh"))
def test_init_offers_nothing(comp_env, shell):
    assert shell(comp_env, ["model-switch", "init", ""]) == []


@pytest.mark.parametrize("shell", shell_params("bash", "zsh", "fish"))
def test_import_completes_files(comp_env, tmp_path, shell):
    (tmp_path / "sample.toml").write_text("")
    (tmp_path / "notes.txt").write_text("")
    got = shell(comp_env, ["model-switch", "model", "import", ""], cwd=tmp_path)
    assert "sample.toml" in got


def test_bash_align_completes_flags_and_models(comp_env):
    flags = _bash_tokens(comp_env, ["model-switch", "model", "align", "--"])
    assert set(flags) == {"--catalog-provider", "--help"}
    models = _bash_tokens(comp_env, ["model-switch", "model", "align", ""])
    assert set(models) == {"glm-z1", "kimi-k2"}


def test_fish_no_file_fallback_after_positional(comp_env, tmp_path):
    """Once the model name is given, an empty token must not offer files."""
    (tmp_path / "stray.toml").write_text("")
    got = _fish_tokens(comp_env, ["model-switch", "model", "use", "glm-z1", ""],
                       cwd=tmp_path)
    assert got == []


# --- mcp-plugin-mgr: bash/zsh only (no fish script) ---------------------------


def _mcp_bash_tokens(env, tokens, cwd=None):
    return bash_complete(env, list(tokens), len(tokens) - 1, cwd=cwd,
                         script="mcp-plugin-mgr", func="_mcp_plugin_mgr")


@pytest.mark.parametrize("shell, expected", [
    pytest.param(_mcp_bash_tokens, {"init", "add", "list", "remove", "presets",
                                    "status", "test", "enable", "disable",
                                    "--help"}, id="bash"),
    pytest.param(_zsh_tokens, {"init", "add", "list", "remove", "presets",
                               "status", "test", "enable", "disable"},
                 id="zsh", marks=needs_zsh),
])
def test_mcp_top_level_includes_test(mcp_env, shell, expected):
    assert set(shell(mcp_env, ["mcp-plugin-mgr", ""])) == expected


@pytest.mark.parametrize("shell, action", [
    pytest.param(_mcp_bash_tokens, "disable", id="bash-disable"),
    pytest.param(_mcp_bash_tokens, "enable", id="bash-enable"),
    pytest.param(_mcp_bash_tokens, "test", id="bash-test"),
    pytest.param(_zsh_tokens, "test", id="zsh-test", marks=needs_zsh),
])
def test_mcp_server_name_completion(mcp_env, shell, action):
    got = shell(mcp_env, ["mcp-plugin-mgr", action, ""])
    assert set(got) == {"outline", "memos"}


def test_mcp_test_completes_flags(mcp_env):
    got = _mcp_bash_tokens(mcp_env, ["mcp-plugin-mgr", "test", "--"])
    assert set(got) == {"--url", "--token", "--header", "--timeout", "--help"}


@pytest.mark.parametrize("shell", [
    pytest.param(_mcp_bash_tokens, id="bash"),
    pytest.param(_zsh_tokens, id="zsh", marks=needs_zsh),
])
def test_mcp_add_flags_include_auto_allow(mcp_env, shell):
    assert shell(mcp_env, ["mcp-plugin-mgr", "add", "--auto"]) == ["--auto-allow"]


@pytest.mark.parametrize("shell", [
    pytest.param(_mcp_bash_tokens, id="bash"),
    pytest.param(_zsh_tokens, id="zsh", marks=needs_zsh),
])
def test_mcp_remove_flags_include_auto_allow(mcp_env, shell):
    got = shell(mcp_env, ["mcp-plugin-mgr", "remove", "--auto"])
    assert got == ["--auto-allow"]


def test_mcp_test_flag_value_offers_nothing(mcp_env):
    got = _mcp_bash_tokens(mcp_env, ["mcp-plugin-mgr", "test", "--timeout", ""])
    assert got == []


@needs_zsh
def test_zsh_llmw_commands_and_flags():
    env = os.environ.copy()
    env["PATH"] = "{}{}{}".format(BIN, os.pathsep, env.get("PATH", ""))
    got = zsh_complete(env, "llmw-connect-mgr ")
    assert set(got) == {"install", "config", "upgrade", "uninstall"}
    got = zsh_complete(env, "llmw-connect-mgr uninstall --")
    assert set(got) == {"--remove-npm", "--purge", "--help"}
