"""Outline wiki preset — Streamable HTTP MCP.

The deployment URL and the API token are per-installation, so this preset only
knows how to shape the auth header (``Authorization: Bearer <token>``); the user
supplies ``--url`` and ``--token``.

``allow_tools`` is the verified 15-tool set from yzr-outline-wiki-setup: the
auto-mode classifier is prone to false-positive blocking large writes (≥3000
chars) to these, and pre-approving them in ``permissions.allow`` (via
``--auto-allow``) makes the classifier skip that second guess.

``_diagnose`` is the Outline-specific overlay the ``test`` command applies on
top of the generic (transport-driven) probe result — same protocol handshake,
but Outline-flavored root causes / fixes.
"""
from mcp_plugin_mgr.presets._types import Preset
from mcp_plugin_mgr.store import TRANSPORT_HTTP


def _diagnose(result):
    """Outline-specific root-cause refinement on the generic ProbeResult."""
    c = result.code
    if c == "auth":
        result.remediation = "Outline: API key 过期/被撤销或没传 → Settings → API 重新生成"
    elif c == "middlebox_https_works":
        # Generic already says "改成 https://..."; add Outline context.
        result.detail = (result.detail or "") + (
            "\n[outline] *.ddnsto.com 等反代的典型症状:HTTP 端口对所有路径返占位 200,"
            "真正的 MCP 只在 HTTPS 443 才透到上游"
        )
    elif c == "middlebox_empty":
        result.remediation = (
            "Outline: 已是 https 仍空响应 → Settings → AI 确认 MCP toggle 已开启;"
            "自托管检查反代/ddnsto 在 HTTPS 443 把 /mcp 转发到上游"
        )
    elif c == "conn":
        result.detail = (result.detail or "") + (
            "\n[outline] 自托管最常见于反代/ddnsto 未把 HTTPS 443 转发到上游 /mcp"
        )
    elif c in ("notfound", "not_mcp"):
        result.remediation = "Outline: 确认 endpoint 形如 https://<host>/mcp,且工作区已启用 MCP"
    elif c == "ok":
        result.detail = (result.detail or "") + (
            "\n[outline] 握手 OK。之后写大文档(≥3000 字符)若被 auto-mode 误拦,"
            "用 `mcp-plugin-mgr add outline --auto-allow` 预批工具"
        )
    return result


PRESET = Preset(
    name="outline",
    transport=TRANSPORT_HTTP,
    description="Outline wiki — Streamable HTTP MCP. Needs per-deployment --url and --token.",
    needs_url=True,
    headers_template={"Authorization": "Bearer {token}"},
    needs_token=True,
    diagnose=_diagnose,
    allow_tools=[
        "mcp__outline__create_attachment",
        "mcp__outline__update_document",
        "mcp__outline__create_document",
        "mcp__outline__fetch",
        "mcp__outline__list_collections",
        "mcp__outline__list_documents",
        "mcp__outline__list_collection_documents",
        "mcp__outline__list_comments",
        "mcp__outline__create_comment",
        "mcp__outline__update_comment",
        "mcp__outline__delete_comment",
        "mcp__outline__move_document",
        "mcp__outline__delete_document",
        "mcp__outline__update_collection",
        "mcp__outline__delete_collection",
    ],
)
