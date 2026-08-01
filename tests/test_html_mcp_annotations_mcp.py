"""Tests for MCP list_annotations + delete_annotation tools."""
import json
import threading

import pytest

from html_mcp.config import Config
from html_mcp.mcp_handler import register_route
from html_mcp.server import make_server, routes
from html_mcp.storage.annotations import add as anno_add


@pytest.fixture
def http_server(tmp_path):
    routes.clear()
    docroot = tmp_path / "docroot"
    docroot.mkdir()
    cfg = Config(
        host="127.0.0.1", port=0,
        docroot=str(docroot),
        public_base_url="https://notes.example.com",
        max_file_size=50 * 1024 * 1024,
        token="mcp-token",
        extra_top={}, extra_auth={},
    )
    register_route(cfg)
    srv = make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, cfg
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


def _post(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    import http.client
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def _rpc(host, port, token, method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode("utf-8")
    r = _post(host, port, "/mcp", body=body,
              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(r.read())


def test_tools_list_includes_annotation_tools(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/list")
    names = [t["name"] for t in data["result"]["tools"]]
    assert "list_annotations" in names
    assert "delete_annotation" in names


def test_list_annotations_returns_entries(http_server):
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    anno_add(docroot, "design.html", "q1", "c1", "t1")
    anno_add(docroot, "design.html", "q2", "c2", "t2")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "list_annotations", "arguments": {"name": "design.html"}})
    payload = json.loads(data["result"]["content"][0]["text"])
    assert payload["name"] == "design.html"
    assert len(payload["annotations"]) == 2


def test_delete_annotation_by_agent_succeeds(http_server):
    from pathlib import Path
    srv, cfg = http_server
    docroot = Path(cfg.docroot)
    entry = anno_add(docroot, "design.html", "q", "c", "browser-token")
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "design.html", "id": entry["id"]}})
    payload = json.loads(data["result"]["content"][0]["text"])
    assert payload["deleted"] is True
    assert anno_store_count(docroot, "design.html") == 0


def test_delete_annotation_not_found_returns_error(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/call",
                {"name": "delete_annotation",
                 "arguments": {"name": "design.html", "id": "NONEXISTENT"}})
    # Tool-level error (isError=True) with not_found code.
    assert data["result"]["isError"] is True
    assert "not_found" in data["result"]["content"][0]["text"]


def test_agent_no_add_annotation_tool(http_server):
    """N11: agent must NOT have a write-annotation tool."""
    srv, cfg = http_server
    host, port = srv.server_address
    data = _rpc(host, port, cfg.token, "tools/list")
    names = [t["name"] for t in data["result"]["tools"]]
    assert "add_annotation" not in names


def anno_store_count(docroot, name):
    from html_mcp.storage.annotations import count
    return count(docroot, name)
