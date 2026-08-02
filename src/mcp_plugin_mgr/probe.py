"""MCP connectivity diagnostics for the `test` command.

Performs a real MCP ``initialize`` handshake against a server and classifies
the outcome — going beyond "did the config file write" to "does the endpoint
actually speak MCP". Designed to catch the specific failure modes that bite in
practice, notably the 内网穿透/反代盒 (e.g. ``*.ddnsto.com``) trap where the
HTTP port returns a placeholder ``200`` + empty body for every path and the
real MCP only reaches upstream over HTTPS 443.

Two transports:
  - ``probe_http``: POST a JSON-RPC ``initialize`` to a Streamable HTTP URL,
    classify the HTTP status / body (incl. auto-retry of an HTTPS variant when
    the empty-200 middlebox signature shows up).
  - ``probe_stdio``: spawn the command, send ``initialize`` over stdin, read
    the JSON-RPC reply (``communicate`` with timeout — no deadlock).

Both take injectable ``poster`` / ``spawner`` callables so tests drive the full
classification matrix offline. stdlib only (urllib + subprocess).
"""
import json
import socket
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit, urlunsplit


# MCP protocol version we advertise. Servers negotiate; an older server may
# answer with its own version or an error — either way a JSON-RPC reply proves
# the endpoint speaks MCP, which is what `test` cares about.
_PROTOCOL_VERSION = "2025-06-18"
_CLIENT_INFO = {"name": "mcp-plugin-mgr", "version": "1.0"}


class _ConnError(Exception):
    """Wraps any network-level failure (DNS / refused / timeout / TLS)."""


@dataclass
class ProbeResult:
    """Outcome of one probe. `code` is a stable machine label for assertions."""
    ok: bool
    code: str
    summary: str
    detail: str = ""
    remediation: str = ""
    server_info: str = ""


def _initialize_payload() -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": _CLIENT_INFO,
        },
    }


def _try_json(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None


def _snippet(body) -> str:
    if not body:
        return ""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    body = body.strip()
    if len(body) > 200:
        body = body[:200] + "…"
    return body


def _parse_mcp_message(body, ctype: str) -> Optional[dict]:
    """Extract a JSON-RPC message from an HTTP response body.

    Streamable HTTP may answer with ``application/json`` (one message) or
    ``text/event-stream`` (SSE; the message is in a ``data:`` line).
    """
    if isinstance(body, (bytes, bytearray)):
        text = body.decode("utf-8", "replace")
    else:
        text = body
    low = ctype.lower()
    if "event-stream" in low:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload:
                    msg = _try_json(payload)
                    if isinstance(msg, dict):
                        return msg
        return None
    msg = _try_json(text)
    return msg if isinstance(msg, dict) else None


def _classify_message(msg: dict) -> ProbeResult:
    """Classify a parsed JSON-RPC dict (shared by http 200 and stdio paths)."""
    if msg.get("jsonrpc") != "2.0":
        return ProbeResult(
            ok=False, code="not_mcp",
            summary="response is JSON but not JSON-RPC 2.0",
        )
    if "error" in msg:
        err = msg.get("error") or {}
        message = err.get("message", "") if isinstance(err, dict) else str(err)
        return ProbeResult(
            ok=False, code="mcp_error",
            summary="MCP endpoint replied with an error",
            detail=message,
            remediation="endpoint speaks MCP but rejected initialize; "
                        "check protocol version / required params in the error",
        )
    if "result" in msg:
        res = msg.get("result") or {}
        si = res.get("serverInfo") or {}
        info = "{} {}".format(si.get("name", "?"), si.get("version", "")).strip()
        pv = res.get("protocolVersion", "?")
        return ProbeResult(
            ok=True, code="ok",
            summary="MCP server responded to initialize",
            server_info=info or "(no serverInfo)",
            detail="protocolVersion: {}".format(pv),
        )
    return ProbeResult(
        ok=False, code="not_mcp",
        summary="JSON-RPC message has neither result nor error",
    )


# --- HTTP --------------------------------------------------------------------

# A poster returns (status, content_type, body_bytes) on success or raises
# _ConnError on any network failure. Injectable for tests.
Poster = Callable[[str, Dict[str, str], Dict[str, Any], int], Tuple[int, str, bytes]]


def _default_http_poster(url, headers, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.headers.get("Content-Type", ""), resp.read()
    except urlerror.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()
    except urlerror.URLError as e:
        raise _ConnError(str(e.reason))
    except socket.timeout:
        raise _ConnError("timeout after {}s".format(timeout))


def _https_variant(url: str) -> Optional[str]:
    """The https:// equivalent of an http:// URL, or None if already https."""
    parts = urlsplit(url)
    if parts.scheme == "https":
        return None
    if parts.scheme != "http":
        return None
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))


_MIDDLEBOX_EXPLANATION = (
    "HTTP 200 但响应体为空 —— 典型是内网穿透 / 反代盒(如 *.ddnsto.com)的 HTTP "
    "端口对所有路径都返占位 200 + Content-Length: 0;真正的 MCP 通常只在 HTTPS 443 "
    "才透到上游。这与鉴权对不对、客户端主机是否被「标记」无关。"
)


def _classify_http_200(ctype: str, body) -> ProbeResult:
    """Classify a 200 response body. The empty-body branch is the ddnsto signal."""
    if isinstance(body, (bytes, bytearray)):
        text = body.decode("utf-8", "replace")
    else:
        text = body
    if not text.strip():
        return ProbeResult(
            ok=False, code="middlebox_empty",
            summary="HTTP 200 with empty body (middlebox signature)",
        )
    msg = _parse_mcp_message(body, ctype)
    if msg is None:
        return ProbeResult(
            ok=False, code="not_mcp",
            summary="HTTP 200 but body is not JSON-RPC",
            detail=_snippet(body),
            remediation="endpoint 返回了非 JSON-RPC 内容(可能是普通网页 / 路径错);"
                        "确认 URL 以 /mcp 结尾且指向真正的 MCP 端点",
        )
    return _classify_message(msg)


def probe_http(url, headers, timeout=10, poster=_default_http_poster):
    # type: (str, Dict[str,str], int, Poster) -> ProbeResult
    try:
        status, ctype, body = poster(url, headers, _initialize_payload(), timeout)
    except _ConnError as e:
        return ProbeResult(
            ok=False, code="conn",
            summary="无法连接端点: {}".format(e),
            remediation="检查 URL / DNS / 网络;若是内网穿透,确认 HTTPS 443 已开放",
        )

    if status == 200:
        r = _classify_http_200(ctype, body)
        if r.code == "middlebox_empty":
            return _try_https_variant(url, headers, timeout, poster)
        return r

    if status in (401, 403):
        return ProbeResult(
            ok=False, code="auth",
            summary="HTTP {} (认证被拒)".format(status),
            remediation="token 错了 / 过期 / 被撤销,或没传;Outline 在 Settings→API "
                        "重新生成,Memos 在 设置→Access Tokens 生成",
        )
    if status == 404:
        return ProbeResult(
            ok=False, code="notfound",
            summary="HTTP 404",
            remediation="路径不对,确认 endpoint 以 /mcp 结尾",
        )
    if status == 405:
        return ProbeResult(
            ok=False, code="method",
            summary="HTTP 405 Method Not Allowed",
            remediation="端点可能不支持 POST / Streamable HTTP(老版 MCP 只支持 SSE GET)",
        )
    return ProbeResult(
        ok=False, code="http_{}".format(status),
        summary="HTTP {}".format(status),
        detail=_snippet(body),
    )


def _try_https_variant(url, headers, timeout, poster):
    # type: (...) -> ProbeResult
    https_url = _https_variant(url)
    if https_url is None:
        # Already https but empty 200 — different root cause.
        return ProbeResult(
            ok=False, code="middlebox_empty",
            summary="已是 HTTPS 但响应体为空",
            detail=_MIDDLEBOX_EXPLANATION,
            remediation="上游可能没启用 MCP 或路径不对——Outline 在 Settings→AI 开启 "
                        "MCP;确认路径 /mcp;自托管检查反代是否转发了 /mcp 到上游",
        )
    try:
        s2, c2, b2 = poster(https_url, headers, _initialize_payload(), timeout)
    except _ConnError as e:
        return ProbeResult(
            ok=False, code="middlebox_empty",
            summary="HTTP 200 空响应(疑似 middlebox);HTTPS 变体也连不上",
            detail=_MIDDLEBOX_EXPLANATION + "\nHTTPS 变体 {} 连接失败: {}".format(https_url, e),
            remediation="确认 HTTPS 443 对该 host 开放(ddnsto 需在控制台标记主机)",
        )
    if s2 == 200:
        r2 = _classify_http_200(c2, b2)
        if r2.ok:
            return ProbeResult(
                ok=False, code="middlebox_https_works",
                summary="HTTP 200 空响应(疑似 middlebox),但 HTTPS 变体正常!",
                detail=_MIDDLEBOX_EXPLANATION
                       + "\nHTTPS 变体探测成功: " + r2.summary,
                remediation="把 endpoint 改成 {}".format(https_url),
                server_info=r2.server_info,
            )
        https_summary = r2.summary
    else:
        https_summary = "HTTP {}".format(s2)
    return ProbeResult(
        ok=False, code="middlebox_empty",
        summary="HTTP 200 空响应(疑似 middlebox);HTTPS 变体也未通",
        detail=_MIDDLEBOX_EXPLANATION
               + "\nHTTPS 变体 {} 结果: {}".format(https_url, https_summary),
        remediation="检查内网穿透 / 反代是否在 HTTPS 443 正确转发到上游 /mcp",
    )


# --- stdio -------------------------------------------------------------------

# A spawner returns an object with a .communicate(input=, timeout=) like
# subprocess.Popen. Injectable for tests.
Spawner = Callable[[List[str], Dict[str, str]], Any]


def _default_spawner(command_args, env):
    return subprocess.Popen(
        command_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def probe_stdio(command_args, env, timeout=15, spawner=_default_spawner):
    # type: (List[str], Dict[str,str], int, Spawner) -> ProbeResult
    try:
        proc = spawner(command_args, env)
    except FileNotFoundError:
        return ProbeResult(
            ok=False, code="no_command",
            summary="可执行文件不存在: {}".format(command_args[0]),
            remediation="确认 command / PATH,或该 MCP server 是否已安装",
        )
    except OSError as e:
        return ProbeResult(
            ok=False, code="spawn_error",
            summary="启动失败: {}".format(e),
        )

    payload = (json.dumps(_initialize_payload()) + "\n").encode("utf-8")
    try:
        out, err = proc.communicate(input=payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate()
        except Exception:
            pass
        return ProbeResult(
            ok=False, code="no_response",
            summary="{}s 内未返回响应".format(timeout),
            remediation="进程起来了但不回 initialize;查该 MCP server 的日志 / stderr",
        )

    for line in out.decode("utf-8", "replace").splitlines():
        msg = _try_json(line.strip())
        if isinstance(msg, dict):
            return _classify_message(msg)
    return ProbeResult(
        ok=False, code="not_mcp",
        summary="进程启动但未返回 JSON-RPC",
        detail="stderr: " + _snippet(err) if err else "",
        remediation="确认 command + args 正确,且该进程是 MCP stdio server",
    )
