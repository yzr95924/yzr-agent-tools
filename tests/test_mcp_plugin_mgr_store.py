"""Tests for the servers.toml store — round-trip + passthrough + validation."""
import pytest

from mcp_plugin_mgr.store import (
    InvalidTransport,
    MissingRequiredField,
    ServerEntry,
    ServerRegistry,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    load_servers,
    save_servers,
)


def test_load_missing_file_returns_empty_registry(tmp_path):
    assert load_servers(tmp_path / "nope.toml").servers == {}


def test_save_load_roundtrip_http(tmp_path):
    p = tmp_path / "servers.toml"
    reg = ServerRegistry()
    reg.servers["outline"] = ServerEntry(
        name="outline",
        transport=TRANSPORT_HTTP,
        url="https://x/mcp",
        headers={"Authorization": "Bearer t"},
        description="Outline wiki",
    )
    save_servers(p, reg)

    e = load_servers(p).servers["outline"]
    assert e.transport == "http"
    assert e.url == "https://x/mcp"
    assert e.headers == {"Authorization": "Bearer t"}
    assert e.description == "Outline wiki"


def test_save_load_roundtrip_stdio(tmp_path):
    p = tmp_path / "servers.toml"
    reg = ServerRegistry()
    reg.servers["g"] = ServerEntry(
        name="g",
        transport=TRANSPORT_STDIO,
        command="uvx",
        args=["--from", "X", "run"],
        env={"K": "V"},
    )
    save_servers(p, reg)

    e = load_servers(p).servers["g"]
    assert e.command == "uvx"
    assert e.args == ["--from", "X", "run"]
    assert e.env == {"K": "V"}


def test_unknown_top_level_and_per_server_keys_roundtrip(tmp_path):
    p = tmp_path / "servers.toml"
    reg = ServerRegistry(extra_top={"schema_version": 1})
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    e.extra = {"custom_field": "keep-me", "enabled": True}
    reg.servers["s"] = e
    save_servers(p, reg)

    loaded = load_servers(p)
    assert loaded.extra_top == {"schema_version": 1}
    assert loaded.servers["s"].extra == {"custom_field": "keep-me", "enabled": True}


def test_invalid_transport_rejected(tmp_path):
    p = tmp_path / "servers.toml"
    p.write_text('[servers.x]\ntransport = "ftp"\nurl = "https://x"\n')
    with pytest.raises(InvalidTransport):
        load_servers(p)


def test_missing_transport_rejected(tmp_path):
    p = tmp_path / "servers.toml"
    p.write_text('[servers.x]\nurl = "https://x"\n')
    with pytest.raises(InvalidTransport):
        load_servers(p)


def test_http_entry_requires_url():
    with pytest.raises(MissingRequiredField):
        ServerEntry(name="x", transport=TRANSPORT_HTTP).validate()


def test_stdio_entry_requires_command():
    with pytest.raises(MissingRequiredField):
        ServerEntry(name="x", transport=TRANSPORT_STDIO).validate()


def test_detail_summary_http_and_stdio():
    assert (
        ServerEntry(name="o", transport=TRANSPORT_HTTP, url="https://x/mcp").detail()
        == "https://x/mcp"
    )
    assert (
        ServerEntry(
            name="g", transport=TRANSPORT_STDIO, command="uvx", args=["--from", "X"]
        ).detail()
        == "uvx --from X"
    )
