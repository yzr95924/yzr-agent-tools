# bash completion for mcp-plugin-mgr(1)
#
# Dynamic candidates (server / driver / preset names) come from the hidden
# `mcp-plugin-mgr _complete <what>` plumbing command, so completion always
# reflects the real servers.toml / driver registry / built-in presets.
#
# Loaded two ways by scripts/mcp-plugin-mgr.sh install (both harmless if repeated):
#   - symlinked into ~/.local/share/bash-completion/completions/mcp-plugin-mgr
#   - sourced from the PATH marker block in ~/.bashrc

_mcp_plugin_mgr() {
    local cur prev cmd
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd=""

    # Completing a flag's value?
    case "$prev" in
        --driver)
            COMPREPLY=( $(compgen -W "$(mcp-plugin-mgr _complete drivers 2>/dev/null)" -- "$cur") )
            return 0
            ;;
        --url|--token|--header|--command|--env|--description)
            # Free-form values: nothing sensible to offer.
            COMPREPLY=()
            return 0
            ;;
    esac

    # Walk the completed words to establish context:
    #   cmd = init | add | list | remove | presets | status   (COMP_WORDS[1])
    local i w
    for (( i = 1; i < COMP_CWORD; i++ )); do
        w="${COMP_WORDS[i]}"
        case "$w" in
            init|add|list|remove|presets|status)
                [ -z "$cmd" ] && cmd="$w"
                ;;
        esac
    done

    if [ -z "$cmd" ]; then
        COMPREPLY=( $(compgen -W "init add list remove presets status --help" -- "$cur") )
        return 0
    fi

    case "$cmd" in
        init|list|presets)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            ;;
        status)
            COMPREPLY=( $(compgen -W "--driver --all-drivers --help" -- "$cur") )
            ;;
        add)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "--url --token --header --stdio --command --env --description --driver --all-drivers --no-apply --force --help" -- "$cur") )
            else
                # First positional: a preset name, or an already-configured server.
                COMPREPLY=( $(compgen -W "$(mcp-plugin-mgr _complete presets 2>/dev/null) $(mcp-plugin-mgr _complete servers 2>/dev/null)" -- "$cur") )
            fi
            ;;
        remove)
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "--driver --all-drivers --help" -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "$(mcp-plugin-mgr _complete servers 2>/dev/null)" -- "$cur") )
            fi
            ;;
    esac
    return 0
}

complete -F _mcp_plugin_mgr mcp-plugin-mgr
