"""End-to-end tests for the shell completion scripts.

Both scripts are exercised as black boxes in a real bash / fish process,
driven through the same entry points an interactive shell would use:

  bash: source the script, set COMP_WORDS/COMP_CWORD, call _model_switch,
        then inspect COMPREPLY.
  fish: source the script, call `complete --do-complete="<line>"`.

Hermeticity: the scripts resolve dynamic candidates by shelling out to
`model-switch _complete ...`, so the subprocess env points PATH at the
repo's bin/ and XDG_CONFIG_HOME at a tmp dir holding a fixture
models.toml. The real user config is never touched (conftest's teardown
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


def _bash_quote(word):
    return "'" + word.replace("'", "'\\''") + "'"


def bash_complete(env, words, cword, cwd=None):
    """Simulate readline: set COMP_WORDS/COMP_CWORD, run _model_switch."""
    script = (
        'source "{}/model-switch.bash"\n'.format(COMPLETIONS)
        + "COMP_WORDS=({})\n".format(" ".join(_bash_quote(w) for w in words))
        + "COMP_CWORD={}\n".format(cword)
        + "_model_switch\n"
        + 'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    r = subprocess.run(
        ["bash", "-c", script], env=env, cwd=cwd, capture_output=True, text=True,
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


# --- bash ---------------------------------------------------------------------


def test_bash_top_level_commands(comp_env):
    got = bash_complete(comp_env, ["model-switch", ""], 1)
    assert set(got) == {"init", "model", "status"}


def test_bash_top_level_prefix_filter(comp_env):
    assert bash_complete(comp_env, ["model-switch", "m"], 1) == ["model"]


def test_bash_model_actions(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", ""], 2)
    assert set(got) == {"add", "list", "show", "remove", "use", "import"}


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


def test_bash_add_flag_value_offers_nothing(comp_env):
    got = bash_complete(comp_env, ["model-switch", "model", "add", "--base-url", ""], 4)
    assert got == []


def test_bash_init_offers_nothing(comp_env):
    assert bash_complete(comp_env, ["model-switch", "init", ""], 2) == []


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
    assert set(got) == {"add", "list", "show", "remove", "use", "import"}


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
