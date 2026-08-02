"""Tests for probe.py + the `test` CLI command.

All offline: probe_http / probe_stdio take injectable poster / spawner so the
full classification matrix (ok / auth / 404 / middlebox-empty / https-variant /
conn-error / stdio no-command / timeout / not-mcp) runs with no real network or
subprocess. The CLI tests monkeypatch the probe functions.
"""
import subprocess

import pytest

from mcp_plugin_mgr import probe
from mcp_plugin_mgr.probe import ProbeResult, _ConnError
from mcp_plugin_mgr.presets import get_preset

from _mcp_cli_runner import invoke_cli as run


# --- fake poster / spawner ---------------------------------------------------

def _poster_by_scheme(http_resp, https_resp=None):
    """Return a poster that serves http_resp for http:// URLs and https_resp otherwise."""
    def poster(url, headers, payload, timeout):
        if url.startswith("http://") and https_resp is not None:
            return http_resp
        if url.startswith("https://") and https_resp is not None:
            return https_resp
        return http_resp
    return poster


def _poster_const(resp):
    def poster(url, headers, payload, timeout):
        return resp
    return poster


def _conn_poster():
    def poster(url, headers, payload, timeout):
        raise _ConnError("connection refused")
    return poster


_OK_BODY = (b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18",'
            b'"serverInfo":{"name":"outline","version":"1.2.3"}}}')
_ERR_BODY = b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"bad init"}}'
_SSE_BODY = (b'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18",'
             b'"serverInfo":{"name":"memos","version":"0.30"}}}\n\n')


class _FakeProc:
    def __init__(self, out=b"", err=b"", exc=None):
        self._out = out
        self._err = err
        self._exc = exc

    def kill(self):
        pass

    def communicate(self, input=None, timeout=None):
        if self._exc:
            raise self._exc
        return self._out, self._err


def _spawner(out=b"", err=b"", exc=None, raise_exc=None):
    def spawner(command_args, env):
        if raise_exc is not None:
            raise raise_exc
        return _FakeProc(out, err, exc)
    return spawner


# --- probe_http: success paths ----------------------------------------------

def test_http_ok_json():
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((200, "application/json", _OK_BODY)))
    assert r.ok and r.code == "ok"
    assert r.server_info == "outline 1.2.3"
    assert "2025-06-18" in r.detail


def test_http_ok_sse_event_stream():
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((200, "text/event-stream", _SSE_BODY)))
    assert r.ok and r.code == "ok"
    assert r.server_info == "memos 0.30"


def test_http_mcp_error_is_not_ok_but_endpoint_speaks_mcp():
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((200, "application/json", _ERR_BODY)))
    assert not r.ok and r.code == "mcp_error"
    assert "bad init" in r.detail


# --- probe_http: the ddnsto middlebox diagnosis ------------------------------

def test_http_middlebox_empty_then_https_works_suggests_fix():
    # http URL -> empty 200 (middlebox); https variant -> real init. This is the
    # *.ddnsto.com scenario from yzr-outline-wiki-setup's troubleshoot section.
    poster = _poster_by_scheme(
        http_resp=(200, "text/html", b""),
        https_resp=(200, "application/json", _OK_BODY),
    )
    r = probe.probe_http("http://myoutline.ddnsto.com/mcp", {}, poster=poster)
    assert not r.ok                       # the given http URL does not work
    assert r.code == "middlebox_https_works"
    assert "https://myoutline.ddnsto.com/mcp" in r.remediation


def test_http_middlebox_empty_https_also_empty():
    poster = _poster_by_scheme(
        http_resp=(200, "text/html", b""),
        https_resp=(200, "text/html", b""),
    )
    r = probe.probe_http("http://h/mcp", {}, poster=poster)
    assert not r.ok and r.code == "middlebox_empty"
    assert "HTTPS" in r.detail or "https" in r.detail.lower()


def test_http_middlebox_empty_already_https():
    # Already https but empty 200 -> different remediation (upstream MCP off / path).
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((200, "text/html", b"")))
    assert not r.ok and r.code == "middlebox_empty"
    assert "Settings" in r.remediation or "AI" in r.remediation


def test_http_middlebox_empty_https_conn_fails():
    def poster(url, headers, payload, timeout):
        if url.startswith("http://"):
            return (200, "text/html", b"")
        raise _ConnError("tls handshake failed")
    r = probe.probe_http("http://h/mcp", {}, poster=poster)
    assert not r.ok and r.code == "middlebox_empty"
    assert "连不上" in r.summary or "连接失败" in r.detail


# --- probe_http: other failures ---------------------------------------------

def test_http_not_mcp_html_body():
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((200, "text/html", b"<html>landing page</html>")))
    assert not r.ok and r.code == "not_mcp"


def test_http_auth_401():
    r = probe.probe_http("https://h/mcp", {}, poster=_poster_const((401, "application/json", b'{"error":"unauth"}')))
    assert not r.ok and r.code == "auth"


def test_http_404():
    r = probe.probe_http("https://h", {}, poster=_poster_const((404, "text/plain", b"nope")))
    assert not r.ok and r.code == "notfound"


def test_http_conn_error():
    r = probe.probe_http("https://dead.invalid/mcp", {}, poster=_conn_poster())
    assert not r.ok and r.code == "conn"


# --- probe_stdio -------------------------------------------------------------

def test_stdio_ok():
    r = probe.probe_stdio(["fake"], {}, spawner=_spawner(out=_OK_BODY))
    assert r.ok and r.code == "ok"
    assert r.server_info == "outline 1.2.3"


def test_stdio_command_not_found():
    r = probe.probe_stdio(["no-such-bin"], {}, spawner=_spawner(raise_exc=FileNotFoundError("no-such-bin")))
    assert not r.ok and r.code == "no_command"


def test_stdio_timeout():
    exc = subprocess.TimeoutExpired(cmd=["fake"], timeout=15)
    r = probe.probe_stdio(["fake"], {}, spawner=_spawner(exc=exc))
    assert not r.ok and r.code == "no_response"


def test_stdio_not_mcp():
    r = probe.probe_stdio(["fake"], {}, spawner=_spawner(out=b"hello world\n", err=b""))
    assert not r.ok and r.code == "not_mcp"


# --- CLI `test` command (monkeypatched probe, offline) -----------------------

def test_cli_test_url_ok_exit0(monkeypatch):
    def fake(url, headers, timeout=10, poster=None):
        return ProbeResult(ok=True, code="ok", summary="MCP server responded",
                           server_info="outline 1.2.3", detail="protocolVersion: 2025-06-18")
    monkeypatch.setattr(probe, "probe_http", fake)
    r = run(["test", "--url", "https://x/mcp"])
    assert r.exit_code == 0
    assert "✓" in r.stdout
    assert "outline 1.2.3" in r.stdout


def test_cli_test_url_middlebox_exit1_with_fix(monkeypatch):
    def fake(url, headers, timeout=10, poster=None):
        return ProbeResult(ok=False, code="middlebox_https_works",
                           summary="HTTP 200 空响应(疑似 middlebox),但 HTTPS 变体正常!",
                           remediation="把 endpoint 改成 https://x/mcp")
    monkeypatch.setattr(probe, "probe_http", fake)
    r = run(["test", "--url", "http://x/mcp"])
    assert r.exit_code == 1
    assert "✗" in r.stdout
    assert "https://x/mcp" in r.stdout


def test_cli_test_registered_name(monkeypatch):
    # Register a server, then test it by name (transport dispatched to probe_http).
    run(["add", "outline", "--url", "https://x/mcp", "--token", "tok", "--no-apply"])
    called = {}

    def fake(url, headers, timeout=10, poster=None):
        called["url"] = url
        called["headers"] = headers
        return ProbeResult(ok=True, code="ok", summary="ok", server_info="outline 1")

    monkeypatch.setattr(probe, "probe_http", fake)
    r = run(["test", "outline"])
    assert r.exit_code == 0
    assert called["url"] == "https://x/mcp"
    assert called["headers"] == {"Authorization": "Bearer tok"}


def test_cli_test_no_arg_errors():
    r = run(["test"])
    assert r.exit_code == 1
    assert "name" in r.stdout or "--url" in r.stdout


# --- per-plugin diagnose overlay --------------------------------------------
# The generic probe classifies by transport; each preset's diagnose() refines
# the root cause / remediation for that specific service.

def test_outline_diagnose_auth_points_at_settings_api():
    r = get_preset("outline").diagnose(ProbeResult(ok=False, code="auth", summary="x"))
    assert "Settings → API" in r.remediation


def test_outline_diagnose_ok_adds_auto_allow_hint():
    r = get_preset("outline").diagnose(ProbeResult(ok=True, code="ok", summary="x"))
    assert "auto-allow" in r.detail


def test_outline_diagnose_conn_adds_reverse_proxy_hint():
    r = get_preset("outline").diagnose(ProbeResult(ok=False, code="conn", summary="x"))
    assert "反代" in r.detail or "ddnsto" in r.detail


def test_memos_diagnose_auth_points_at_access_tokens():
    r = get_preset("memos").diagnose(ProbeResult(ok=False, code="auth", summary="x"))
    assert "Access Tokens" in r.remediation


def test_memos_diagnose_notfound_mentions_version_and_path():
    r = get_preset("memos").diagnose(ProbeResult(ok=False, code="notfound", summary="x"))
    assert "v0.27" in r.remediation
    assert "/mcp" in r.remediation


def test_cli_test_outline_applies_outline_overlay_not_memos(monkeypatch):
    run(["add", "outline", "--url", "https://x/mcp", "--token", "t", "--no-apply"])

    def fake(url, headers, timeout=10, poster=None):
        return ProbeResult(ok=False, code="auth", summary="HTTP 401 (auth rejected)")

    monkeypatch.setattr(probe, "probe_http", fake)
    r = run(["test", "outline"])
    assert r.exit_code == 1
    assert "Settings → API" in r.stdout          # outline-specific
    assert "Access Tokens" not in r.stdout        # not the memos overlay


def test_cli_test_url_adhoc_has_no_overlay(monkeypatch):
    # Ad-hoc --url: no preset -> generic remediation only, no plugin overlay.
    def fake(url, headers, timeout=10, poster=None):
        return ProbeResult(ok=False, code="auth", summary="x", remediation="GENERIC-TOKEN-HINT")

    monkeypatch.setattr(probe, "probe_http", fake)
    r = run(["test", "--url", "https://x/mcp"])
    assert "GENERIC-TOKEN-HINT" in r.stdout
    assert "Settings → API" not in r.stdout       # no outline overlay for ad-hoc
