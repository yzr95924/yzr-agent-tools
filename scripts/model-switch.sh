#!/usr/bin/env bash
# Per-tool control for model-switch: install | uninstall
#
# Manages ONE tool's install artifacts: the bin/model-switch wrapper and its
# bash/fish completion symlinks. It does NOT touch your shell rc — that
# repo-global PATH block is owned by scripts/install.sh / uninstall.sh, which
# loop over every scripts/<tool>.sh.
#
# Usage:
#     scripts/model-switch.sh install      # write wrapper + link completions
#     scripts/model-switch.sh uninstall    # remove wrapper + completion links
#
# Pattern mirrors scripts/html-mcp.sh (one script, subcommand dispatch).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/_common.sh"

TOOL="model-switch"

usage() {
    cat >&2 <<EOF
Usage: $(basename "$0") {install|uninstall}

  install    Write the $TOOL wrapper ($BIN_DIR/$TOOL) and link bash/fish completions.
  uninstall  Remove the $TOOL wrapper and its completion symlinks.

This manages ONE tool. To install/uninstall every tool in the repo AND manage
the shared PATH block in your shell rc, use:
  scripts/install.sh        scripts/uninstall.sh
EOF
    exit 64
}

[ $# -ge 1 ] || usage
sub="$1"; shift || true

case "$sub" in
    install)   do_install_tool "$TOOL" ;;
    uninstall) do_uninstall_tool "$TOOL" ;;
    -h|--help|help) usage ;;
    *) log "Unknown subcommand: $sub"; usage ;;
esac
