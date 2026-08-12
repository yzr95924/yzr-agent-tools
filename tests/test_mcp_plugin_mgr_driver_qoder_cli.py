"""Tests for the Qoder CLI MCP driver (~/.qoder/settings.json mcpServers).

Shape facts verified against qodercli 1.0.43 by running
``qodercli --config-dir <tmp> mcp add ... --scope user`` and inspecting the
resulting settings.json: stdio carries NO ``type`` and omits empty ``env``,
http carries ``type: http``.
"""
import json

import pytest

from mcp_plugin_mgr.drivers.qoder_cli import QoderCliMcpDriver
from mcp_plugin_mgr.store import ServerEntry, TRANSPORT_HTTP, TRANSPORT_STDIO


@pytest.fixture
def driver(tmp_path):
    return QoderCliMcpDriver(config_path=tmp_path / ".qoder" / "settings.json")


def _http():
    return ServerEntry(
        name="outline",
        transport=TRANSPORT_HTTP,
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
    )


# --- render (vocabulary translation) ----------------------------------------

def test_render_http_uses_url_plus_type_with_headers(driver):
    assert driver.render(_http()) == {
        "url": "https://x/mcp",
        "type": "http",
        "headers": {"Authorization": "Bearer t"},
    }


def test_render_http_without_headers_omits_key(driver):
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    assert driver.render(e) == {"url": "https://x", "type": "http"}


def test_render_stdio_has_no_type_and_emits_env(driver):
    e = ServerEntry(
        name="g", transport=TRANSPORT_STDIO, command="uvx",
        args=["--from", "X", "run"], env={"K": "V"},
    )
    out = driver.render(e)
    assert out == {
        "command": "uvx",
        "args": ["--from", "X", "run"],
        "env": {"K": "V"},
    }
    # qodercli mcp add writes NO type field for stdio (unlike Claude Code).
    assert "type" not in out


def test_render_stdio_without_env_omits_env_and_type(driver):
    e = ServerEntry(name="g", transport=TRANSPORT_STDIO, command="uvx", args=["X"])
    out = driver.render(e)
    assert out == {"command": "uvx", "args": ["X"]}
    assert "env" not in out
    assert "type" not in out


# --- add / remove + preservation --------------------------------------------

def test_add_preserves_model_ui_permissions_and_existing_servers(driver):
    cp = driver.config_path
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({
        "model": {"name": "q35model_preview"},
        "ui": {"theme": "Tokyo Night"},
        "permissions": {"trustDirectories": ["/work"]},
        "git": {"installHooks": False},
        "mcpServers": {"existing": {"command": "old", "args": ["-x"]}},
    }))
    driver.add_server("outline", _http())
    data = json.loads(cp.read_text())
    # qodercli's own settings keys are untouched.
    assert data["model"] == {"name": "q35model_preview"}
    assert data["ui"] == {"theme": "Tokyo Night"}
    assert data["permissions"] == {"trustDirectories": ["/work"]}
    assert data["git"] == {"installHooks": False}
    assert "existing" in data["mcpServers"]
    assert data["mcpServers"]["outline"] == {
        "url": "https://x/mcp", "type": "http",
        "headers": {"Authorization": "Bearer t"},
    }


def test_remove_is_idempotent(driver):
    driver.add_server("outline", _http())
    assert driver.remove_server("outline") is True
    assert driver.remove_server("outline") is False


def test_driver_name(driver):
    assert driver.name == "qodercli"
