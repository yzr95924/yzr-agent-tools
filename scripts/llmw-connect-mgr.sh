#!/usr/bin/env bash
# Manage llmw-connect-mgr: install | uninstall
#
# Self-contained: writes the bin/llmw-connect-mgr wrapper, links bash/zsh/fish
# completions, and manages a per-tool PATH block in your shell rc. One script
# per tool — there is no shared helper to (mis)invoke directly.
#
# Usage:
#     scripts/llmw-connect-mgr.sh install      # wrapper + completions + PATH block
#     scripts/llmw-connect-mgr.sh uninstall    # remove all of the above
set -euo pipefail

TOOL="llmw-connect-mgr"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$PROJECT_ROOT/bin"
COMPLETION_SRC_DIR="$PROJECT_ROOT/completions"
# bash-completion lookup dir. On macOS with Homebrew's bash-completion@2,
# the XDG dir is not scanned — link into the brew prefix instead (Intel:
# /usr/local, Apple Silicon: /opt/homebrew). Everything else (Linux, macOS
# without brew) keeps the XDG path.
bash_completion_dir() {
    if [ "$(uname)" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        local prefix
        prefix="$(brew --prefix 2>/dev/null || true)"
        if [ -n "$prefix" ] && [ -d "$prefix" ]; then
            printf '%s\n' "$prefix/share/bash-completion/completions"
            return 0
        fi
    fi
    printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions"
}

BASH_COMPLETION_DIR="$(bash_completion_dir)"
# zsh loads completions from $fpath; ~/.zfunc is a per-user dir that works for
# system zsh, Homebrew zsh, and Linux zsh alike (no sudo needed). The rc block
# below prepends it to fpath.
ZSH_COMPLETION_DIR="$HOME/.zfunc"
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
    [ -f "$COMPLETION_SRC_DIR/_$TOOL" ] && \
        link_completion "$COMPLETION_SRC_DIR/_$TOOL" "$ZSH_COMPLETION_DIR/_$TOOL"
}

uninstall_completions() {
    remove_completion_link "$BASH_COMPLETION_DIR/$TOOL"
    remove_completion_link "$FISH_COMPLETION_DIR/$TOOL.fish"
    remove_completion_link "$ZSH_COMPLETION_DIR/_$TOOL"
}

# --- shell-rc PATH block ------------------------------------------------------

rc_path() {
    case "${SHELL:-}" in
        */zsh) printf '%s\n' "$HOME/.zshrc" ;;
        */bash|*) printf '%s\n' "$HOME/.bashrc" ;;
    esac
}

# Strip the inclusive [begin, end] marker block from $1 (exact full-line
# match), plus the single blank line the writer prepends before the block —
# without that, re-installs would accumulate one orphan blank line each.
strip_block() {
    local rc="$1" begin="$2" end="$3"
    [ -f "$rc" ] || return 0
    grep -qxF "$begin" "$rc" || return 0
    local tmp; tmp="$(mktemp)"
    awk -v begin="$begin" -v end="$end" '
        { lines[++n] = $0 }
        END {
            m = 0; i = 1
            while (i <= n) {
                if (lines[i] == begin) {
                    if (m > 0 && out[m] == "") m--   # drop preceding blank
                    while (i <= n && lines[i] != end) i++
                    i++
                    continue
                }
                out[++m] = lines[i]
                i++
            }
            for (j = 1; j <= m; j++) print out[j]
        }
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

    # Idempotent rewrite: always strip our own block first, then append the
    # current form. This also migrates legacy blocks (e.g. ones that sourced
    # the bash completion into ~/.zshrc, which errors under zsh).
    strip_block "$rc" "$PATH_BEGIN" "$PATH_END"

    local comp_src="$COMPLETION_SRC_DIR/$TOOL.bash"
    {
        printf '\n%s\n' "$PATH_BEGIN"
        printf 'export PATH="%s:$PATH"\n' "$BIN_DIR"
        case "$rc" in
            *.zshrc)
                # zsh: put ~/.zfunc on fpath and make sure the completion
                # system is up. compinit is re-run deliberately: if a framework
                # (oh-my-zsh & co) already ran it earlier in .zshrc, it did so
                # BEFORE our fpath line, so our completion files would not be
                # picked up without a rescan.
                printf 'fpath=("%s" $fpath)\n' "$ZSH_COMPLETION_DIR"
                printf 'autoload -Uz compinit && compinit\n'
                ;;
            *)
                # bash: source the bash completion directly.
                printf '[ -f "%s" ] && . "%s"\n' "$comp_src" "$comp_src"
                ;;
        esac
        printf '%s\n' "$PATH_END"
    } >> "$rc"
    log "Wrote PATH block to $rc"
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

  install    Write the $TOOL wrapper ($BIN_DIR/$TOOL), link bash/zsh/fish
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
