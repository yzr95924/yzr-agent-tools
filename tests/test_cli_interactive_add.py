"""Tests for interactive prompts in `model add`."""
import json

import pytest


from model_switch.store import load_models, load_state

from _cli_runner import invoke_cli as runner


ZAI_BASE = "https://api.z.ai/api/anthropic"
NEW_BASE = "https://api.z.ai/api/anthropic/v2"


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    return _isolate_yzr_state


def _add_with_input(extra_args, inputs):
    """Invoke `model add <name>` with extra CLI args and stdin input lines.

    Tests list every line explicitly, including the final wizard
    confirmation ("Proceed?" → `y`).
    """
    args = ["model", "add", "demo"] + extra_args
    return runner(args, input="\n".join(inputs) + "\n")


def _entry(name="GLM-5.3", context=1000000):
    return {
        "name": name,
        "limit": {"context": context},
        "reasoning_options": [{"type": "effort", "values": ["low", "high"]}],
        "modalities": {"input": ["text", "image"], "output": ["text"]},
    }


@pytest.fixture
def catalog(yzr_paths):
    """A cache with one provider on the wizard's host and a decoy on another.

    `glm-4.7` sorts before `glm-5.3`, so picking `1` after searching "glm"
    selects `zai/glm-4.7`; the decoy provider must never appear in a
    host-filtered menu.
    """
    yzr_paths["catalog"].parent.mkdir(parents=True, exist_ok=True)
    yzr_paths["catalog"].write_text(json.dumps({
        "zai": {"id": "zai", "name": "Z.AI",
                "api": "https://api.z.ai/api/paas/v4",
                "models": {"glm-5.3": _entry("GLM-5.3"),
                           "glm-4.7": _entry("GLM-4.7")}},
        "decoy": {"id": "decoy", "name": "Decoy Inc",
                  "api": "https://decoy.example/v1",
                  "models": {"glm-5.3": _entry("GLM-5.3")}},
    }), encoding="utf-8")
    return yzr_paths


# --- non-interactive: full flags still works (back-compat) ------------------

def test_add_with_all_flags_does_not_prompt(yzr_paths):
    result = runner([
        "model", "add", "glm",
        "--base-url", "https://x",
        "--api-key", "KEY",
        "--model-name", "m",
        "--context-window", "1000000",
    ])
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["glm"].context_window == 1000000


def test_add_defaults_model_name_to_local_id(yzr_paths):
    """Without --model-name the upstream id defaults to the local id, so
    scripts can add a model with just base_url + api_key (catalog fill-in
    looks the id up itself)."""
    result = runner([
        "model", "add", "MiniMax-M3",
        "--base-url", "https://api.minimaxi.com/anthropic",
        "--api-key", "KEY",
    ])
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["MiniMax-M3"].name == "MiniMax-M3"


# --- interactive prompts -----------------------------------------------------

def test_add_prompts_for_missing_base_url(yzr_paths):
    result = _add_with_input(
        ["--api-key", "KEY", "--model-name", "m"],
        ["https://api.example.com", "", "", "y"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].base_url == "https://api.example.com"


def test_add_prompts_for_missing_api_key(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--model-name", "m"],
        ["API_KEY", "", "", "y"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].api_key == "API_KEY"


def test_add_prompts_for_missing_model_name(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY"],
        ["MiniMax-M3", "", "", "y"],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].name == "MiniMax-M3"


def test_add_prompts_for_context_window_with_default(yzr_paths):
    """Context window prompt is optional: pressing Enter yields None (no default)."""
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m"],
        ["", "", "y"],  # context, description, Proceed?
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].context_window is None


def test_add_omitting_context_window_yields_none(yzr_paths):
    """Even without any context window input the field should remain None,
    not silently default to a hard-coded number."""
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m"],
        ["", "", "y"],  # context, description, Proceed?
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].context_window is None


def test_add_prompts_for_context_window_with_explicit_value(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m"],
        ["1000000", "", "y"],  # context, description, Proceed?,
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].context_window == 1000000


def test_add_prompts_for_description_optional(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m",
         "--context-window", "200000"],
        ["", "y"],  # description, Proceed?,
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    assert cfg.models["demo"].description in (None, "")


def test_add_prompts_for_all_when_nothing_provided(yzr_paths):
    """Worst case: name only on CLI, everything else prompted in order."""
    result = _add_with_input(
        [],
        [
            "https://api.minimaxi.com/anthropic",  # base_url
            "MiniMax_API_KEY",                     # api_key
            "MiniMax-M3",                          # model_name
            "1000000",                             # context_window
            "",                                    # description (skip)
            "y",                                   # Proceed?
        ],
    )
    assert result.exit_code == 0, result.stdout
    cfg = load_models(yzr_paths["models"])
    m = cfg.models["demo"]
    assert m.base_url == "https://api.minimaxi.com/anthropic"
    assert m.api_key == "MiniMax_API_KEY"
    assert m.name == "MiniMax-M3"
    assert m.context_window == 1000000


# --- catalog wizard ----------------------------------------------------------

def test_wizard_picks_from_catalog_and_derives_fields(catalog):
    """Paste URL + key, then a search word and a number: the upstream id and
    every derivable field come from the picker, nothing is typed."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE,   # base URL
        "K",        # API key
        "glm",      # search
        "1",        # → zai/glm-4.7 (glm-4.7 sorts first)
        "",         # local name = picked id
        "",         # context window = catalog default
        "",         # description (skip)
        "y",        # Proceed?
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "decoy" not in result.stdout
    m = load_models(catalog["models"]).models["glm-4.7"]
    assert m.name == "glm-4.7"
    assert m.base_url == ZAI_BASE
    assert m.api_key == "K"
    assert m.context_window == 1000000
    assert m.extra["reasoning"] is True
    assert list(m.extra["variants"]) == ["low", "high"]
    assert m.extra["modalities"] == {"input": ["text", "image"],
                                     "output": ["text"]}


def test_wizard_back_refines_the_search(catalog):
    """'b' at the picker returns to the search prompt (first query matches
    two rows, the refined one matches a single row)."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE, "K",
        "glm",          # 2 matches
        "b",            # back — refine
        "glm-5",        # 1 match
        "1",            # → zai/glm-5.3
        "", "", "",     # name / ctx / description defaults
        "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    m = load_models(catalog["models"]).models["glm-5.3"]
    assert m.name == "glm-5.3"
    assert m.context_window == 1000000


def test_wizard_skip_falls_back_to_manual_id(catalog):
    """'skip' (or no matching host) keeps the old typed flow alive."""
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "skip",       # do not use the catalog
        "my-model",   # upstream id typed by hand
        "",           # context window (no catalog match → optional)
        "",           # description
        "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.name == "my-model"
    assert m.context_window is None


def test_wizard_no_match_reprompts_the_search(catalog):
    """A query with no hits must not end the wizard — it re-asks."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE, "K",
        "nope",      # no match → re-prompt
        "glm-5.3",   # 1 match
        "1",
        "", "", "",
        "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "no catalog entry" in result.stdout
    assert "glm-5.3" in load_models(catalog["models"]).models


def test_wizard_confirm_no_writes_nothing(catalog):
    """Answering 'n' at the final gate must leave models.toml untouched."""
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "skip", "m", "", "",
        "n",         # Proceed? → no
    ]) + "\n")
    assert result.exit_code != 0
    assert "nothing written" in result.stdout
    assert "demo" not in load_models(catalog["models"]).models


def test_wizard_yes_skips_the_confirmation(catalog):
    """`--yes` must not even ask: with input ending right after the last
    real prompt, a stray confirmation would hit EOF and abort."""
    result = runner(["model", "add", "demo", "--base-url", ZAI_BASE,
                     "--api-key", "K", "--model-name", "m", "--yes"],
                    input="\n\n")  # context window, description
    assert result.exit_code == 0, result.stdout
    assert "About to add" not in result.stdout
    assert "demo" in load_models(catalog["models"]).models


# --- overwriting an existing name -------------------------------------------

def test_wizard_duplicate_declined_asks_for_a_new_name(catalog):
    runner(["model", "add", "demo", "--base-url", "https://old",
            "--api-key", "K", "--model-name", "m"])
    result = runner(["model", "add", "demo"], input="\n".join([
        NEW_BASE, "K2",
        "skip", "m2",
        "n",         # Overwrite it? → no
        "demo2",     # different local name
        "", "",      # context window, description
        "y",         # Proceed?
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    cfg = load_models(catalog["models"])
    assert cfg.models["demo"].base_url == "https://old"
    assert cfg.models["demo2"].base_url == NEW_BASE


def test_wizard_duplicate_accepted_replaces(catalog):
    runner(["model", "add", "demo", "--base-url", "https://old",
            "--api-key", "K", "--model-name", "m"])
    result = runner(["model", "add", "demo"], input="\n".join([
        NEW_BASE, "K2",
        "skip", "m2",
        "y",         # Overwrite it? → yes
        "", "",      # context window, description
        "y",         # Proceed?
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "replaces existing" in result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.base_url == NEW_BASE
    assert m.api_key == "K2"
    assert m.name == "m2"


def test_add_noninteractive_yes_overwrites_without_prompt(catalog):
    runner(["model", "add", "demo", "--base-url", "https://old",
            "--api-key", "K", "--model-name", "m"])
    result = runner(["model", "add", "demo", "--base-url", NEW_BASE,
                     "--api-key", "K2", "--model-name", "m2", "--yes"])
    assert result.exit_code == 0, result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.base_url == NEW_BASE


def test_overwriting_the_active_model_hints_and_leaves_agents_alone(catalog):
    runner(["model", "add", "demo", "--base-url", "https://old",
            "--api-key", "K", "--model-name", "m"])
    runner(["model", "use", "demo"])
    result = runner(["model", "add", "demo", "--base-url", NEW_BASE,
                     "--api-key", "K2", "--model-name", "m2", "--yes"])
    assert result.exit_code == 0, result.stdout
    assert "is the active model" in result.stdout
    assert load_state(catalog["state"]).active_main == "demo"
    # `add` mirrors OpenCode's catalog but must not rewrite the single-slot
    # agent config — that only happens on `model use`.
    assert "https://old" in catalog["settings"].read_text()

# --- token-count type errors -------------------------------------------------

def test_add_reprompts_on_a_bad_token_count(yzr_paths):
    """Typing a non-number at the context prompt must re-ask, not traceback."""
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m"],
        ["abc", "200000", "", "y"],  # bad, good, description, Proceed?
    )
    assert result.exit_code == 0, result.stdout
    assert "int expected" in result.stdout
    assert "Traceback" not in result.stdout
    assert load_models(yzr_paths["models"]).models["demo"].context_window == 200000


def test_add_bad_token_count_then_enter_skips(yzr_paths):
    result = _add_with_input(
        ["--base-url", "https://x", "--api-key", "KEY", "--model-name", "m"],
        ["abc", "", "", "y"],
    )
    assert result.exit_code == 0, result.stdout
    assert load_models(yzr_paths["models"]).models["demo"].context_window is None
