"""Built-in MCP presets.

Each plugin lives in its OWN module (outline.py, memos.py, ...) and contributes
one ``Preset``. This package aggregates them into ``PRESETS`` (keyed by
``preset.name``) and re-exports the public surface used by cli / tests:

    from mcp_plugin_mgr.presets import PRESETS, Preset, PresetError, get_preset

Add a preset = add a module under this package + one import line below.
"""
from mcp_plugin_mgr.presets._types import Preset, PresetError
from mcp_plugin_mgr.presets.memos import PRESET as _MEMOS
from mcp_plugin_mgr.presets.outline import PRESET as _OUTLINE

# Keyed by preset.name so the dict key and the name can't drift apart.
PRESETS = {p.name: p for p in (_OUTLINE, _MEMOS)}


def get_preset(name):
    return PRESETS.get(name)


__all__ = ["PRESETS", "Preset", "PresetError", "get_preset"]
