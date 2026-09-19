"""TOML parsing/dumping. Prefers stdlib `tomllib` on 3.11+, falls back to
`tomli` on older Python. The dumper is always hand-written (no stdlib
write API) so that fields copied verbatim from `workspace_models.toml`
(e.g. `api_key`, `is_default`, `schema_version`) round-trip without
data loss.
"""
import io
import re
from typing import Any, Dict, Optional


# Bare TOML keys: A-Za-z0-9_-; anything else must be quoted.
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Inline tables must stay on one line; a subtree whose `key = value`
# rendering is longer than this falls back to `[header]` form.
_INLINE_MAX = 120


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
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _format_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # repr keeps the decimal point (`1.0`, not `1`) so the value stays a
        # TOML float on reload; inf/nan reprs are valid TOML literals too.
        return repr(v)
    if isinstance(v, str):
        return '"{}"'.format(_toml_escape_str(v))
    raise TypeError("Unsupported TOML scalar type: {}".format(type(v)))


def _dump_key(k: str) -> str:
    """A TOML key: bare when safe, otherwise a quoted basic string.

    Unquoted, a key containing `.` would silently add a table level.
    """
    if _BARE_KEY_RE.match(k):
        return k
    return '"{}"'.format(_toml_escape_str(k))


def _can_inline(v: Any) -> bool:
    """Scalars, arrays of scalars and tables of those fit on one line;
    arrays of tables never do."""
    if isinstance(v, dict):
        return all(_can_inline(x) for x in v.values())
    if isinstance(v, list):
        return all(not isinstance(x, dict) for x in v)
    return True


def _format_inline(v: Any) -> str:
    """Render one inline value (scalar, array, or nested inline table)."""
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{{ {} }}".format(
            ", ".join(
                "{} = {}".format(_dump_key(k), _format_inline(x))
                for k, x in v.items()
            )
        )
    if isinstance(v, list):
        return "[{}]".format(", ".join(_format_scalar(x) for x in v))
    return _format_scalar(v)


def _inline_form(k: str, v: Any) -> Optional[str]:
    """The one-line `key = value` rendering, or None when it must expand."""
    if not _can_inline(v):
        return None
    text = "{} = {}".format(_dump_key(k), _format_inline(v))
    if len(text) > _INLINE_MAX:
        return None
    return text


def _needs_scope(v: Dict[str, Any]) -> bool:
    """Whether a table must open a `[header]` line of its own.

    A table may drop its header only when it is a pure namespace: no scalars
    or table-arrays of its own and every child table expands. A child that
    renders inline has no scope of its own — its line would otherwise land
    in whatever table was opened last.
    """
    if not v:
        return True
    for k, x in v.items():
        if isinstance(x, dict):
            if _inline_form(k, x) is not None:
                return True
        else:
            return True
    return False


def _dump_section(buf, data: Dict[str, Any], prefix: str) -> None:
    """Dump a dict: scalars first, then [[arrays-of-tables]], then tables.

    Tables render inline (`key = { ... }`) when shallow enough, otherwise
    as `[header]` sections; a pure-namespace table drops its own header.

    Inline-able tables are emitted before `[[array]]` / `[header]` lines even
    outside the root: after a header is opened, a bare `key = ...` line would
    land inside that table instead of its real parent.
    """
    scalars = {}
    arrays = []
    inline_tables = {}
    tables = {}
    for k, v in data.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            arrays.append((k, v))
        elif isinstance(v, dict):
            if _inline_form(k, v) is not None:
                inline_tables[k] = v
            else:
                tables[k] = v
        else:
            scalars[k] = v

    for k, v in scalars.items():
        buf.write("{} = {}\n".format(_dump_key(k), _format_inline(v)))

    for k, v in inline_tables.items():
        buf.write("{}\n".format(_inline_form(k, v)))

    for k, items in arrays:
        for item in items:
            header = "{}{}".format(prefix, _dump_key(k))
            buf.write("\n[[{}]]\n".format(header))
            # Carry the array header into the item's nested dicts so they
            # render as `[<array>.<key>]` (a sub-table of the current array
            # element) rather than a bogus top-level `[<key>]`.
            _dump_section(buf, item, prefix=header + ".")

    for k, v in tables.items():
        header = "{}{}".format(prefix, _dump_key(k))
        if _needs_scope(v):
            buf.write("\n[{}]\n".format(header))
        _dump_section(buf, v, prefix=header + ".")


def toml_dumps(data: Dict[str, Any]) -> str:
    """Render `data` as TOML. Hand-written: stdlib tomllib and tomli have no
    write API, and fields copied verbatim from llmw must round-trip."""
    buf = io.StringIO()
    _dump_section(buf, data, prefix="")
    return buf.getvalue()


# Loader: prefer stdlib tomllib (3.11+), fall back to tomli.
# pyproject pins `tomli>=1.1` for Python <3.11, so the fallback is always
# available when tomllib is missing.
try:
    from tomllib import loads as toml_loads
except ImportError:  # Python <3.11
    from tomli import loads as toml_loads  # type: ignore[no-redef]
