# fish completion for opencode-plugins
#
# Dynamic plugin-name candidates come from the hidden
# `opencode-plugins _complete plugins` plumbing command.
#
# scripts/opencode-plugins.sh install symlinks this file into
# ~/.config/fish/completions/.

function __fish_opencode_plugins_using_command
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2; and contains -- $cmd[2] $argv
end

complete -c opencode-plugins -f -n '__fish_use_subcommand' -a list -d 'Show bundled plugins and their status'
complete -c opencode-plugins -f -n '__fish_use_subcommand' -a install -d 'Copy plugin sources into OpenCode and register them'
complete -c opencode-plugins -f -n '__fish_use_subcommand' -a uninstall -d 'Deregister and remove installed plugins'
complete -c opencode-plugins -f -n '__fish_use_subcommand' -a sync -d 'Re-copy plugin sources after editing them'
complete -c opencode-plugins -f -n '__fish_use_subcommand' -a verify -d 'Check install integrity'

complete -c opencode-plugins -f -n '__fish_opencode_plugins_using_command install sync verify' -a '(opencode-plugins _complete plugins 2>/dev/null)' -d 'bundled plugin'
