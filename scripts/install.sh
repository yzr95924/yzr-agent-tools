#!/usr/bin/env bash
# Install model-switch: write a thin bash wrapper at $PROJECT_ROOT/bin/model-switch
# that runs `python3 -m model_switch` with PYTHONPATH pointing at $PROJECT_ROOT/src,
# and append an idempotent PATH block to the user's shell rc.
#
# No virtualenv, no `pip install`. See README "Install" for runtime / dev dep
# notes (Python<3.11 needs tomli; running tests needs pytest + pytest-cov).
#
# Usage:
#   bash scripts/install.sh         # default: bash
#   FISH=1 bash scripts/install.sh  # source this to update current shell
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"

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
   model-switch needs tomli. Install it yourself before running the CLI:
       pip install --user 'tomli>=1.1'
   Continuing with install — tomli will be required at runtime.
NOTE
fi

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/model-switch" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -m model_switch "$@"
WRAPPER
chmod +x "$BIN_DIR/model-switch"

# Shell completions (bash + fish). Symlinked (not copied) so a `git pull`
# refreshes them without re-running install.
#   bash: bash-completion's per-user dir + a source line inside the PATH
#         marker block in ~/.bashrc (covers setups without the
#         bash-completion package).
#   fish: auto-loaded from ~/.config/fish/completions/, no rc edit needed.
COMPLETION_SRC_BASH="$PROJECT_ROOT/completions/model-switch.bash"
COMPLETION_SRC_FISH="$PROJECT_ROOT/completions/model-switch.fish"
BASH_COMPLETION_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
FISH_COMPLETION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"

link_completion() {
    local src="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        echo ">> $dest exists and is not a symlink; leaving it alone" >&2
        return 0
    fi
    ln -sfn "$src" "$dest"
    echo ">> Linked completion: $dest -> $src"
}

link_completion "$COMPLETION_SRC_BASH" "$BASH_COMPLETION_DIR/model-switch"
link_completion "$COMPLETION_SRC_FISH" "$FISH_COMPLETION_DIR/model-switch.fish"

update_rc() {
    local rc_path="$1"
    local completion_src="${2:-}"
    local path_line="export PATH=\"$BIN_DIR:\$PATH\""
    local begin="# model-switch PATH begin"
    local end="# model-switch PATH end"
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

    # Upgrade path: installs from before completions existed have the marker
    # block but no source line — splice one in just before the end marker.
    if [ -n "$completion_src" ] && ! grep -qF "$completion_src" "$rc_path"; then
        local tmp
        tmp="$(mktemp)"
        awk -v end="$end" -v line="[ -f \"$completion_src\" ] && . \"$completion_src\"" '
            $0 == end && !done { print line; done = 1 }
            { print }
        ' "$rc_path" > "$tmp"
        mv "$tmp" "$rc_path"
        echo ">> Added completion source line to $rc_path"
    fi
}

case "${SHELL:-}" in
    */zsh)
        update_rc "$HOME/.zshrc"
        ;;
    */bash|*)
        update_rc "$HOME/.bashrc" "$COMPLETION_SRC_BASH"
        ;;
esac

cat <<EOF

Installed.

  repo : $PROJECT_ROOT
  exec : $BIN_DIR/model-switch
  comp : $BASH_COMPLETION_DIR/model-switch (symlink)
         $FISH_COMPLETION_DIR/model-switch.fish (symlink)

To use it in this shell:
  source $HOME/.bashrc   # or ~/.zshrc
  model-switch --help

Or run it directly without PATH changes:
  $BIN_DIR/model-switch --help
EOF
