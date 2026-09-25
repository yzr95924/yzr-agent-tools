# bash completion for opencode-plugins(1)
#
# Dynamic plugin-name candidates come from the hidden
# `opencode-plugins _complete plugins` plumbing command, so completion always
# reflects the bundled sources.
#
# Loaded two ways by scripts/opencode-plugins.sh install (both harmless if
# repeated):
#   - symlinked into ~/.local/share/bash-completion/completions/opencode-plugins
#   - sourced from the PATH marker block in ~/.bashrc

_opencode_plugins() {
    local cur prev cmd
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd=""

    local i w
    for (( i = 1; i < COMP_CWORD; i++ )); do
        w="${COMP_WORDS[i]}"
        case "$w" in
            list|install|uninstall|sync|verify)
                [ -z "$cmd" ] && cmd="$w"
                ;;
        esac
    done

    if [ -z "$cmd" ]; then
        COMPREPLY=( $(compgen -W "list install uninstall sync verify" -- "$cur") )
        return 0
    fi

    case "$cmd" in
        list)
            COMPREPLY=()
            ;;
        install|uninstall|sync|verify)
            COMPREPLY=( $(compgen -W "$(opencode-plugins _complete plugins 2>/dev/null)" -- "$cur") )
            ;;
    esac
}
complete -F _opencode_plugins opencode-plugins
