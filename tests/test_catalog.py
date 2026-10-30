"""Tests for catalog lookup of canonical Chat Completions providers."""
from model_switch import catalog
from _catalog_db import write_catalog_db


def _route(base_url, package):
    return {"base_url": base_url, "sdk": {"opencodeai": package}}


def _entry(api):
    return {"type": "chat", "api": api}


def test_default_route_uses_the_first_packaged_api():
    entry = _entry({
        "messages": {"base_url": "https://ours.example/anthropic"},
        "chat-completions": _route(
            "https://ours.example/v1", "@opencode/ai/p/chat"),
    })
    assert catalog.default_route(entry) == (
        "chat-completions", "https://ours.example/v1")


def test_model_candidates_only_accept_chat_completions_default_routes():
    data = {
        "ours": {"models": {"m": _entry({
            "chat-completions": _route("https://ours.example/v1", "@p/a"),
        })}},
        "messages-first": {"models": {"m": _entry({
            "messages": _route("https://ours.example/anthropic", "@p/m"),
            "chat-completions": _route("https://ours.example/v1", "@p/a"),
        })}},
    }
    assert [c.provider for c in catalog.model_candidates(data, "m")] == [
        "ours"]


def test_pick_requires_a_pin_when_candidates_are_ambiguous():
    data = {
        "a": {"models": {"m": _entry({
            "chat-completions": _route("https://a.example/v1", "@p/a"),
        })}},
        "b": {"models": {"m": _entry({
            "chat-completions": _route("https://b.example/v1", "@p/b"),
        })}},
    }
    cands = catalog.model_candidates(data, "m")
    picked = catalog.pick(cands)
    assert picked.candidate is None
    assert "ambiguous" in picked.reason
    assert catalog.pick(cands, pin="b").candidate.provider == "b"


def test_lookup_resolves_a_canonical_provider_and_model():
    data = {
        "zai-coding-plan": {"models": {"glm-5.3": _entry({
            "chat-completions": _route(
                "https://api.z.ai/api/coding/paas/v4", "@p/zai"),
        })}},
    }
    candidate = catalog.lookup(data, "zai-coding-plan", "glm-5.3")
    assert candidate.provider == "zai-coding-plan"
    assert candidate.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert catalog.lookup(data, "zai-coding-plan", "missing") is None


def test_load_cache_reads_opencode_snapshot(tmp_path):
    providers = {
        "ours": {"models": {"m": _entry({
            "chat-completions": _route("https://ours.example/v1", "@p/a"),
        })}},
    }
    db = write_catalog_db(tmp_path / "opencode.db", providers)
    data, desc = catalog.load_cache(db)
    assert data == providers
    assert "updated" in desc


def test_load_cache_reports_missing_database(tmp_path):
    data, desc = catalog.load_cache(tmp_path / "missing.db")
    assert data is None
    assert "no catalog cache" in desc
