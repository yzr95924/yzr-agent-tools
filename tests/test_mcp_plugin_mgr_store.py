"""Tests for the servers.toml store — round-trip + passthrough + validation."""
import pytest

from mcp_plugin_mgr.store import (
    InvalidTransport,
    MissingRequiredField,
    ServerEntry,
    ServerRegistry,
    StoreError,
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
    e.extra = {"custom_field": "keep-me"}
    reg.servers["s"] = e
    save_servers(p, reg)

    loaded = load_servers(p)
    assert loaded.extra_top == {"schema_version": 1}
    assert loaded.servers["s"].extra == {"custom_field": "keep-me"}


# ---- enabled flag -----------------------------------------------------------

def test_enabled_defaults_true():
    assert ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x").enabled is True


def test_enabled_defaults_true_when_key_missing_in_file(tmp_path):
    p = tmp_path / "servers.toml"
    p.write_text('[servers.s]\ntransport = "http"\nurl = "https://x"\n')
    assert load_servers(p).servers["s"].enabled is True


def test_enabled_true_is_not_written_to_file(tmp_path):
    # Byte-stability: entries that were never disabled keep their old shape.
    p = tmp_path / "servers.toml"
    reg = ServerRegistry()
    reg.servers["s"] = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    save_servers(p, reg)
    assert "enabled" not in p.read_text()


def test_enabled_false_roundtrips(tmp_path):
    p = tmp_path / "servers.toml"
    reg = ServerRegistry()
    e = ServerEntry(name="s", transport=TRANSPORT_HTTP, url="https://x")
    e.enabled = False
    reg.servers["s"] = e
    save_servers(p, reg)

    assert "enabled = false" in p.read_text()
    assert load_servers(p).servers["s"].enabled is False


def test_enabled_true_in_file_reads_true(tmp_path):
    p = tmp_path / "servers.toml"
    p.write_text('[servers.s]\ntransport = "http"\nenabled = true\nurl = "https://x"\n')
    assert load_servers(p).servers["s"].enabled is True


def test_non_boolean_enabled_rejected(tmp_path):
    # A string like "false" is truthy in Python — fail fast instead of
    # silently leaving the server enabled.
    p = tmp_path / "servers.toml"
    p.write_text('[servers.s]\ntransport = "http"\nenabled = "false"\nurl = "https://x"\n')
    with pytest.raises(StoreError) as err:
        load_servers(p)
    assert "must be a boolean" in str(err.value)


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
