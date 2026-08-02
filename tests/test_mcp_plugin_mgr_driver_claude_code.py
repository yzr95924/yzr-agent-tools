"""Tests for the Claude Code MCP driver (~/.claude.json mcpServers)."""
import json

import pytest

from mcp_plugin_mgr.drivers.claude_code import ClaudeCodeMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP, TRANSPORT_STDIO


@pytest.fixture
def driver(tmp_path):
    return ClaudeCodeMcpDriver(config_path=tmp_path / ".claude.json")


def _http():
    return ServerEntry(
        name="outline",
        transport=TRANSPORT_HTTP,
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
    )


# --- render ------------------------------------------------------------------

def test_render_http(driver):
    assert driver.render(_http()) == {
        "type": "http",
        "url": "https://x/mcp",
        "headers": {"Authorization": "Bearer t"},
    }


def test_render_http_without_headers_omits_key(driver):
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    assert driver.render(e) == {"type": "http", "url": "https://x"}


def test_render_stdio(driver):
    e = ServerEntry(
        name="g", transport=TRANSPORT_STDIO, command="uvx",
        args=["--from", "X", "run"], env={"K": "V"},
    )
    assert driver.render(e) == {
        "type": "stdio", "command": "uvx",
        "args": ["--from", "X", "run"], "env": {"K": "V"},
    }


def test_render_stdio_always_emits_env(driver):
    # Matches what `claude mcp add` writes (env: {} even when empty).
    e = ServerEntry(name="g", transport=TRANSPORT_STDIO, command="uvx")
    assert driver.render(e)["env"] == {}


# --- add / list / has / remove ----------------------------------------------

def test_add_then_has_and_list(driver):
    driver.add_server("outline", _http())
    assert driver.has_server("outline")
    assert driver.list_servers()["outline"]["url"] == "https://x/mcp"


def test_list_empty_when_file_missing(driver):
    assert driver.list_servers() == {}


def test_add_preserves_unrelated_top_level_keys_and_existing_servers(driver):
    cp = driver.config_path
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({
        "userID": "u123",
        "numStartups": 5,
        "hasCompletedOnboarding": True,
        "mcpServers": {"existing": {"type": "http", "url": "https://old"}},
    }))
    driver.add_server("outline", _http())
    data = json.loads(cp.read_text())
    # Unrelated top-level keys untouched.
    assert data["userID"] == "u123"
    assert data["numStartups"] == 5
    assert data["hasCompletedOnboarding"] is True
    # Pre-existing server preserved, new one added.
    assert "existing" in data["mcpServers"]
    assert data["mcpServers"]["outline"]["url"] == "https://x/mcp"


def test_remove(driver):
    driver.add_server("outline", _http())
    assert driver.remove_server("outline") is True
    assert not driver.has_server("outline")
    assert driver.remove_server("outline") is False  # idempotent


def test_remove_preserves_other_keys(driver):
    cp = driver.config_path
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({
        "userID": "u",
        "mcpServers": {"outline": {"type": "http", "url": "https://x"}},
    }))
    driver.remove_server("outline")
    data = json.loads(cp.read_text())
    assert data["userID"] == "u"
    assert data["mcpServers"] == {}


def test_driver_name(driver):
    assert driver.name == "claude-code"
