"""agent-html-drop preset — Streamable HTTP MCP.

``agent-html-drop`` is a self-hosted daemon that lets the local agent push
self-contained HTML (e.g. ``yzr-md-to-html`` output) to a remote nginx server
and exposes 6 MCP tools (``upload_html`` / ``list_html`` / ``delete_html`` /
``get_public_url`` / ``list_annotations`` / ``delete_annotation``). The MCP
endpoint is ``POST /mcp`` behind an HTTPS reverse proxy, authed with a static
Bearer token the operator generates on the server.

The origin (and thus the ``/mcp`` URL) plus the token are per-deployment, so
this preset only knows how to shape the auth header
(``Authorization: Bearer <token>``); the user supplies ``--url`` and
``--token``.

``allow_tools`` enumerates the verified 6-tool set: ``upload_html`` writes
potentially large HTML (default ceiling 50 MB), exactly the kind of large
write Claude Code's auto-mode classifier false-positive BLOCKs — pre-approving
the tool names via ``--auto-allow`` makes the classifier skip that second guess.

``_diagnose`` is the agent-html-drop-specific overlay the ``test`` command
applies on top of the generic (transport-driven) probe result — same protocol
handshake, but daemon-flavored root causes / fixes (token rotation, daemon
liveness, nginx forwarding /mcp).
"""
from mcp_plugin_mgr.presets._types import Preset
from mcp_plugin_mgr.store import TRANSPORT_HTTP


def _diagnose(result):
    """agent-html-drop-specific root-cause refinement on the generic ProbeResult."""
    c = result.code
    if c == "auth":
        result.remediation = (
            "agent-html-drop: token 错了/过期/被撤销或没传 → server 上重新取:"
            " 经典部署 `agent-html-drop token show`;容器部署 "
            "`docker compose exec agent-html-drop agent-html-drop token show`。"
            "若 rotate 过 token,需重启 daemon 才生效"
        )
    elif c == "middlebox_https_works":
        result.detail = (result.detail or "") + (
            "\n[agent-html-drop] 反代/内网穿透的典型症状:HTTP 端口返占位 200,"
            "真 MCP 只在 HTTPS 443(agent-html-drop 默认就在 nginx HTTPS 反代后)"
        )
    elif c == "middlebox_empty":
        result.remediation = (
            "agent-html-drop: 已是 https 仍空响应 → 确认 nginx 反代把 /mcp "
            "转发到上游 :8765,且 daemon 在跑(`docker compose ps` / "
            "`agent-html-drop serve`)"
        )
    elif c == "conn":
        result.detail = (result.detail or "") + (
            "\n[agent-html-drop] 最常见于 daemon 没起(`docker compose ps` 看"
            "状态;`agent-html-drop serve` 起前台)或 nginx 反代没把 /mcp 转发到上游 :8765"
        )
    elif c in ("notfound", "not_mcp", "method"):
        result.remediation = (
            "agent-html-drop: 确认 endpoint 形如 https://<origin>/mcp"
            "(MCP 路径固定为 /mcp,POST 方法)"
        )
    elif c == "ok":
        result.detail = (result.detail or "") + (
            "\n[agent-html-drop] 握手 OK。upload_html 会写大 HTML(默认上限 50MB),"
            "若被 auto-mode 误拦,用 `mcp-plugin-mgr add agent-html-drop --auto-allow` 预批工具"
        )
    return result


PRESET = Preset(
    name="agent-html-drop",
    transport=TRANSPORT_HTTP,
    description="agent-html-drop — self-hosted HTML drop (Streamable HTTP MCP). "
    "Needs --url (HTTPS origin incl. /mcp) and --token (server-side Bearer token).",
    needs_url=True,
    headers_template={"Authorization": "Bearer {token}"},
    needs_token=True,
    diagnose=_diagnose,
    allow_tools=[
        "mcp__agent-html-drop__upload_html",
        "mcp__agent-html-drop__list_html",
        "mcp__agent-html-drop__delete_html",
        "mcp__agent-html-drop__get_public_url",
        "mcp__agent-html-drop__list_annotations",
        "mcp__agent-html-drop__delete_annotation",
    ],
)
