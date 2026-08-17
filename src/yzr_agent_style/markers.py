"""Marker-block management for yzr-agent-style.

The tool owns exactly the region of a target file between two HTML-comment
markers:

    <!-- yzr-agent-style begin -->
    <template content>
    <!-- yzr-agent-style end -->

Everything outside the block is the user's own content and is left untouched:
install appends a block to a marker-less file and replaces an existing block
in place (idempotent re-install); uninstall strips the block and deletes the
file if nothing remains. Writes are atomic (.tmp + os.replace), matching the
repo's atomic-write convention.
"""
import os
from pathlib import Path
from typing import Optional, Tuple

BEGIN = "<!-- yzr-agent-style begin -->"
END = "<!-- yzr-agent-style end -->"


def _block_range(text: str) -> Optional[Tuple[int, int]]:
    """Return (start, end) char offsets of the marker block, or None.

    Matches the markers as whole lines so a marker-like string embedded in
    prose does not count. If the BEGIN marker is present but no END follows,
    the block spans from BEGIN to end-of-file (cleans up a truncated block).
    """
    lines = text.split("\n")
    begin_i = None
    end_i = None
    for i, line in enumerate(lines):
        if line == BEGIN:
            begin_i = i
        elif line == END and begin_i is not None and end_i is None:
            end_i = i
            break
    if begin_i is None:
        return None

    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1

    start = starts[begin_i]
    if end_i is None:
        return start, len(text)
    end = starts[end_i] + len(lines[end_i])
    if end < len(text) and text[end] == "\n":
        end += 1
    return start, end


def render_block(template_text: str) -> str:
    """Wrap template content in the marker block."""
    body = template_text.rstrip("\n")
    return "{0}\n{1}\n{2}\n".format(BEGIN, body, END)


def install_block(path: Path, template_text: str) -> str:
    """Ensure `path` contains a marker block with the template content.

    Returns one of:
      "created"  — file did not exist (or was blank); wrote a fresh block
      "appended" — file existed without a marker block; block appended at end
      "updated"  — replaced the content of an existing marker block
    """
    text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8")

    block = render_block(template_text)
    rng = _block_range(text)
    if rng is None:
        if text.strip():
            new_text = text.rstrip("\n") + "\n\n" + block
            status = "appended"
        else:
            new_text = block
            status = "created"
    else:
        start, end = rng
        new_text = text[:start] + block + text[end:]
        status = "updated"

    _atomic_write(path, new_text)
    return status


def remove_block(path: Path) -> str:
    """Remove the marker block from `path` (leaving user content intact).

    Returns one of:
      "absent"       — file does not exist
      "untouched"    — file exists but has no marker block
      "stripped"     — block removed; file kept (user content remains)
      "removed-file" — block removed; file deleted (nothing left but the block)
    """
    if not path.exists():
        return "absent"
    text = path.read_text(encoding="utf-8")
    rng = _block_range(text)
    if rng is None:
        return "untouched"

    start, end = rng
    remainder = (text[:start] + text[end:]).strip()
    if not remainder:
        path.unlink()
        return "removed-file"
    _atomic_write(path, remainder.rstrip("\n") + "\n")
    return "stripped"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))