"""TOML parsing/dumping for model-switch's models.toml.

Loader prefers stdlib ``tomllib`` (3.11+), falls back to ``tomli`` on older
Python. The dumper is always hand-written (no stdlib write API) so unknown
fields round-trip without data loss.

Self-contained copy adapted from mcp-plugin-mgr's ``_compat.py`` (repo
convention: each tool keeps its own). One deliberate difference:
models.toml is a flat ``[[models]]`` array, and a ``[section]`` header would
escape the enclosing array item — so dict values render as INLINE tables
instead of sections.
"""
import io
from typing import Any, Dict


# TOML basic string escapes: backslash, double-quote, control chars.
_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_escape_str(s: str) -> str:
    out = []
    for ch in s:
        if ch in _BASIC_ESCAPES:
            out.append(_BASIC_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u{:04x}".format(ord(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _format_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"{}"'.format(_toml_escape_str(v))
    raise TypeError("Unsupported TOML scalar type: {}".format(type(v)))


def _dump_inline(v: Any) -> str:
    """Render one value inline: scalar, array, or (nested) inline table."""
    if isinstance(v, dict):
        return "{{{}}}".format(", ".join(
            "{} = {}".format(k, _dump_inline(x)) for k, x in v.items()))
    if isinstance(v, list):
        return "[{}]".format(", ".join(_dump_inline(x) for x in v))
    return _format_scalar(v)


def _dump_section(buf, data: Dict[str, Any]) -> None:
    """Dump a dict: scalar/inline values first, then [[arrays-of-tables]]."""
    arrays = []
    for k, v in data.items():
        if (isinstance(v, list) and v
                and all(isinstance(x, dict) for x in v)):
            arrays.append((k, v))
            continue
        buf.write("{} = {}\n".format(k, _dump_inline(v)))
    for k, items in arrays:
        for item in items:
            buf.write("\n[[{}]]\n".format(k))
            _dump_section(buf, item)


def toml_dumps(data: Dict[str, Any]) -> str:
    """Render `data` as TOML. Hand-written: stdlib tomllib and tomli have no
    write API, and unknown fields must round-trip."""
    buf = io.StringIO()
    _dump_section(buf, data)
    return buf.getvalue()


# Loader: prefer stdlib tomllib (3.11+), fall back to tomli.
try:
    from tomllib import loads as toml_loads
except ImportError:  # Python <3.11
    from tomli import loads as toml_loads  # type: ignore[no-redef]
