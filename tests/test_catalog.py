"""Unit tests for catalog-derivation from OpenCode's models.dev cache.

Pure functions with injected data — no file I/O except `load_cache`, no
network anywhere (asserted). The mapping rules decide what model-switch
writes into models.toml, so each rule gets an explicit case.
"""
import json
import socket

import pytest

from model_switch import catalog


def _entry(name=None, options=None, limit=None, modalities=None):
    entry = {}
    if options is not None:
        entry["reasoning_options"] = options
    if limit is not None:
        entry["limit"] = limit
    if modalities is not None:
        entry["modalities"] = modalities
    return entry


def _full_options():
    return [
        {"type": "toggle"},
        {"type": "effort", "values": ["low", "medium", "xhigh"]},
        {"type": "budget_tokens", "min": 0, "max": 262144},
    ]


def _cache(providers):
    return {p: {"api": api, "models": models}
            for p, (api, models) in providers.items()}


# --- host_of -------------------------------------------------------------------

def test_host_of_strips_scheme_and_path():
    assert catalog.host_of("https://api.z.ai/api/anthropic") == "api.z.ai"
    assert catalog.host_of("HTTPS://API.Z.AI/x") == "api.z.ai"
    assert catalog.host_of("") == ""
    assert catalog.host_of(None) == ""


# --- load_cache ----------------------------------------------------------------

def test_load_cache_missing_file_reports_reason(tmp_path):
    data, desc = catalog.load_cache(tmp_path / "nope.json")
    assert data is None
    assert "no catalog cache" in desc


def test_load_cache_broken_json_reports_reason(tmp_path):
    p = tmp_path / "models.json"
    p.write_text("{ not json", encoding="utf-8")
    data, desc = catalog.load_cache(p)
    assert data is None
    assert "unreadable" in desc


def test_load_cache_returns_data_and_mtime_description(tmp_path):
    p = tmp_path / "models.json"
    p.write_text(json.dumps({"a": {"api": "https://a", "models": {}}}),
                 encoding="utf-8")
    data, desc = catalog.load_cache(p)
    assert data == {"a": {"api": "https://a", "models": {}}}
    assert "updated" in desc and str(p) in desc


# --- candidates / pick ---------------------------------------------------------

def test_candidates_marks_host_match_and_sorts():
    data = _cache({
        "zzz-other": ("https://other.example.com/v1", {"m": _entry()}),
        "aaa-ours": ("https://ours.example.com/v1", {"m": _entry()}),
        "no-model": ("https://ours.example.com/v1", {}),
    })
    cands = catalog.candidates(data, "m", "https://ours.example.com/anthropic")
    assert [c.provider for c in cands] == ["aaa-ours", "zzz-other"]
    assert [c.host_match for c in cands] == [True, False]


def test_pick_single_host_match_wins_over_non_matching():
    data = _cache({
        "aaa-trap": ("https://other.example.com/v1", {"m": _entry()}),
        "zzz-ours": ("https://ours.example.com/v1", {"m": _entry()}),
    })
    picked = catalog.pick(catalog.candidates(data, "m", "https://ours.example.com"))
    assert picked.candidate.provider == "zzz-ours"
    assert "host match" in picked.reason


def test_pick_accepts_identical_host_matches_deterministically():
    entry = _entry(options=_full_options())
    data = _cache({
        "b-plan": ("https://z.example.com/v1", {"m": entry}),
        "a-plan": ("https://z.example.com/v2", {"m": entry}),
    })
    picked = catalog.pick(catalog.candidates(data, "m", "https://z.example.com"))
    assert picked.candidate.provider == "a-plan"  # alphabetical, stable
    assert [c.provider for c in picked.alternatives] == ["b-plan"]
    assert "agree" in picked.reason


def test_pick_refuses_conflicting_host_matches():
    data = _cache({
        "a": ("https://z.example.com/v1",
              {"m": _entry(options=[{"type": "effort", "values": ["low"]}])}),
        "b": ("https://z.example.com/v2",
              {"m": _entry(options=[{"type": "effort", "values": ["high"]}])}),
    })
    picked = catalog.pick(catalog.candidates(data, "m", "https://z.example.com"))
    assert picked.candidate is None
    assert "conflicting" in picked.reason
    assert len(picked.alternatives) == 2


@pytest.mark.parametrize("data, base_url, pin, reason_substr, alternatives", [
    pytest.param(
        _cache({"a": ("https://other.example.com/v1", {"m": _entry()})}),
        "https://ours.example.com", None, "no candidate api host", ["a"],
        id="no-host-match"),
    pytest.param(
        _cache({"a": ("https://z.example.com/v1", {"m": _entry()})}),
        "https://z.example.com", "nope", "nope", ["a"],
        id="unknown-pin"),
    pytest.param({}, "https://ours.example.com", None, "no entry", [],
                 id="no-candidates"),
])
def test_pick_refusals(data, base_url, pin, reason_substr, alternatives):
    kwargs = {"pin": pin} if pin is not None else {}
    picked = catalog.pick(catalog.candidates(data, "m", base_url), **kwargs)
    assert picked.candidate is None
    assert reason_substr in picked.reason
    assert [c.provider for c in picked.alternatives] == alternatives


def test_pick_pin_wins_even_with_conflicts():
    data = _cache({
        "a": ("https://z.example.com/v1",
              {"m": _entry(options=[{"type": "effort", "values": ["low"]}])}),
        "b": ("https://z.example.com/v2",
              {"m": _entry(options=[{"type": "effort", "values": ["high"]}])}),
    })
    picked = catalog.pick(catalog.candidates(data, "m", "https://z.example.com"),
                          pin="b")
    assert picked.candidate.provider == "b"
    assert "pinned" in picked.reason


# --- derive --------------------------------------------------------------------

def test_derive_effort_tiers_ignore_toggle():
    """OpenCode's own derivation emits effort tiers only, dropping the
    toggle, so we drop it too — a declared toggle must not add a tier."""
    fields = catalog.derive(_entry(
        options=_full_options(),
        limit={"context": 1000000, "output": 131072},
        modalities={"input": ["text", "image", "video", "pdf"], "output": ["text"]},
    ))
    assert fields["context_window"] == 1000000
    assert fields["reasoning"] is True
    assert fields["variants"] == {
        "low": {"effort": "low", "thinking": {"type": "adaptive"}},
        "medium": {"effort": "medium", "thinking": {"type": "adaptive"}},
        "xhigh": {"effort": "xhigh", "thinking": {"type": "adaptive"}},
    }
    # video is dropped: the Anthropic wire format has no such part.
    assert fields["modalities"] == {"input": ["text", "image", "pdf"],
                                    "output": ["text"]}


def test_derive_effort_only_lists_effort_tiers():
    fields = catalog.derive(_entry(
        options=[{"type": "effort", "values": ["low", "high", "max"]}]))
    assert list(fields["variants"]) == ["low", "high", "max"]


def test_derive_none_effort_becomes_thinking_off():
    """`none` has no Anthropic effort slot, so it is translated to the shape
    every gateway calls thinking-off — and keeps its name."""
    fields = catalog.derive(_entry(
        options=[{"type": "effort", "values": ["none", "minimal", "low"]}]))
    assert fields["variants"] == {
        "none": {"thinking": {"type": "disabled"}},
        "low": {"effort": "low", "thinking": {"type": "adaptive"}},
    }


def test_derive_skips_minimal_effort_value():
    fields = catalog.derive(_entry(
        options=[{"type": "effort", "values": ["minimal", "low"]}]))
    assert list(fields["variants"]) == ["low"]


def test_derive_toggle_only_gets_no_tiers():
    entry = _entry(options=[{"type": "toggle"}])
    fields = catalog.derive(entry)
    assert fields["variants"] == {}
    assert fields["reasoning"] is True
    assert catalog.no_tiers_declared(entry) is True


def test_derive_budget_only_gets_no_tiers():
    entry = _entry(options=[{"type": "budget_tokens", "min": 0, "max": 32768}])
    fields = catalog.derive(entry)
    assert fields["variants"] == {}
    assert fields["reasoning"] is True
    assert catalog.no_tiers_declared(entry) is True


def test_derive_all_skippable_efforts_yield_no_tiers():
    entry = _entry(options=[{"type": "effort", "values": ["minimal"]}])
    assert catalog.derive(entry)["variants"] == {}
    assert catalog.no_tiers_declared(entry) is True


def test_derive_without_options_is_not_reasoning():
    fields = catalog.derive(_entry(limit={"context": 8192}))
    assert fields["reasoning"] is False
    assert fields["variants"] == {}
    assert catalog.no_tiers_declared({}) is False


def test_no_tiers_declared_false_when_a_tier_derives():
    assert catalog.no_tiers_declared(
        _entry(options=[{"type": "effort", "values": ["minimal", "low"]}])) is False


def test_derive_text_only_modalities_stay_undeclared():
    fields = catalog.derive(_entry(modalities={"input": ["text"], "output": ["text"]}))
    assert fields["modalities"] is None


def test_derive_missing_or_invalid_context_is_none():
    assert catalog.derive(_entry())["context_window"] is None
    assert catalog.derive(_entry(limit={"context": 0}))["context_window"] is None


def test_derive_capability_flags_only_when_true():
    """OpenCode's model config treats an absent flag as false, so only a
    declared ``true`` carries information; false/null/missing derive None."""
    entry = _entry()
    assert catalog.derive(entry)["temperature"] is None
    assert catalog.derive(entry)["attachment"] is None
    entry["temperature"] = False
    entry["attachment"] = None
    fields = catalog.derive(entry)
    assert fields["temperature"] is None
    assert fields["attachment"] is None
    entry["temperature"] = True
    entry["attachment"] = True
    fields = catalog.derive(entry)
    assert fields["temperature"] is True
    assert fields["attachment"] is True


def test_derive_display_name_from_entry_name():
    entry = _entry()
    entry["name"] = "  Kimi K3  "
    assert catalog.derive(entry)["display_name"] == "Kimi K3"
    entry["name"] = "   "
    assert catalog.derive(entry)["display_name"] is None
    assert catalog.derive(_entry())["display_name"] is None
    assert catalog.derive(_entry(limit={"output": 100}))["context_window"] is None


def test_derive_modalities_without_text_input_is_none():
    fields = catalog.derive(_entry(modalities={"input": ["video"], "output": ["text"]}))
    assert fields["modalities"] is None


def test_derive_drops_output_modalities_the_anthropic_path_cannot_produce():
    """Entries describe their provider's OpenAI-compatible endpoint, where a
    TTS model may declare audio output — this path only ever returns text."""
    fields = catalog.derive(_entry(
        modalities={"input": ["text", "image"], "output": ["audio"]}))
    assert fields["modalities"] == {"input": ["text", "image"], "output": ["text"]}


# --- search --------------------------------------------------------------------

def _search_cache():
    return {
        "zai": {
            "id": "zai", "name": "Z.AI", "api": "https://api.z.ai/api/paas/v4",
            "models": {
                "glm-5.3": _entry(limit={"context": 1000000}),
                "glm-4.7": _entry(),
                "text-only": _entry(),
            },
        },
        "kimi-for-coding": {
            "id": "kimi-for-coding", "name": "Kimi For Coding",
            "api": "https://api.kimi.com/coding/v1",
            "models": {"k3": _entry()},
        },
        "decoy": {
            "id": "decoy", "name": "Decoy", "api": "https://decoy.example/v1",
            "models": {"glm-5.3": _entry()},
        },
    }


def test_search_returns_everything_sorted_without_query():
    data = _search_cache()
    rows = catalog.search(data)
    assert [(r.provider, r.model) for r in rows] == [
        ("decoy", "glm-5.3"),
        ("kimi-for-coding", "k3"),
        ("zai", "glm-4.7"),
        ("zai", "glm-5.3"),
        ("zai", "text-only"),
    ]
    assert rows[0].entry is data["decoy"]["models"]["glm-5.3"]


def test_search_matches_model_id_case_insensitively():
    rows = catalog.search(_search_cache(), "GLM")
    assert [(r.provider, r.model) for r in rows] == [
        ("decoy", "glm-5.3"), ("zai", "glm-4.7"), ("zai", "glm-5.3")]


def test_search_matches_provider_id_and_display_name():
    assert [r.model for r in catalog.search(_search_cache(), "kimi")] == ["k3"]
    assert [r.model for r in catalog.search(_search_cache(), "z.a")] == [
        "glm-4.7", "glm-5.3", "text-only"]


def test_search_requires_all_tokens():
    """Multi-token queries narrow instead of OR-ing the tokens."""
    assert [r.model for r in catalog.search(_search_cache(), "zai glm-5")] == [
        "glm-5.3"]
    assert catalog.search(_search_cache(), "zai k3") == []


def test_search_host_filter_keeps_only_that_upstream():
    rows = catalog.search(_search_cache(), "", host="api.z.ai")
    assert [(r.provider, r.model) for r in rows] == [
        ("zai", "glm-4.7"), ("zai", "glm-5.3"), ("zai", "text-only")]
    assert catalog.search(_search_cache(), "", host="nowhere.example") == []


def test_search_matches_model_display_name():
    data = _search_cache()
    data["zai"]["models"]["glm-4.7"]["name"] = "Legacy Falcon"
    assert [r.model for r in catalog.search(data, "falcon")] == ["glm-4.7"]


def test_search_tolerates_malformed_provider_shapes():
    rows = catalog.search({"broken": None, "nouser": {"api": "https://x"}})
    assert rows == []


# --- no network, ever ----------------------------------------------------------

def test_catalog_never_opens_a_socket(tmp_path, monkeypatch):
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps(_cache({
        "ours": ("https://ours.example.com/v1", {"m": _entry(
            options=_full_options(),
            limit={"context": 1000},
            modalities={"input": ["text", "image"], "output": ["text"]},
        )}),
    })), encoding="utf-8")

    def _boom(*_a, **_k):
        raise AssertionError("catalog code must never touch the network")

    monkeypatch.setattr(socket, "socket", _boom)
    data, _desc = catalog.load_cache(cache)
    picked = catalog.pick(catalog.candidates(data, "m", "https://ours.example.com"))
    assert catalog.derive(picked.candidate.entry)["context_window"] == 1000
