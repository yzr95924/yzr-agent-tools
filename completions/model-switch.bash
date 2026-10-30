# bash completion for model-switch(1)
#
# Dynamic model references come from the hidden `model-switch _complete
# models` plumbing command, so completion always reflects the real
# models.toml registry.
#
# Loaded two ways by scripts/model-switch.sh install (both harmless if repeated):
#   - symlinked into ~/.local/share/bash-completion/completions/model-switch
#   - sourced from the PATH marker block in ~/.bashrc

_model_switch() {
    local cur prev cmd action
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd=""
    action=""

    # Completing a flag's value?
    case "$prev" in
        --api-key|--catalog-provider)
            # Free-form values: nothing sensible to offer.
            COMPREPLY=()
            return 0
            ;;
    esac

    # Walk the completed words to establish context:
    #   cmd    = model | status   (COMP_WORDS[1])
    #   action = add | list | show | remove | use | align   (COMP_WORDS[2], under `model`)
    local i w
    for (( i = 1; i < COMP_CWORD; i++ )); do
        w="${COMP_WORDS[i]}"
        case "$w" in
            model|status)
                [ -z "$cmd" ] && cmd="$w"
                ;;
            add|list|show|remove|use|align)
                [ "$cmd" = "model" ] && [ -z "$action" ] && action="$w"
                ;;
        esac
    done

    if [ -z "$cmd" ]; then
        COMPREPLY=( $(compgen -W "model status" -- "$cur") )
        return 0
    fi

    case "$cmd" in
        status)
            COMPREPLY=( $(compgen -W "--help" -- "$cur") )
            ;;
        model)
            if [ -z "$action" ]; then
                COMPREPLY=( $(compgen -W "add list show remove use align" -- "$cur") )
                return 0
            fi
            case "$action" in
                add)
                    COMPREPLY=( $(compgen -W "--api-key --catalog-provider --yes --help" -- "$cur") )
                    ;;
                list)
                    COMPREPLY=( $(compgen -W "--help" -- "$cur") )
                    ;;
                show|use)
                    if [[ "$cur" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--help" -- "$cur") )
                    else
                        COMPREPLY=( $(compgen -W "$(model-switch _complete models 2>/dev/null)" -- "$cur") )
                    fi
                    ;;
                remove)
                    if [[ "$cur" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--yes --help" -- "$cur") )
                    else
                        COMPREPLY=( $(compgen -W "$(model-switch _complete models 2>/dev/null)" -- "$cur") )
                    fi
                    ;;
                align)
                    if [[ "$cur" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--help" -- "$cur") )
                    else
                        COMPREPLY=( $(compgen -W "$(model-switch _complete models 2>/dev/null)" -- "$cur") )
                    fi
                    ;;
            esac
            ;;
    esac
    return 0
}

complete -F _model_switch model-switch
