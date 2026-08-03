"""Tests for built-in presets (V1 ships outline + memos, both http)."""
import pytest

from mcp_plugin_mgr.presets import PRESETS, PresetError, get_preset


def test_outline_preset_is_http_and_needs_url_and_token():
    p = get_preset("outline")
    assert p is not None
    assert p.transport == "http"
    with pytest.raises(PresetError):
        p.to_entry()                       # no url
    with pytest.raises(PresetError):
        p.to_entry(url="https://x/mcp")    # no token


def test_outline_preset_renders_bearer_header():
    e = get_preset("outline").to_entry(url="https://my/mcp", token="abc123")
    assert e.url == "https://my/mcp"
    assert e.headers == {"Authorization": "Bearer abc123"}


def test_outline_preset_extra_headers_layer_and_override():
    e = get_preset("outline").to_entry(
        url="https://x",
        token="t",
        extra_headers={"X-Custom": "v", "Authorization": "Bearer override"},
    )
    assert e.headers["Authorization"] == "Bearer override"
    assert e.headers["X-Custom"] == "v"


def test_memos_preset_is_http_and_needs_url_and_token():
    p = get_preset("memos")
    assert p is not None
    assert p.transport == "http"
    with pytest.raises(PresetError):
        p.to_entry()                            # no url
    with pytest.raises(PresetError):
        p.to_entry(url="https://memos.example/mcp")  # no token


def test_memos_preset_renders_bearer_header():
    e = get_preset("memos").to_entry(url="https://memos.example/mcp", token="tok")
    assert e.url == "https://memos.example/mcp"
    assert e.headers == {"Authorization": "Bearer tok"}


def test_get_preset_unknown_returns_none():
    assert get_preset("does-not-exist") is None


def test_presets_registry_contains_outline_and_memos():
    assert "outline" in PRESETS
    assert "memos" in PRESETS


def test_agent_html_drop_preset_is_http_and_needs_url_and_token():
    p = get_preset("agent-html-drop")
    assert p is not None
    assert p.transport == "http"
    with pytest.raises(PresetError):
        p.to_entry()                       # no url
    with pytest.raises(PresetError):
        p.to_entry(url="https://notes.example/mcp")  # no token


def test_agent_html_drop_preset_renders_bearer_header():
    e = get_preset("agent-html-drop").to_entry(
        url="https://notes.example/mcp", token="drop_tok"
    )
    assert e.url == "https://notes.example/mcp"
    assert e.headers == {"Authorization": "Bearer drop_tok"}


def test_agent_html_drop_preset_preapproves_all_six_tools():
    # upload_html writes large HTML (≤50MB) — exactly what the auto-mode
    # classifier false-positive blocks, so the preset enumerates all 6 tools
    # for --auto-allow rather than falling back to the server wildcard.
    p = get_preset("agent-html-drop")
    assert set(p.allow_tools) == {
        "mcp__agent-html-drop__upload_html",
        "mcp__agent-html-drop__list_html",
        "mcp__agent-html-drop__delete_html",
        "mcp__agent-html-drop__get_public_url",
        "mcp__agent-html-drop__list_annotations",
        "mcp__agent-html-drop__delete_annotation",
    }
