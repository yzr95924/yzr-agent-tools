"""Tests for annotation auth + list_files annotation_count extension."""
import http.client
import json
import threading
from pathlib import Path

import pytest

from html_mcp.api import register_routes
from html_mcp.config import Config
from html_mcp.server import make_server, routes


@pytest.fixture
def cfg_factory(tmp_path, monkeypatch):
    """Factory that builds a Config with tmp paths; monkeypatches config.load_config."""
    from html_mcp import config as cfg_mod
    from html_mcp import _legacy_storage as storage

    def _make(docroot_files=None, token="test-token-abc"):
        docroot = tmp_path / "docroot"
        docroot.mkdir(exist_ok=True)
        if docroot_files:
            for name, content in docroot_files:
                if isinstance(content, str):
                    storage.upload(
                        docroot, name, content, max_size=10_000_000, force=True
                    )
                else:
                    (docroot / name).write_bytes(content)
        cfg = Config(
            host="127.0.0.1",
            port=0,
            docroot=str(docroot),
            public_base_url="https://notes.example.com",
            max_file_size=50 * 1024 * 1024,
            token=token,
            extra_top={},
            extra_auth={},
        )
        monkeypatch.setattr(cfg_mod, "load_config", lambda *args: cfg)
        return cfg

    return _make


@pytest.fixture
def http_server(cfg_factory):
    routes.clear()
    cfg = cfg_factory(docroot_files=[("design.html", "<h1>Design</h1>")])
    srv = make_server("127.0.0.1", 0, quiet=True)
    register_routes(cfg)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
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
    conn = http.client.HTTPConnection(host, port, timeout=2)
    conn.request("POST", path, body=body, headers=hdrs)
    return conn, conn.getresponse()


def _get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    conn.request("GET", path, headers=headers or {})
    return conn, conn.getresponse()


def test_auth_correct_token_sets_cookie(http_server):
    srv, cfg = http_server
    host, port = srv.server_address
    conn, response = _post(
        host,
        port,
        "/api/auth",
        headers={"Authorization": "Bearer " + cfg.token},
    )
    try:
        assert response.status == 204
        set_cookie = response.getheader("Set-Cookie")
        assert set_cookie is not None
        assert "anno_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=Lax" in set_cookie
        assert "Max-Age=1800" in set_cookie
    finally:
        response.read()
        conn.close()


def test_auth_wrong_token_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _post(
        host, port, "/api/auth", headers={"Authorization": "Bearer WRONG"}
    )
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()


def test_auth_missing_header_returns_401(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _post(host, port, "/api/auth")
    try:
        assert response.status == 401
    finally:
        response.read()
        conn.close()


def test_list_files_includes_annotation_count_zero(http_server):
    srv, _ = http_server
    host, port = srv.server_address
    conn, response = _get(host, port, "/api/files")
    try:
        assert response.status == 200
        data = json.loads(response.read())
        assert data["files"][0]["annotation_count"] == 0
    finally:
        conn.close()


def test_list_files_includes_annotation_count_nonzero(http_server):
    """Mutate docroot after server start, then re-fetch /api/files."""
    from html_mcp.storage import annotations as anno_store

    srv, cfg = http_server
    anno_store.add(
        Path(cfg.docroot), "design.html", "quote", "comment", "any-token"
    )
    host, port = srv.server_address
    conn, response = _get(host, port, "/api/files")
    try:
        data = json.loads(response.read())
        assert data["files"][0]["annotation_count"] == 1
    finally:
        conn.close()
