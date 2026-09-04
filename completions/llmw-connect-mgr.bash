# bash completion for llmw-connect-mgr
#
# Static command surface: install / config / upgrade / uninstall plus their
# flags. scripts/llmw-connect-mgr.sh install symlinks this file into
# ~/.local/share/bash-completion/completions/ and sources it from the PATH
# marker block in ~/.bashrc (both harmless if repeated).

_llmw_connect_mgr() {
    local cur prev cmd
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd="${COMP_WORDS[1]:-}"

    local commands="install config upgrade uninstall"
    local common="--telegram-token --telegram-allow-from --dingtalk --dingtalk-id --dingtalk-secret --yes -y"
    local flags_for=""
    case "$cmd" in
        install) flags_for="$common --no-systemd --verify-timeout" ;;
        config)  flags_for="$common --no-restart --verify-timeout" ;;
        upgrade) flags_for="--verify-timeout" ;;
        uninstall) flags_for="--remove-npm --purge" ;;
    esac

    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$flags_for" -- "$cur") )
        return 0
    fi
    if [[ -z "$cmd" ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi
    COMPREPLY=()
    return 0
}
complete -F _llmw_connect_mgr llmw-connect-mgr
