#!/usr/bin/env bash
# Uninstall model-switch:
#   1. remove repo-local wrapper bin/model-switch
#   2. strip the idempotent PATH marker from the user's shell rc
#      (matches the marker block written by install.sh)
#
# Notes:
#   - Does NOT touch a legacy .venv/ — that was created by an earlier install
#     flow and is unrelated to current install. Clean it up manually if you
#     want it gone: `rm -rf .venv`.
#   - Does NOT touch user data under ~/.config/model-switch/ (models.toml,
#     state.toml). Those are CLI data, not install artifacts.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"

begin_marker="# model-switch PATH begin"
end_marker="# model-switch PATH end"

# 1. Remove wrapper (idempotent: missing wrapper is fine).
if [ -f "$BIN_DIR/model-switch" ]; then
    rm -f "$BIN_DIR/model-switch"
    echo "Removed wrapper: $BIN_DIR/model-switch"
else
    echo "No wrapper at $BIN_DIR/model-switch (already gone)"
fi

# 2. Strip the marker block from the user's shell rc.
#    Uses awk: print lines OUTSIDE the [begin, end] inclusive range.
#    Skips rc files that have no marker (idempotent).
strip_marker() {
    local rc_path="$1"
    if [ ! -f "$rc_path" ]; then
        return 0
    fi
    if ! grep -qxF "$begin_marker" "$rc_path"; then
        echo "  $rc_path: no model-switch PATH marker, skipping"
        return 0
    fi
    # awk state machine: in-block (skip) vs outside (print).
    local tmp
    tmp="$(mktemp)"
    awk -v begin="$begin_marker" -v end="$end_marker" '
        $0 == begin      { in_block = 1; next }
        $0 == end        { in_block = 0; next }
        in_block         { next }
                      { print }
    ' "$rc_path" > "$tmp"
    mv "$tmp" "$rc_path"
    echo "Stripped model-switch PATH marker from $rc_path"
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

  removed : $BIN_DIR/model-switch
  rc      : PATH marker stripped (per detected shell)

Restart your shell (or 'source ~/.bashrc' / '~/.zshrc') to drop the
PATH entry from the running session.
EOF
