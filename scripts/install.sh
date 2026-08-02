#!/usr/bin/env bash
# Install yzr-agent-tools — every tool + the shared PATH block.
#
# Per-tool artifacts (the bin/<tool> wrapper + bash/fish completion symlinks)
# are owned by scripts/<tool>.sh install. This script is the AGGREGATOR: it
# runs each per-tool install, then manages the one repo-global PATH marker
# block in the user's shell rc (one block for all tools).
#
# No virtualenv, no `pip install`. See README "Install" for runtime / dev dep
# notes (Python<3.11 needs tomli; running tests needs pytest + pytest-cov).
#
# Usage:
#   bash scripts/install.sh         # default: bash
#   FISH=1 bash scripts/install.sh  # source this to update current shell
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$PROJECT_ROOT/scripts"
BIN_DIR="$PROJECT_ROOT/bin"

# Tools shipped by this repo. Each has its own scripts/<tool>.sh install.
TOOLS=(
    "model-switch"
    "html-mcp"
    "mcp-plugin-mgr"
)

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found on PATH." >&2
    exit 1
fi

# Optional legacy-state warning: an old install may have left a .venv behind.
# The new flow doesn't use it; users can remove it at their leisure.
if [ -d "$PROJECT_ROOT/.venv" ]; then
    cat >&2 <<'NOTE'
>> Detected legacy .venv/ from a previous install.
   The new install flow does not use it; safe to remove manually:
       rm -rf .venv
NOTE
fi

# Warn about runtime deps the user must supply themselves (mirrors the
# llm-workspace-cli install.sh idiom: stderr notice, no auto-install).
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    cat >&2 <<'NOTE'
>> Note: Python < 3.11 detected.
   yzr-agent-tools needs tomli. Install it yourself before running the CLI:
       pip install --user 'tomli>=1.1'
   Continuing with install — tomli will be required at runtime.
NOTE
fi

# --- per-tool wrapper + completions -----------------------------------------

for tool in "${TOOLS[@]}"; do
    bash "$SCRIPT_DIR/$tool.sh" install
done

# --- shared PATH block in shell rc ------------------------------------------

COMPLETION_SRC_BASH_DIR="$PROJECT_ROOT/completions"
BASH_COMPLETION_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
FISH_COMPLETION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"

update_rc() {
    local rc_path="$1"
    local completion_src="${2:-}"
    local path_line="export PATH=\"$BIN_DIR:\$PATH\""
    local begin="# yzr-agent-tools PATH begin"
    local end="# yzr-agent-tools PATH end"
    local block="$begin
$path_line"
    if [ -n "$completion_src" ]; then
        block="$block
[ -f \"$completion_src\" ] && . \"$completion_src\""
    fi
    block="$block
$end"

    # Ensure the rc file's parent dir exists. Some environments (fresh CI
    # containers, chroots, quirky Docker setups) ship a $HOME that has no
    # $HOME/.bashrc / $HOME/.zshrc yet — writing to those paths then errors.
    mkdir -p "$(dirname "$rc_path")"

    if [ ! -f "$rc_path" ]; then
        : > "$rc_path"
    fi

    # Upgrade path (BEFORE idempotency check): installs from before this
    # script's marker rename have the old `# model-switch PATH begin/end`
    # block. Rewrite the labels in place so the idempotency check below
    # doesn't see two blocks.
    if grep -qxF "# model-switch PATH begin" "$rc_path"; then
        sed -i.bak \
            -e 's|^# model-switch PATH begin|# yzr-agent-tools PATH begin|' \
            -e 's|^# model-switch PATH end|# yzr-agent-tools PATH end|' \
            "$rc_path"
        rm -f "$rc_path.bak"
        echo ">> Rewrote legacy model-switch PATH marker to yzr-agent-tools in $rc_path"
    fi

    # Upgrade path: legacy installs have the marker block but no source
    # line for bash completion (covers setups without the bash-completion
    # package). Splice one in just before the end marker — the in-rc
    # source is the fallback path when the XDG symlink isn't picked up.
    if [ -n "$completion_src" ] && grep -qxF "$begin" "$rc_path" \
            && ! grep -qF "$completion_src" "$rc_path"; then
        local tmp
        tmp="$(mktemp)"
        awk -v end="$end" -v line="[ -f \"$completion_src\" ] && . \"$completion_src\"" '
            $0 == end && !done { print line; done = 1 }
            { print }
        ' "$rc_path" > "$tmp"
        mv "$tmp" "$rc_path"
        echo ">> Spliced completion source line into existing block in $rc_path"
    fi

    # Idempotency: marker line already present => skip.
    if grep -qxF "$begin" "$rc_path"; then
        echo ">> PATH entry already present in $rc_path"
    else
        {
            echo ""
            echo "$block"
        } >> "$rc_path"
        echo ">> Appended PATH entry to $rc_path"
    fi
}

case "${SHELL:-}" in
    */zsh)
        update_rc "$HOME/.zshrc"
        ;;
    */bash|*)
        # Source every bash completion we ship so even setups without
        # bash-completion pick them up. Pass the first one for the in-rc
        # source line (belt-and-suspenders fallback).
        bash_srcs=()
        for tool in "${TOOLS[@]}"; do
            [ -f "$COMPLETION_SRC_BASH_DIR/$tool.bash" ] && bash_srcs+=("$COMPLETION_SRC_BASH_DIR/$tool.bash")
        done
        if [ "${#bash_srcs[@]}" -gt 0 ]; then
            update_rc "$HOME/.bashrc" "${bash_srcs[0]}"
        else
            update_rc "$HOME/.bashrc"
        fi
        ;;
esac

cat <<EOF

Installed.

  repo : $PROJECT_ROOT
  bin  : $BIN_DIR
  tools: ${TOOLS[@]}
  comp : $BASH_COMPLETION_DIR/ (bash)  $FISH_COMPLETION_DIR/ (fish)

To install a single tool only (no shell-rc change):
  scripts/<tool>.sh install      # e.g. scripts/mcp-plugin-mgr.sh install

To use it in this shell:
  source $HOME/.bashrc   # or ~/.zshrc
  html-mcp --help

Or run it directly without PATH changes:
  $BIN_DIR/html-mcp --help
EOF
