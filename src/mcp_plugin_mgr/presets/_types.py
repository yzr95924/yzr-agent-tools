"""Preset type + materialization logic, shared by every plugin module.

A preset is a partially-filled canonical ``ServerEntry`` template. Plugin
modules (outline.py, memos.py, ...) each define one ``Preset`` instance; the
package ``__init__`` aggregates them into ``PRESETS``. Keep this file free of
any specific plugin so plugins can import ``Preset`` without a cycle.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from mcp_plugin_mgr.store import (
    ServerEntry,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
)


class PresetError(Exception):
    """A preset could not be expanded with the given inputs."""


@dataclass
class Preset:
    """A canonical server template with optional holes the user must fill."""
    name: str
    transport: str
    description: str = ""
    # http
    url: Optional[str] = None        # if set, preset hardcodes the URL
    needs_url: bool = True           # else the user must pass --url
    headers_template: Dict[str, str] = field(default_factory=dict)
    needs_token: bool = False        # template references {token}; user must pass --token
    # stdio
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    # Claude Code permission rules to pre-approve via --auto-allow (avoids the
    # auto-mode classifier false-positive on large writes). Empty -> fall back
    # to the server-level wildcard mcp__<name> at allow time.
    allow_tools: List[str] = field(default_factory=list)
    # Optional per-plugin diagnostic overlay for the `test` command. Takes the
    # GENERIC ProbeResult returned by probe.py (classified by transport) and
    # returns a refined one with plugin-specific root cause / remediation
    # (e.g. outline points at Settings→AI; memos at Access Tokens / v0.27+).
    # None -> use the generic result as-is. Typed loosely (Any) so this module
    # need not import probe (avoids a cycle; probe doesn't import plugins).
    diagnose: Optional[Callable] = None

    def to_entry(
        self,
        *,
        url: Optional[str] = None,
        token: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        description: Optional[str] = None,
    ) -> ServerEntry:
        """Materialize the preset into a validated ServerEntry.

        `extra_headers` (from repeated --header flags) are layered on top of the
        preset's rendered headers and override matching keys.
        """
        e = ServerEntry(
            name=self.name,
            transport=self.transport,
            description=description or self.description,
        )
        if self.transport == TRANSPORT_HTTP:
            final_url = url or self.url
            if not final_url:
                raise PresetError(
                    "preset {!r} needs a URL — pass --url URL".format(self.name)
                )
            e.url = final_url
            headers: Dict[str, str] = {}
            if self.headers_template:
                if self.needs_token and not token:
                    raise PresetError(
                        "preset {!r} needs an API token — pass --token TOKEN".format(
                            self.name
                        )
                    )
                for k, v in self.headers_template.items():
                    headers[k] = v.format(token=token) if "{token}" in v else v
            if extra_headers:
                headers.update(extra_headers)
            e.headers = headers
        else:  # stdio
            e.command = self.command
            e.args = list(self.args)
            e.env = dict(self.env)
        e.validate()
        return e
