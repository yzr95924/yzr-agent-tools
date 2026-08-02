"""Memos (usememos.com) preset — Streamable HTTP MCP.

Same shape as Outline: per-deployment instance URL (incl. ``/mcp``) + a personal
access token from Memos settings. ``allow_tools`` is empty, so ``--auto-allow``
falls back to the server-level wildcard ``mcp__memos``.

``_diagnose`` is the Memos-specific overlay for the ``test`` command — same
generic handshake, but Memos-flavored root causes (Access Tokens, v0.27+ MCP,
/mcp path).
"""
from mcp_plugin_mgr.presets._types import Preset
from mcp_plugin_mgr.store import TRANSPORT_HTTP


def _diagnose(result):
    """Memos-specific root-cause refinement on the generic ProbeResult."""
    c = result.code
    if c == "auth":
        result.remediation = "Memos: personal access token 过期/失效或没传 → 设置 → Access Tokens 重新生成"
    elif c == "middlebox_https_works":
        result.detail = (result.detail or "") + (
            "\n[memos] 反代/内网穿透的典型症状:HTTP 端口返占位 200,真 MCP 只在 HTTPS 443"
        )
    elif c == "middlebox_empty":
        result.remediation = (
            "Memos: 反代需在 HTTPS 443 把 /mcp 转发到上游;确认实例版本 ≥ v0.27.0(MCP 内置)"
        )
    elif c == "conn":
        result.detail = (result.detail or "") + "\n[memos] 确认实例可达,反代/ddnsto 在 HTTPS 443 转发 /mcp"
    elif c in ("notfound", "not_mcp", "method"):
        result.remediation = (
            "Memos: 确认 endpoint 含 /mcp;MCP 自 v0.27.0 起内置(v0.30 重写为 stateless),确认版本与路径"
        )
    elif c == "ok":
        result.detail = (result.detail or "") + "\n[memos] 握手 OK"
    return result


PRESET = Preset(
    name="memos",
    transport=TRANSPORT_HTTP,
    description="Memos (usememos.com) — Streamable HTTP MCP. Needs --url "
    "(instance URL incl. /mcp) and --token (personal access token).",
    needs_url=True,
    headers_template={"Authorization": "Bearer {token}"},
    needs_token=True,
    diagnose=_diagnose,
)
