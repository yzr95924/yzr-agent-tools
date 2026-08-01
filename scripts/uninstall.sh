#!/usr/bin/env bash
# Uninstall yzr-agent-tools:
#   1. remove per-tool repo-local wrappers under bin/
#   2. strip the idempotent PATH marker from the user's shell rc
#      (matches the marker block written by install.sh)
#   3. remove per-tool completion symlinks (only those pointing into this repo)
#
# Notes:
#   - Does NOT touch a legacy .venv/ — that was created by an earlier install
#     flow and is unrelated to current install. Clean it up manually if you
#     want it gone: `rm -rf .venv`.
#   - Does NOT touch user data under ~/.config/<tool>/ (config.toml, etc.).
#     Those are CLI data, not install artifacts.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"

TOOLS=(
    "model-switch"
    "html-mcp"
)

# Two possible markers — the new (post-html-mcp) one and the legacy one
# written by older installs. Both are stripped.
begin_marker="# yzr-agent-tools PATH begin"
end_marker="# yzr-agent-tools PATH end"
legacy_begin="# model-switch PATH begin"
legacy_end="# model-switch PATH end"

# 1. Remove wrappers (idempotent: missing wrapper is fine).
for tool in "${TOOLS[@]}"; do
    if [ -f "$BIN_DIR/$tool" ]; then
        rm -f "$BIN_DIR/$tool"
        echo "Removed wrapper: $BIN_DIR/$tool"
    else
        echo "No wrapper at $BIN_DIR/$tool (already gone)"
    fi
done

# 2. Strip the marker block from the user's shell rc.
#    Uses awk: print lines OUTSIDE the [begin, end] inclusive range.
#    Strips both new and legacy markers.
strip_marker() {
    local rc_path="$1"
    [ ! -f "$rc_path" ] && return 0

    # Run multiple awk passes — one per marker pair — so a file can have
    # both the new and legacy blocks (highly unlikely, but safe).
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

# 3. Remove completion symlinks (only those pointing into this repo).
remove_completion_link() {
    local link="$1"
    if [ -L "$link" ]; then
        case "$(readlink "$link")" in
            "$PROJECT_ROOT"/completions/*)
                rm -f "$link"
                echo "Removed completion link: $link"
                ;;
            *)
                echo "  $link points elsewhere, leaving it alone"
                ;;
        esac
    fi
}

BASH_COMPLETION_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
FISH_COMPLETION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"
for tool in "${TOOLS[@]}"; do
    remove_completion_link "$BASH_COMPLETION_DIR/$tool"
    remove_completion_link "$FISH_COMPLETION_DIR/$tool.fish"
done

cat <<EOF

Uninstalled.

  removed : ${TOOLS[@]/#/$BIN_DIR/}
  rc      : PATH marker stripped (per detected shell)

Restart your shell (or 'source ~/.bashrc' / '~/.zshrc') to drop the
PATH entry from the running session.
EOF