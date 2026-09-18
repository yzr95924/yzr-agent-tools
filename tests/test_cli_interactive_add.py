"""Tests for interactive prompts in `model add`."""
import json

import pytest


from model_switch.store import load_models, load_state, save_models

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
    """Paste URL + key, then a search word and a number: every derivable
    field comes from the picker, and the upstream id is pre-filled with the
    catalog's spelling — Enter keeps it, since the id is asked, not guessed."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE,   # base URL
        "K",        # API key
        "glm",      # search
        "1",        # → zai/glm-4.7 (glm-4.7 sorts first)
        "",         # upstream id = the picked spelling
        "",         # local name = resolved id
        "",         # context window = catalog default
        "",         # description (skip)
        "y",        # Proceed?
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "decoy" not in result.stdout
    # The summary must mirror the entry that gets written.
    assert "About to add 'glm-4.7'" in result.stdout
    assert "context window  1M" in result.stdout
    assert "reasoning       yes" in result.stdout
    assert "variants        low, high" in result.stdout
    assert "modalities      text+image" in result.stdout
    m = load_models(catalog["models"]).models["glm-4.7"]
    assert m.name == "glm-4.7"
    assert m.base_url == ZAI_BASE
    assert m.api_key == "K"
    assert m.context_window == 1000000
    assert m.extra["reasoning"] is True
    assert list(m.extra["variants"]) == ["low", "high"]
    assert m.extra["modalities"] == {"input": ["text", "image"],
                                     "output": ["text"]}


def test_wizard_edited_upstream_id_carries_into_the_local_name(catalog):
    """The pick pre-fills the id but does not decide it: every provider spells
    the same model differently, so the typed id wins — and the local-name
    default follows it rather than the catalog's spelling."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE, "K",
        "glm-5",                  # 1 match
        "1",                      # → zai/glm-5.3
        "my-gateway/glm-5.3",     # the endpoint's own spelling
        "",                       # local name = the edited id
        "", "",                   # context window, description
        "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "Local name [my-gateway/glm-5.3]" in result.stdout
    m = load_models(catalog["models"]).models["my-gateway/glm-5.3"]
    assert m.name == "my-gateway/glm-5.3"
    assert m.context_window == 1000000  # catalog fields still applied


def test_wizard_strips_the_typed_upstream_id(catalog):
    """A pasted id with stray whitespace must not become a broken
    ANTHROPIC_MODEL."""
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "glm-5", "1",
        "  glm-5.3-edit  ",
        "", "",                   # context window, description
        "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert load_models(catalog["models"]).models["demo"].name == "glm-5.3-edit"


def test_add_strips_a_flagged_upstream_id(yzr_paths):
    """Same for `--model-name`: the id lands verbatim in agent configs."""
    result = runner([
        "model", "add", "demo",
        "--base-url", "https://x", "--api-key", "K",
        "--model-name", "  glm-5.3  ",
    ])
    assert result.exit_code == 0, result.stdout
    assert load_models(yzr_paths["models"]).models["demo"].name == "glm-5.3"


def test_wizard_back_refines_the_search(catalog):
    """'b' at the picker returns to the search prompt (first query matches
    two rows, the refined one matches a single row)."""
    result = runner(["model", "add"], input="\n".join([
        ZAI_BASE, "K",
        "glm",          # 2 matches
        "b",            # back — refine
        "glm-5",        # 1 match
        "1",            # → zai/glm-5.3
        "", "", "", "", # id / name / ctx / description defaults
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
        "", "", "", "",
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


# --- provider group inheritance ---------------------------------------------
#
# The driver groups models into `yzr-<name>` blocks keyed by
# (declared, base_url, api_key), and declared names beat derived host slugs —
# so an undeclared model on an upstream that already has a declared group
# lands in a *second* block (`yzr-<host>-2`). The wizard inherits the group
# name so the two stay in one block.

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/apps/anthropic"


def _seed_declared_group(provider="dashscope", name="qwen-max"):
    """Register one model declaring `provider` on the dashscope upstream."""
    result = runner([
        "model", "add", name,
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", name, "--provider", provider,
    ])
    assert result.exit_code == 0, result.stdout


def _add_second(name, inputs, api_key="K", base_url=DASHSCOPE_BASE):
    """Add a model with only the upstream flags set, so the prompts left are
    (provider group, when offered), context window, description, Proceed?."""
    return runner([
        "model", "add", name,
        "--base-url", base_url, "--api-key", api_key, "--model-name", name,
    ], input="\n".join(inputs) + "\n")


def test_add_prompts_provider_when_same_upstream_group_exists(yzr_paths):
    _seed_declared_group()
    result = _add_second("deepseek-v4-flash", [
        "",    # provider group → Enter = inherit 'dashscope'
        "",    # context window (skip)
        "",    # description (skip)
        "y",   # Proceed?
    ])
    assert result.exit_code == 0, result.stdout
    assert "Provider group" in result.stdout
    m = load_models(yzr_paths["models"]).models["deepseek-v4-flash"]
    assert m.extra["provider"] == "dashscope"


def test_add_provider_prompt_accepts_a_different_name(yzr_paths):
    _seed_declared_group()
    result = _add_second("second", ["qwen", "", "", "y"])
    assert result.exit_code == 0, result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert m.extra["provider"] == "qwen"


def test_add_no_provider_prompt_when_api_key_differs(yzr_paths):
    """A different key is a different upstream group: nothing to inherit, and
    the wizard must not spend a line on the prompt (three lines suffice)."""
    _seed_declared_group()
    result = _add_second("second", ["", "", "y"], api_key="K2")
    assert result.exit_code == 0, result.stdout
    assert "Provider group" not in result.stdout
    assert "still has a declared group" not in result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert "provider" not in m.extra


def test_add_provider_flag_preanswers_the_prompt(yzr_paths):
    """`--provider` wins over the inherited default, and asks nothing."""
    _seed_declared_group()
    result = runner([
        "model", "add", "second",
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", "second", "--provider", "other",
    ], input="\n".join(["", "", "y"]) + "\n")  # ctx, description, Proceed?
    assert result.exit_code == 0, result.stdout
    assert "Provider group" not in result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert m.extra["provider"] == "other"


def test_add_non_interactive_inherits_without_asking(yzr_paths):
    """No TTY means no prompt, but `_prompt` still applies the default — the
    script path must not keep splitting one upstream into two blocks."""
    _seed_declared_group()
    result = runner([
        "model", "add", "second",
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", "second",
    ])
    assert result.exit_code == 0, result.stdout
    assert "Provider group" not in result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert m.extra["provider"] == "dashscope"


def test_add_provider_prompt_accepts_no_declaration(yzr_paths):
    """`-` declines the inherited name, which is the only way to *drop* a
    declaration an entry already had — and the consequence is noted."""
    _seed_declared_group()
    result = _add_second("second", ["-", "", "", "y"])
    assert result.exit_code == 0, result.stdout
    assert "still has a declared group 'dashscope'" in result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert "provider" not in m.extra


def test_add_provider_flag_dash_drops_the_declaration(yzr_paths):
    """The same opt-out has to be expressible from a script."""
    _seed_declared_group()
    result = runner([
        "model", "add", "second",
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", "second", "--provider", "-",
    ], input="\n".join(["", "", "y"]) + "\n")  # ctx, description, Proceed?
    assert result.exit_code == 0, result.stdout
    assert "still has a declared group 'dashscope'" in result.stdout
    m = load_models(yzr_paths["models"]).models["second"]
    assert "provider" not in m.extra


def test_add_provider_dash_on_the_only_declarer_is_not_noted(yzr_paths):
    """Replacing the entry that declares the group itself: the declaration
    disappears with it, so the note must not claim the group is still there."""
    _seed_declared_group(name="qwen-max")
    result = runner([
        "model", "add", "qwen-max",
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", "qwen-max", "--provider", "-", "--yes",
    ])
    assert result.exit_code == 0, result.stdout
    assert "still has a declared group" not in result.stdout
    cfg = load_models(yzr_paths["models"])
    assert "provider" not in cfg.models["qwen-max"].extra


def test_add_dash_excludes_the_entry_named_at_the_prompt(yzr_paths):
    """Same as above with the local name typed at the prompt: the check runs
    *after* name resolution, so it excludes the replaced entry either way."""
    _seed_declared_group(name="qwen-max")
    result = runner(["model", "add", "--yes"], input="\n".join([
        DASHSCOPE_BASE, "K",   # base URL, key
        "-",                   # decline the inherited group 'dashscope'
        "qwen-max",            # upstream model id
        "",                    # local name → defaults to the upstream id
        "", "",                # context window, description
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "still has a declared group" not in result.stdout
    assert "provider" not in load_models(yzr_paths["models"]).models["qwen-max"].extra


def test_add_non_string_provider_is_a_clean_error(yzr_paths):
    """A hand-edited `provider = 123` must fail with one line, not a
    traceback — the grouping rule now raises while the wizard is running."""
    _seed_declared_group()
    reg = load_models(yzr_paths["models"])
    reg.models["qwen-max"].extra["provider"] = 123
    save_models(yzr_paths["models"], reg)

    result = runner([
        "model", "add", "second",
        "--base-url", DASHSCOPE_BASE, "--api-key", "K",
        "--model-name", "second",
    ])
    assert result.exit_code == 1
    assert "provider must be a string" in result.stderr
    assert "Traceback" not in result.stdout


def test_same_upstream_lands_in_one_provider_block(yzr_paths):
    """Regression: a second model on an already-declared upstream used to
    split into `yzr-dashscope` + `yzr-dashscope-2`."""
    _seed_declared_group()
    result = runner(["model", "use", "qwen-max", "--driver", "opencode"])
    assert result.exit_code == 0, result.stdout
    result = _add_second("deepseek-v4-flash", ["", "", "", "y"])
    assert result.exit_code == 0, result.stdout

    cfg = json.loads(yzr_paths["opencode"].read_text(encoding="utf-8"))
    ours = [pid for pid in cfg["provider"] if pid.startswith("yzr-")]
    assert ours == ["yzr-dashscope"], ours
    assert sorted(cfg["provider"]["yzr-dashscope"]["models"]) == [
        "deepseek-v4-flash", "qwen-max"]


# --- catalog search scope: the 'all' escape word -----------------------------
#
# Searches default to the pasted base_url's host, because the derived fields
# land in an entry talking to that upstream. `all <term>` widens one search
# to the whole catalog, ranks host matches first (MENU_MAX would otherwise
# bury them), tags the foreign rows, and notes a foreign pick.

def test_rank_host_first_partitions_keeping_search_order():
    from model_switch import catalog
    from model_switch.cli import _rank_host_first

    rows = [
        catalog.Row("decoy", "Decoy", "glm-5.3", {}),
        catalog.Row("zai", "Z.AI", "glm-4.7", {}),
        catalog.Row("zai", "Z.AI", "glm-5.3", {}),
    ]
    ranked = _rank_host_first(rows, {("zai", "glm-4.7"), ("zai", "glm-5.3")})
    assert [(r.provider, r.model) for r in ranked] == [
        ("zai", "glm-4.7"), ("zai", "glm-5.3"), ("decoy", "glm-5.3")]


def test_catalog_row_renderer_tags_only_foreign_rows():
    from model_switch import catalog
    from model_switch.cli import _catalog_row_renderer

    render = _catalog_row_renderer({("zai", "glm-5.3")})
    assert render(catalog.Row("zai", "Z.AI", "glm-5.3", {"name": "GLM-5.3"})) == \
        "zai/glm-5.3  GLM-5.3"
    foreign = render(catalog.Row("decoy", "Decoy", "glm-5.3", {"name": "GLM-5.3"}))
    assert foreign.endswith("[other host]")


def test_wizard_all_widens_to_other_providers(catalog):
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "all glm",   # widen: 2 host matches + 1 foreign
        "3",         # → decoy/glm-5.3 (last, after the host matches)
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "decoy/glm-5.3" in result.stdout
    assert "[other host]" in result.stdout
    assert "note: fields and id come from decoy" in result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.name == "glm-5.3"
    # The entry keeps the pasted upstream — only the derived fields came
    # from the foreign provider, which is exactly what the note warns about.
    assert m.base_url == ZAI_BASE


def test_wizard_all_ranks_host_matches_first(catalog):
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "all glm",
        "1",         # zai/glm-4.7 — a host match sorts first
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert out.index("zai/glm-4.7") < out.index("zai/glm-5.3") \
        < out.index("decoy/glm-5.3")
    # Only the foreign row carries the tag, and a host pick is not warned about.
    assert out.count("[other host]") == 1
    assert "note: fields and id come from" not in out
    assert load_models(catalog["models"]).models["demo"].name == "glm-4.7"


def test_wizard_all_without_a_term_reprompts(catalog):
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "all",       # no term — hint, then stay in the loop
        "glm", "1",  # host-scoped search still works
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "'all' needs a search term" in result.stdout
    assert load_models(catalog["models"]).models["demo"].name == "glm-4.7"


def test_wizard_all_no_match_reprompts(catalog):
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "all zzz",
        "glm", "1",
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "no catalog entry matches 'zzz' on any provider" in result.stdout
    assert load_models(catalog["models"]).models["demo"].name == "glm-4.7"


def test_wizard_host_miss_points_at_the_wide_search(catalog):
    result = runner(["model", "add", "demo"], input="\n".join([
        ZAI_BASE, "K",
        "zzz",       # nothing on this host → the hint must offer 'all'
        "glm", "1",
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "no catalog entry on api.z.ai matches 'zzz'" in result.stdout
    assert "'all <term>'" in result.stdout


def test_wizard_unknown_host_can_still_search_every_provider(catalog):
    """A gateway the catalog has never heard of must not dead-end at
    'type the id by hand' before the search loop even starts."""
    result = runner(["model", "add", "demo"], input="\n".join([
        "https://unknown.example/v1", "K",
        "",          # Enter at a 0-row host → hint to widen
        "all glm",
        "1",         # no host matches → decoy sorts first (decoy < zai)
        "", "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "0 model(s) on unknown.example" in result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.base_url == "https://unknown.example/v1"
    assert m.name == "glm-5.3"


def test_wizard_refuses_a_base_url_without_a_host(catalog):
    """A schemeless base URL has no host to scope by, and `catalog.search`
    reads "" as 'no filter' — offering the whole catalog as if it were the
    user's upstream, with nothing tagged foreign. Refuse the picker instead."""
    result = runner(["model", "add", "demo"], input="\n".join([
        "dashscope.aliyuncs.com/apps/anthropic", "K",  # no scheme
        "m",                                          # model id, typed by hand
        "", "", "y",
    ]) + "\n")
    assert result.exit_code == 0, result.stdout
    assert "has no host" in result.stdout
    assert "Search models" not in result.stdout
    m = load_models(catalog["models"]).models["demo"]
    assert m.base_url == "dashscope.aliyuncs.com/apps/anthropic"
    assert m.name == "m"


