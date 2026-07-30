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

update_rc() {
    local rc_path="$1"
    local path_line="export PATH=\"$BIN_DIR:\$PATH\""
    local begin="# model-switch PATH begin"
    local end="# model-switch PATH end"
    local block="$begin
$path_line
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
        return
    fi

    {
        echo ""
        echo "$block"
    } >> "$rc_path"
    echo ">> Appended PATH entry to $rc_path"
}

case "${SHELL:-}" in
    */zsh)
        update_rc "$HOME/.zshrc"
        ;;
    */bash|*)
        update_rc "$HOME/.bashrc"
        ;;
esac

cat <<EOF

Installed.

  repo : $PROJECT_ROOT
  exec : $BIN_DIR/model-switch

To use it in this shell:
  source $HOME/.bashrc   # or ~/.zshrc
  model-switch --help

Or run it directly without PATH changes:
  $BIN_DIR/model-switch --help
EOF
