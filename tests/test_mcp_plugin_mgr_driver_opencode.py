"""Tests for the OpenCode MCP driver (opencode.json mcp)."""
import json

import pytest

from mcp_plugin_mgr.drivers.opencode import OpenCodeMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP, TRANSPORT_STDIO


@pytest.fixture
def driver(tmp_path):
    return OpenCodeMcpDriver(
        config_path=tmp_path / ".config" / "opencode" / "opencode.json"
    )


def _http():
    return ServerEntry(
        name="outline",
        transport=TRANSPORT_HTTP,
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
    )


# --- render (vocabulary translation) ----------------------------------------

def test_render_http_uses_remote_vocab_with_enabled(driver):
    assert driver.render(_http()) == {
        "type": "remote",
        "url": "https://x/mcp",
        "enabled": True,
        "headers": {"Authorization": "Bearer t"},
    }


def test_render_http_without_headers_omits_key(driver):
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    assert driver.render(e) == {"type": "remote", "url": "https://x", "enabled": True}


def test_render_stdio_combines_command_into_array_and_uses_environment(driver):
    e = ServerEntry(
        name="g", transport=TRANSPORT_STDIO, command="uvx",
        args=["--from", "X", "run"], env={"K": "V"},
    )
    assert driver.render(e) == {
        "type": "local",
        "command": ["uvx", "--from", "X", "run"],
        "enabled": True,
        "environment": {"K": "V"},
    }


def test_render_stdio_without_env_omits_environment(driver):
    e = ServerEntry(name="g", transport=TRANSPORT_STDIO, command="uvx", args=["X"])
    out = driver.render(e)
    assert out == {"type": "local", "command": ["uvx", "X"], "enabled": True}
    assert "environment" not in out


# --- add / remove + preservation --------------------------------------------

def test_add_preserves_schema_provider_model_and_existing_servers(driver):
    cp = driver.config_path
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "model": "yzr/glm",
        "provider": {"yzr": {"npm": "@ai-sdk/anthropic"}},
        "mcp": {"existing": {"type": "remote", "url": "https://old", "enabled": True}},
    }))
    driver.add_server("outline", _http())
    data = json.loads(cp.read_text())
    # Disjoint keys owned by model-switch are untouched.
    assert data["$schema"] == "https://opencode.ai/config.json"
    assert data["model"] == "yzr/glm"
    assert data["provider"]["yzr"]["npm"] == "@ai-sdk/anthropic"
    assert "existing" in data["mcp"]
    assert data["mcp"]["outline"] == {
        "type": "remote", "url": "https://x/mcp", "enabled": True,
        "headers": {"Authorization": "Bearer t"},
    }


def test_remove_is_idempotent(driver):
    driver.add_server("outline", _http())
    assert driver.remove_server("outline") is True
    assert driver.remove_server("outline") is False


def test_driver_name(driver):
    assert driver.name == "opencode"
