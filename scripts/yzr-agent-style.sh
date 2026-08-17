#!/usr/bin/env bash
# yzr-agent-style: install | uninstall
#
# Thin shell — just invokes the Python CLI with the repo's src/ on PYTHONPATH.
# No wrapper, no PATH block, no completions: the tool's work is a one-shot
# write into each agent's rules file, so there is nothing persistent to install.
#
# Usage:
#     bash scripts/yzr-agent-style.sh install      # write template into all targets
#     bash scripts/yzr-agent-style.sh uninstall    # remove template block from all targets
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -m yzr_agent_style "$@"