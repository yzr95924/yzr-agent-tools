# fish completion for mcp-plugin-mgr
#
# Dynamic candidates (server / driver / preset names) come from the hidden
# `mcp-plugin-mgr _complete <what>` plumbing command.
#
# scripts/install.sh symlinks this file into ~/.config/fish/completions/.

function __fish_mcp_plugin_mgr_servers
    mcp-plugin-mgr _complete servers 2>/dev/null
end

function __fish_mcp_plugin_mgr_drivers
    mcp-plugin-mgr _complete drivers 2>/dev/null
end

function __fish_mcp_plugin_mgr_presets
    mcp-plugin-mgr _complete presets 2>/dev/null
end

function __fish_mcp_plugin_mgr_needs_command
    set -l cmd (commandline -opc)
    test (count $cmd) -le 1
end

function __fish_mcp_plugin_mgr_using_command
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2; and contains -- $cmd[2] $argv
end

# True while the server-name positional after `add`/`remove` is unfilled.
function __fish_mcp_plugin_mgr_needs_name
    set -l cmd (commandline -opc)
    __fish_mcp_plugin_mgr_using_command add remove; or return 1
    test "$cmd[-1]" = --driver; and return 1
    set -l skip_next 0
    for tok in $cmd[3..-1]
        if test $skip_next -eq 1
            set skip_next 0
            continue
        end
        switch $tok
            case --driver
                set skip_next 1
            case '--*'
            case '*'
                return 1
        end
    end
    return 0
end

# --- top-level commands -------------------------------------------------------
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a init -d 'Initialize the config directory'
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a add -d 'Add an MCP server'
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a list -d 'List servers (with per-agent presence)'
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a remove -d 'Remove a server'
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a presets -d 'List built-in presets'
complete -c mcp-plugin-mgr -n __fish_mcp_plugin_mgr_needs_command -f -a status -d 'Show config paths and counts'

# --- name positional ----------------------------------------------------------
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_needs_name; and __fish_mcp_plugin_mgr_using_command add' -f -a '(__fish_mcp_plugin_mgr_presets)' -d 'preset'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_needs_name; and __fish_mcp_plugin_mgr_using_command add' -f -a '(__fish_mcp_plugin_mgr_servers)' -d 'server'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_needs_name; and __fish_mcp_plugin_mgr_using_command remove' -f -a '(__fish_mcp_plugin_mgr_servers)' -d 'server'

# --- flags: add ---------------------------------------------------------------
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l url -rf -d 'HTTP server URL'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l token -rf -d 'Bearer token fed into the preset auth header'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l header -rf -d 'Extra header KEY=VALUE (repeatable)'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l stdio -f -d 'Declare stdio transport'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l command -rf -d 'stdio: full command line (shlex-split)'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l env -rf -d 'stdio: env KEY=VALUE (repeatable)'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l description -rf -d 'Free-text description'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l driver -rf -a '(__fish_mcp_plugin_mgr_drivers)' -d 'Target a single agent driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l all-drivers -f -d 'Apply to every registered driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l no-apply -f -d 'Register only; do not write agent configs'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -l force -f -d 'Overwrite if the name already exists'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command add' -s h -l help -f -d 'Show help'

# --- flags: remove ------------------------------------------------------------
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command remove' -l driver -rf -a '(__fish_mcp_plugin_mgr_drivers)' -d 'Target a single agent driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command remove' -l all-drivers -f -d 'Apply to every registered driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command remove' -s h -l help -f -d 'Show help'

# --- flags: status ------------------------------------------------------------
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command status' -l driver -rf -a '(__fish_mcp_plugin_mgr_drivers)' -d 'Target a single agent driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command status' -l all-drivers -f -d 'Apply to every registered driver'
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command status' -s h -l help -f -d 'Show help'

# --- file-completion suppression ----------------------------------------------
complete -c mcp-plugin-mgr -n '__fish_mcp_plugin_mgr_using_command init list presets' -f
