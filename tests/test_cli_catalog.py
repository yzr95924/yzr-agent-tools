"""CLI integration tests for catalog-sync semantics.

models.toml is the catalog source of truth; OpenCode mirrors every model into
its `yzr-*` provider namespace, and no deleted model's key may linger in any
agent config. Single-slot Claude Code is cleared when the active model is
removed.
"""
import json

import pytest

from model_switch.store import load_models, load_state

from _cli_runner import invoke_cli as runner


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


def _add(runner, name, key="K", model_name=None, base_url="https://x"):
    return runner([
        "model", "add", name,
        "--base-url", base_url, "--api-key", key,
        "--model-name", model_name or name,
    ])


def _use(runner, name, **kw):
    return runner(["model", "use", name], **kw)


# --- model add mirrors into an existing opencode catalog ----------------------

def test_model_add_updates_existing_opencode_catalog(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _use(runner, "glm", input="opencode\n")  # create opencode.json with catalog

    # Add a second model — its provider appears in the existing opencode.json
    # and the default pointer is preserved.
    _add(runner, "kimi", key="K2", model_name="kimi-k2")
    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-kimi" in cfg["provider"]
    assert cfg["model"] == "yzr-glm/glm-4"  # default unchanged


def test_model_add_does_not_create_opencode_file(yzr_paths):
    """No opencode.json exists (opencode never targeted) → `model add` must not
    conjure one out of thin air."""
    _add(runner, "glm", key="K1")
    assert not yzr_paths["opencode"].exists()


def test_model_add_does_not_hijack_foreign_default(yzr_paths):
    """opencode.json exists with the user's own default → `model add` mirrors
    our providers but must NOT touch their default pointer."""
    yzr_paths["opencode"].parent.mkdir(parents=True, exist_ok=True)
    yzr_paths["opencode"].write_text(json.dumps({
        "provider": {"anthropic": {"options": {"apiKey": "k"}}},
        "model": "anthropic/claude-sonnet-4",
    }), encoding="utf-8")

    _add(runner, "glm", key="K1", model_name="glm-4")
    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-glm" in cfg["provider"]
    assert cfg["model"] == "anthropic/claude-sonnet-4"


# --- model remove --------------------------------------------------------------

def test_model_remove_of_non_active_reclaims_provider_and_keeps_default(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _add(runner, "kimi", key="K2", model_name="kimi-k2")
    _use(runner, "glm", input="opencode\n")  # default = glm

    runner(["model", "remove", "kimi"])
    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-kimi" not in cfg["provider"]  # provider + key gone
    assert cfg["model"] == "yzr-glm/glm-4"    # default still points at glm


def test_model_remove_of_active_clears_claude_and_repoints_opencode(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _add(runner, "kimi", key="K2", model_name="kimi-k2")
    # Use on both agents (interactive all).
    _use(runner, "glm", input="all\n")
    assert "ANTHROPIC_AUTH_TOKEN" in json.loads(yzr_paths["settings"].read_text())["env"]

    runner(["model", "remove", "glm"])

    # Single-slot Claude Code is cleared of the deleted model's key.
    claude = json.loads(yzr_paths["settings"].read_text())
    assert "ANTHROPIC_AUTH_TOKEN" not in claude["env"]
    assert "model" not in claude
    # OpenCode default falls to the first remaining model; glm provider gone.
    opencode = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-glm" not in opencode["provider"]
    assert opencode["model"] == "yzr-kimi/kimi-k2"
    # State no longer claims an active model.
    assert load_state(yzr_paths["state"]).active_main is None


def test_model_remove_of_active_clears_claude_when_no_opencode(yzr_paths):
    """Even with no opencode involvement, removing the active model clears the
    claude-code slot (default driver)."""
    _add(runner, "glm", key="K1", model_name="glm-4")
    _use(runner, "glm")  # non-TTY → claude-code only
    assert "ANTHROPIC_AUTH_TOKEN" in json.loads(yzr_paths["settings"].read_text())["env"]

    runner(["model", "remove", "glm"])
    claude = json.loads(yzr_paths["settings"].read_text())
    assert "ANTHROPIC_AUTH_TOKEN" not in claude["env"]
    assert load_state(yzr_paths["state"]).active_main is None


# --- model use writes the full catalog -----------------------------------------

def test_model_use_opencode_writes_all_models(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _add(runner, "kimi", key="K2", model_name="kimi-k2")
    _use(runner, "kimi", input="opencode\n")

    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-glm" in cfg["provider"]
    assert "yzr-kimi" in cfg["provider"]
    assert cfg["model"] == "yzr-kimi/kimi-k2"


# --- model import --------------------------------------------------------------

def test_model_import_replace_reconciles_catalog(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _use(runner, "glm", input="opencode\n")
    assert "yzr-glm" in json.loads(yzr_paths["opencode"].read_text())["provider"]

    src = yzr_paths["config_dir"] / "incoming.toml"
    src.write_text(
        "[[models]]\n"
        'model_id = "new"\nname = "new-m"\nbase_url = "https://n"\napi_key = "NK"\n',
        encoding="utf-8",
    )
    runner(["model", "import", str(src)])

    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-glm" not in cfg["provider"]   # replaced model's provider reclaimed
    assert "yzr-new" in cfg["provider"]
    assert cfg["model"] == "yzr-new/new-m"    # default re-pointed to remaining
    assert load_state(yzr_paths["state"]).active_main is None  # glm was active


def test_model_import_merge_adds_provider_keeps_default(yzr_paths):
    _add(runner, "glm", key="K1", model_name="glm-4")
    _use(runner, "glm", input="opencode\n")

    src = yzr_paths["config_dir"] / "incoming.toml"
    src.write_text(
        "[[models]]\n"
        'model_id = "kimi"\nname = "kimi-k2"\nbase_url = "https://b"\napi_key = "K2"\n',
        encoding="utf-8",
    )
    runner(["model", "import", str(src), "--merge"])

    cfg = json.loads(yzr_paths["opencode"].read_text())
    assert "yzr-kimi" in cfg["provider"]
    assert cfg["model"] == "yzr-glm/glm-4"  # default preserved
