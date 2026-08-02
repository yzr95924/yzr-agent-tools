#!/usr/bin/env bash
# Uninstall yzr-agent-tools — every tool + the shared PATH block.
#
# Per-tool cleanup (bin/<tool> wrapper + completion symlinks) is owned by
# scripts/<tool>.sh uninstall. This script is the AGGREGATOR: it runs each
# per-tool uninstall, then strips the one repo-global PATH marker block from
# the user's shell rc.
#
# Notes:
#   - Does NOT touch a legacy .venv/ — that was created by an earlier install
#     flow and is unrelated to current install. Clean it up manually if you
#     want it gone: `rm -rf .venv`.
#   - Does NOT touch user data under ~/.config/<tool>/ (config.toml, etc.).
#     Those are CLI data, not install artifacts.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$PROJECT_ROOT/scripts"
BIN_DIR="$PROJECT_ROOT/bin"

TOOLS=(
    "model-switch"
    "html-mcp"
    "mcp-plugin-mgr"
)

# --- per-tool wrapper + completions -----------------------------------------

for tool in "${TOOLS[@]}"; do
    bash "$SCRIPT_DIR/$tool.sh" uninstall
done

# --- strip the shared PATH marker from shell rc -----------------------------

# Two possible markers — the new (post-html-mcp) one and the legacy one
# written by older installs. Both are stripped.
begin_marker="# yzr-agent-tools PATH begin"
end_marker="# yzr-agent-tools PATH end"
legacy_begin="# model-switch PATH begin"
legacy_end="# model-switch PATH end"

# Uses awk: print lines OUTSIDE the [begin, end] inclusive range.
# Runs one pass per marker pair so a file can have both (unlikely, but safe).
strip_marker() {
    local rc_path="$1"
    [ ! -f "$rc_path" ] && return 0

    for pair in "$begin_marker|$end_marker" "$legacy_begin|$legacy_end"; do
        local b="${pair%|*}"
        local e="${pair#*|}"
        if grep -qxF "$b" "$rc_path"; then
            local tmp
            tmp="$(mktemp)"
            awk -v begin="$b" -v end="$e" '
                $0 == begin      { in_block = 1; next }
                $0 == end        { in_block = 0; next }
                in_block         { next }
                              { print }
            ' "$rc_path" > "$tmp"
            mv "$tmp" "$rc_path"
            echo "Stripped PATH marker block ($b) from $rc_path"
        else
            echo "  $rc_path: no $b marker, skipping"
        fi
    done
}

case "${SHELL:-}" in
    */zsh)
        strip_marker "$HOME/.zshrc"
        ;;
    */bash|*)
        strip_marker "$HOME/.bashrc"
        ;;
esac

cat <<EOF

Uninstalled.

  removed : ${TOOLS[@]/#/$BIN_DIR/}
  rc      : PATH marker stripped (per detected shell)

To uninstall a single tool only (no shell-rc change):
  scripts/<tool>.sh uninstall    # e.g. scripts/mcp-plugin-mgr.sh uninstall

Restart your shell (or 'source ~/.bashrc' / '~/.zshrc') to drop the
PATH entry from the running session.
EOF
