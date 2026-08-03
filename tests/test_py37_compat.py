"""Regression guards for Python 3.7 compatibility.

Background: ``typing.Protocol`` is Python 3.8+ (PEP 544). Both tools' driver
base modules import it under a try/except fallback shim so they load on 3.7
(see ``model_switch/drivers/base.py`` and ``mcp_plugin_mgr/drivers/base.py``).

Two layers of cover, on purpose:

1. A structural (AST) guard. It verifies the ``from typing import Protocol``
   line is actually nested inside a ``try`` — i.e. the shim is intact. This
   runs on *every* Python in the CI matrix, so a revert to a bare unguarded
   ``from typing import Protocol`` is caught by ALL jobs, not only the 3.7 one.

2. A runtime import smoke test. On the 3.7 CI job this fails at import if the
   shim ever stops working; on 3.8+ it confirms the public surface is intact.
"""
import ast
import importlib
from pathlib import Path


def _unguarded_protocol_imports(path):
    """AST-walk ``path``; return any ``from typing import Protocol`` whose
    enclosing context is NOT a ``try`` block (i.e. would crash on 3.7)."""
    tree = ast.parse(Path(path).read_text())
    found = []

    def visit(node, in_try):
        is_import = (
            isinstance(node, ast.ImportFrom)
            and node.module == "typing"
            and any(alias.name == "Protocol" for alias in node.names)
        )
        if is_import and not in_try:
            found.append(node.lineno)
        child_in_try = in_try or isinstance(node, ast.Try)
        for child in ast.iter_child_nodes(node):
            visit(child, child_in_try)

    visit(tree, in_try=False)
    return found


def test_model_switch_protocol_import_is_guarded_for_py37():
    base = importlib.import_module("model_switch.drivers.base")
    assert _unguarded_protocol_imports(base.__file__) == []


def test_mcp_protocol_import_is_guarded_for_py37():
    base = importlib.import_module("mcp_plugin_mgr.drivers.base")
    assert _unguarded_protocol_imports(base.__file__) == []


def test_model_switch_drivers_base_imports():
    base = importlib.import_module("model_switch.drivers.base")
    # Protocol resolves to the real typing.Protocol on 3.8+, or the shim on 3.7.
    assert base.Protocol is not None
    assert hasattr(base, "AgentDriver")
    assert hasattr(base, "registry")


def test_mcp_drivers_base_imports():
    base = importlib.import_module("mcp_plugin_mgr.drivers.base")
    assert base.Protocol is not None
    assert hasattr(base, "McpDriver")
    assert hasattr(base, "registry")
