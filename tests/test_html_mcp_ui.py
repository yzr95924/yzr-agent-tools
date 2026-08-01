"""Smoke tests for the management page UI assets + handler."""
import http.client
import os
import threading

import pytest

from html_mcp import server as srv
from html_mcp import ui as ui_mod


@pytest.fixture
def ui_server():
    srv.routes.clear()
    ui_mod.register_routes()
    http = srv.make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    try:
        yield http
    finally:
        http.shutdown()
        http.server_close()
        srv.routes.clear()


def _get(srv_, path):
    host, port = srv_.server_address
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", path, headers={})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


# --- assets exist on disk ---------------------------------------------------

def test_index_html_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "index.html"))


def test_style_css_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "style.css"))


def test_app_js_exists():
    assert os.path.isfile(os.path.join(ui_mod._UI_DIR, "app.js"))


# --- served correctly -------------------------------------------------------

def test_serves_index_html(ui_server):
    status, headers, body = _get(ui_server, "/")
    assert status == 200
    assert "text/html" in headers.get("Content-Type", "")
    assert b"html-mcp" in body
    assert b"<title>" in body


def test_serves_style_css(ui_server):
    status, headers, body = _get(ui_server, "/style.css")
    assert status == 200
    assert "text/css" in headers.get("Content-Type", "")
    assert b"--bg" in body  # CSS variable from style.css


def test_serves_app_js(ui_server):
    status, headers, body = _get(ui_server, "/app.js")
    assert status == 200
    assert "javascript" in headers.get("Content-Type", "")
    assert b"localStorage" in body
    assert b"Authorization" in body


# --- no auth required on / --------------------------------------------------

def test_index_no_auth_required(ui_server):
    """The page is static; auth happens at /api/*."""
    status, _, _ = _get(ui_server, "/")
    assert status == 200


# --- HTML contains expected structure ---------------------------------------

def test_index_has_token_input(ui_server):
    _, _, body = _get(ui_server, "/")
    text = body.decode("utf-8")
    assert 'id="token-input"' in text
    assert 'id="file-tbody"' in text
    assert 'sandbox=""' in text  # iframe sandbox attribute


def test_app_js_uses_localstorage_for_token(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert 'localStorage.setItem' in text
    assert 'localStorage.getItem' in text
    assert "Bearer " in text  # token format


def test_app_js_handles_401(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "r.status === 401" in text or "r.status == 401" in text


def test_app_js_uses_clipboard_for_copy(ui_server):
    _, _, body = _get(ui_server, "/app.js")
    text = body.decode("utf-8")
    assert "clipboard" in text