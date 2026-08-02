#!/usr/bin/env bash
# Manage mcp-plugin-mgr: install | uninstall
#
# Self-contained: writes the bin/mcp-plugin-mgr wrapper, links bash/fish
# completions, and manages a per-tool PATH block in your shell rc. One script
# per tool — there is no shared helper to (mis)invoke directly.
#
# Usage:
#     scripts/mcp-plugin-mgr.sh install      # wrapper + completions + PATH block
#     scripts/mcp-plugin-mgr.sh uninstall    # remove all of the above
set -euo pipefail

TOOL="mcp-plugin-mgr"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
COMPLETION_SRC_DIR="$PROJECT_ROOT/completions"
BASH_COMPLETION_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
FISH_COMPLETION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/fish/completions"

PATH_BEGIN="# yzr-agent-tools ${TOOL} PATH begin"
PATH_END="# yzr-agent-tools ${TOOL} PATH end"

log() { printf '>> %s\n' "$*" >&2; }

# --- wrapper ------------------------------------------------------------------

write_wrapper() {
    local py_module="${TOOL//-/_}"
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/$TOOL" <<WRAPPER
#!/usr/bin/env bash
set -euo pipefail
REPO="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="\$REPO/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -B -m ${py_module} "\$@"
WRAPPER
    chmod +x "$BIN_DIR/$TOOL"
}

remove_wrapper() { rm -f "$BIN_DIR/$TOOL"; }

# --- completions --------------------------------------------------------------

link_completion() {
    local src="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        log "$dest exists and is not a symlink; leaving it alone"
        return 0
    fi
    ln -sfn "$src" "$dest"
    log "Linked completion: $dest -> $src"
}

remove_completion_link() {
    local dest="$1"
    if [ -L "$dest" ]; then
        case "$(readlink "$dest")" in
            "$COMPLETION_SRC_DIR"/*) rm -f "$dest"; log "Removed completion link: $dest" ;;
            *) log "$dest points elsewhere, leaving it alone" ;;
        esac
    fi
}

install_completions() {
    [ -f "$COMPLETION_SRC_DIR/$TOOL.bash" ] && \
        link_completion "$COMPLETION_SRC_DIR/$TOOL.bash" "$BASH_COMPLETION_DIR/$TOOL"
    [ -f "$COMPLETION_SRC_DIR/$TOOL.fish" ] && \
        link_completion "$COMPLETION_SRC_DIR/$TOOL.fish" "$FISH_COMPLETION_DIR/$TOOL.fish"
}

uninstall_completions() {
    remove_completion_link "$BASH_COMPLETION_DIR/$TOOL"
    remove_completion_link "$FISH_COMPLETION_DIR/$TOOL.fish"
}

# --- shell-rc PATH block ------------------------------------------------------

rc_path() {
    case "${SHELL:-}" in
        */zsh) printf '%s\n' "$HOME/.zshrc" ;;
        */bash|*) printf '%s\n' "$HOME/.bashrc" ;;
    esac
}

# Strip the inclusive [begin, end] marker block from $1 (exact full-line match).
strip_block() {
    local rc="$1" begin="$2" end="$3"
    [ -f "$rc" ] || return 0
    grep -qxF "$begin" "$rc" || return 0
    local tmp; tmp="$(mktemp)"
    awk -v begin="$begin" -v end="$end" '
        $0 == begin { in_block = 1; next }
        $0 == end   { in_block = 0; next }
        in_block    { next }
                    { print }
    ' "$rc" > "$tmp"
    mv "$tmp" "$rc"
    log "Stripped marker block ($begin) from $rc"
}

ensure_path_block() {
    local rc; rc="$(rc_path)"
    mkdir -p "$(dirname "$rc")"
    [ -f "$rc" ] || : > "$rc"

    # One-time migration: clear legacy shared blocks from the old aggregator
    # design (exact-line match — cannot collide with this tool's own marker).
    strip_block "$rc" "# yzr-agent-tools PATH begin" "# yzr-agent-tools PATH end"
    strip_block "$rc" "# model-switch PATH begin" "# model-switch PATH end"

    if grep -qxF "$PATH_BEGIN" "$rc"; then
        log "PATH entry already present in $rc"
        return 0
    fi
    local comp_src="$COMPLETION_SRC_DIR/$TOOL.bash"
    {
        printf '\n%s\n' "$PATH_BEGIN"
        printf 'export PATH="%s:$PATH"\n' "$BIN_DIR"
        printf '[ -f "%s" ] && . "%s"\n' "$comp_src" "$comp_src"
        printf '%s\n' "$PATH_END"
    } >> "$rc"
    log "Appended PATH entry to $rc"
}

remove_path_block() { strip_block "$(rc_path)" "$PATH_BEGIN" "$PATH_END"; }

# --- dispatch -----------------------------------------------------------------

do_install() {
    write_wrapper; log "Wrote wrapper: $BIN_DIR/$TOOL"
    install_completions
    ensure_path_block
}

do_uninstall() {
    remove_wrapper; log "Removed wrapper: $BIN_DIR/$TOOL"
    uninstall_completions
    remove_path_block
}

usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") {install|uninstall}

  install    Write the $TOOL wrapper ($BIN_DIR/$TOOL), link bash/fish
             completions, and add a $TOOL PATH block to your shell rc.
  uninstall  Remove the wrapper, completion links, and PATH block.

Self-contained — each tool has its own script; there are no others to run.
EOF
    exit 64
}

[ $# -ge 1 ] || usage
sub="$1"; shift || true
case "$sub" in
    install)   do_install ;;
    uninstall) do_uninstall ;;
    -h|--help|help) usage ;;
    *) log "Unknown subcommand: $sub"; usage ;;
esac
