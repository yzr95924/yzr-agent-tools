"""Tests for html_mcp.server — routing, method whitelist, body limit, threading."""
import http.client
import json
import threading
import time

import pytest

from html_mcp.server import (
    BodyTooLarge,
    Handler,
    make_server,
    register,
    routes,
)


@pytest.fixture
def http_server():
    """Spin up a ThreadingHTTPServer on an ephemeral port.

    Wipes the global ``routes`` registry first so tests don't leak. The
    server runs in a daemon thread; ``http_server.shutdown()`` (called
    automatically at teardown via the harness) ends ``serve_forever``.
    """
    routes.clear()
    srv = make_server("127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


def _base_url(srv):
    host, port = srv.server_address
    return host, port


def _get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", path, headers=headers or {})
        return conn.getresponse()
    finally:
        conn.close()


def _post(host, port, path, body=b"", headers=None):
    hdrs = {"Content-Length": str(len(body))}
    if headers:
        hdrs.update(headers)
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("POST", path, body=body, headers=hdrs)
        return conn.getresponse()
    finally:
        conn.close()


def _delete(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("DELETE", path, headers=headers or {})
        return conn.getresponse()
    finally:
        conn.close()


# --- routing -----------------------------------------------------------------

def test_matched_route_returns_200(http_server):
    register("GET", r"^/test$", lambda req, p, body: (200, b"ok", {"Content-Type": "text/plain"}))
    host, port = _base_url(http_server)
    r = _get(host, port, "/test")
    assert r.status == 200
    assert r.read() == b"ok"


def test_unmatched_path_returns_404(http_server):
    host, port = _base_url(http_server)
    r = _get(host, port, "/nope")
    assert r.status == 404


def test_wrong_method_on_matched_path_returns_405_with_allow(http_server):
    register("GET", r"^/only-get$", lambda req, p, body: (200, b"", {}))
    host, port = _base_url(http_server)
    r = _post(host, port, "/only-get", body=b"x")
    assert r.status == 405
    allow = r.getheader("Allow")
    assert allow is not None and "GET" in allow


def test_routes_with_path_params(http_server):
    """Path groups in the regex land in the handler's params dict."""
    def handler(req, params, body):
        assert params["name"] == "design.html"
        return (200, ("got " + params["name"]).encode("utf-8"), {})

    register("GET", r"^/api/files/(?P<name>[^/]+)$", handler)
    host, port = _base_url(http_server)
    r = _get(host, port, "/api/files/design.html")
    assert r.status == 200
    assert r.read() == b"got design.html"


def test_first_matching_route_wins(http_server):
    register("GET", r"^/dup$", lambda req, p, body: (200, b"first", {}))
    register("GET", r"^/dup$", lambda req, p, body: (200, b"second", {}))
    host, port = _base_url(http_server)
    r = _get(host, port, "/dup")
    assert r.read() == b"first"


# --- body / size limit -------------------------------------------------------

def test_post_body_is_passed_to_handler(http_server):
    seen = {}
    def handler(req, params, body):
        # Body is delivered via the dispatcher's third arg.
        return (200, body, {})

    register("POST", r"^/echo$", handler)
    host, port = _base_url(http_server)
    r = _post(host, port, "/echo", body=b"hello")
    assert r.status == 200
    assert r.read() == b"hello"


def test_oversize_body_returns_413(http_server):
    register("POST", r"^/echo$", lambda req, p, body: (200, b"ok", {}))
    host, port = _base_url(http_server)
    # Bump max_body_size down so we can hit the cap cheaply.
    Handler.max_body_size = 100
    try:
        big = b"x" * 200
        r = _post(host, port, "/echo", body=big)
        assert r.status == 413
    finally:
        Handler.max_body_size = 50 * 1024 * 1024


def test_oversize_body_returns_413(http_server):
    register("POST", r"^/echo$", lambda req, p: (200, b"ok", {}))
    host, port = _base_url(http_server)
    # Bump max_body_size down so we can hit the cap cheaply.
    Handler.max_body_size = 100
    try:
        big = b"x" * 200
        r = _post(host, port, "/echo", body=big)
        assert r.status == 413
    finally:
        Handler.max_body_size = 50 * 1024 * 1024


# --- threading --------------------------------------------------------------

def test_concurrent_requests_handled(http_server):
    """ThreadingMixIn ensures requests don't block each other."""
    counter = {"n": 0}
    lock = threading.Lock()

    def handler(req, params, body):
        with lock:
            counter["n"] += 1
        time.sleep(0.05)  # force overlap
        return (200, b"ok", {})

    register("GET", r"^/slow$", handler)

    host, port = _base_url(http_server)

    results = []
    def fire():
        r = _get(host, port, "/slow")
        results.append(r.status)

    threads = [threading.Thread(target=fire) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(s == 200 for s in results), results
    assert counter["n"] == 5


# --- shutdown ----------------------------------------------------------------

def test_shutdown_ends_serve_forever(http_server):
    # http_server fixture calls shutdown in teardown; if serve_forever
    # were broken, the test would hang.
    host, port = _base_url(http_server)
    r = _get(host, port, "/anything")
    assert r.status == 404


def test_quiet_suppresses_log(capsys, http_server):
    register("GET", r"^/quiet$", lambda req, p, body: (200, b"", {}))
    host, port = _base_url(http_server)
    _get(host, port, "/quiet")
    captured = capsys.readouterr()
    # Quiet is True → no log lines on stderr.
    assert "GET /quiet" not in captured.err


# --- error handling ----------------------------------------------------------

def test_handler_exception_returns_500(capsys):
    def boom(req, params, body):
        raise RuntimeError("nope")

    routes.clear()
    register("GET", r"^/boom$", boom)
    srv = make_server("127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        host, port = srv.server_address
        r = _get(host, port, "/boom")
        assert r.status == 500
        err = capsys.readouterr().err
        assert "handler error" in err
    finally:
        srv.shutdown()
        srv.server_close()
        routes.clear()


# --- BodyTooLarge exception -------------------------------------------------

def test_body_too_large_carries_length_and_cap():
    e = BodyTooLarge(200, 100)
    assert e.length == 200
    assert e.cap == 100