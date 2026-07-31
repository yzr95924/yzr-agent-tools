# bash completion for model-switch(1)
#
# Dynamic candidates (model names, driver names) come from the hidden
# `model-switch _complete <what>` plumbing command, so completion always
# reflects the real models.toml / driver registry.
#
# Loaded two ways by scripts/install.sh (both harmless if repeated):
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
        --driver)
            COMPREPLY=( $(compgen -W "$(model-switch _complete drivers 2>/dev/null)" -- "$cur") )
            return 0
            ;;
        --base-url|--api-key|--model-name|--description|--context-window)
            # Free-form values: nothing sensible to offer.
            COMPREPLY=()
            return 0
            ;;
    esac

    # Walk the completed words to establish context:
    #   cmd    = init | model | status   (COMP_WORDS[1])
    #   action = add | list | show | remove | use | import   (COMP_WORDS[2], under `model`)
    local i w
    for (( i = 1; i < COMP_CWORD; i++ )); do
        w="${COMP_WORDS[i]}"
        case "$w" in
            init|model|status)
                [ -z "$cmd" ] && cmd="$w"
                ;;
            add|list|show|remove|use|import)
                [ "$cmd" = "model" ] && [ -z "$action" ] && action="$w"
                ;;
        esac
    done

    if [ -z "$cmd" ]; then
        COMPREPLY=( $(compgen -W "init model status" -- "$cur") )
        return 0
    fi

    case "$cmd" in
        init)
            COMPREPLY=()
            ;;
        status)
            COMPREPLY=( $(compgen -W "--driver --all-drivers --help" -- "$cur") )
            ;;
        model)
            if [ -z "$action" ]; then
                COMPREPLY=( $(compgen -W "add list show remove use import" -- "$cur") )
                return 0
            fi
            case "$action" in
                add)
                    COMPREPLY=( $(compgen -W "--base-url --api-key --model-name --description --context-window --help" -- "$cur") )
                    ;;
                list)
                    COMPREPLY=( $(compgen -W "--help" -- "$cur") )
                    ;;
                show|remove|use)
                    if [[ "$cur" == -* ]]; then
                        local flags="--help"
                        [ "$action" = "use" ] && flags="--driver --all-drivers --help"
                        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
                    else
                        COMPREPLY=( $(compgen -W "$(model-switch _complete models 2>/dev/null)" -- "$cur") )
                    fi
                    ;;
                import)
                    if [[ "$cur" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--merge --help" -- "$cur") )
                    else
                        # Source TOML path: plain filename completion.
                        COMPREPLY=( $(compgen -f -- "$cur") )
                    fi
                    ;;
            esac
            ;;
    esac
    return 0
}

complete -F _model_switch model-switch
