# fish completion for model-switch
#
# Dynamic candidates (model names, driver names) come from the hidden
# `model-switch _complete <what>` plumbing command, so completion always
# reflects the real models.toml / driver registry.
#
# scripts/install.sh symlinks this file into ~/.config/fish/completions/.
#
# Note on helpers: `commandline -opc` under completion yields only the
# *completed* tokens (the partial token under the cursor is excluded), so
#   count == 1            -> completing the top-level command word
#   count == 2, cmd[2]=model -> completing the `model` action word

function __fish_model_switch_models
    model-switch _complete models 2>/dev/null
end

function __fish_model_switch_drivers
    model-switch _complete drivers 2>/dev/null
end

function __fish_model_switch_needs_command
    set -l cmd (commandline -opc)
    test (count $cmd) -le 1
end

function __fish_model_switch_using_command
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 2; and contains -- $cmd[2] $argv
end

function __fish_model_switch_needs_action
    set -l cmd (commandline -opc)
    test (count $cmd) -eq 2; and test "$cmd[2]" = model
end

function __fish_model_switch_using_action
    set -l cmd (commandline -opc)
    test (count $cmd) -ge 3; or return 1
    test "$cmd[2]" = model; or return 1
    contains -- $cmd[3] $argv
end

# True while the model-name positional after `show|remove|use` is unfilled.
function __fish_model_switch_needs_model_name
    set -l cmd (commandline -opc)
    __fish_model_switch_using_action show remove use; or return 1
    # Completing --driver's value right now is not a model name.
    test "$cmd[-1]" = --driver; and return 1
    # Scan words after the action for an already-given positional
    # (skipping --driver's value, which is a driver name, not a positional).
    set -l skip_next 0
    for tok in $cmd[4..-1]
        if test $skip_next -eq 1
            set skip_next 0
            continue
        end
        switch $tok
            case --driver
                set skip_next 1
            case '--*'
                # valueless flag (--all-drivers, --help)
            case '*'
                return 1
        end
    end
    return 0
end

# --- top-level commands -------------------------------------------------------
complete -c model-switch -n __fish_model_switch_needs_command -f -a init -d 'Initialize the config directory'
complete -c model-switch -n __fish_model_switch_needs_command -f -a model -d 'Manage model definitions'
complete -c model-switch -n __fish_model_switch_needs_command -f -a status -d 'Show current state + effective agent config'

# --- model actions ------------------------------------------------------------
complete -c model-switch -n __fish_model_switch_needs_action -f -a add -d 'Add a new model definition'
complete -c model-switch -n __fish_model_switch_needs_action -f -a list -d 'List all configured models'
complete -c model-switch -n __fish_model_switch_needs_action -f -a show -d 'Show details of one model'
complete -c model-switch -n __fish_model_switch_needs_action -f -a remove -d 'Remove a model definition'
complete -c model-switch -n __fish_model_switch_needs_action -f -a use -d 'Activate a model'
complete -c model-switch -n __fish_model_switch_needs_action -f -a import -d 'Import models from a TOML file'

# --- model name positional (show/remove/use) ----------------------------------
complete -c model-switch -n __fish_model_switch_needs_model_name -f -a '(__fish_model_switch_models)' -d 'model'

# --- import positional (source TOML path) -------------------------------------
# -k: __fish_complete_suffix prints suffix-matching files first, keep that order.
complete -c model-switch -n '__fish_model_switch_using_action import' -ka '(__fish_complete_suffix .toml)'

# --- flags: model add ---------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action add' -l base-url -rf -d 'Upstream API base URL'
complete -c model-switch -n '__fish_model_switch_using_action add' -l api-key -rf -d 'API key (stored plaintext in models.toml)'
complete -c model-switch -n '__fish_model_switch_using_action add' -l model-name -rf -d 'Upstream model identifier'
complete -c model-switch -n '__fish_model_switch_using_action add' -l description -rf -d 'Free-text description'
complete -c model-switch -n '__fish_model_switch_using_action add' -l context-window -rf -d 'Max input tokens'
complete -c model-switch -n '__fish_model_switch_using_action add' -s h -l help -f -d 'Show help'

# --- flags: model use ---------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action use' -l driver -rf -a '(__fish_model_switch_drivers)' -d 'Target agent driver'
complete -c model-switch -n '__fish_model_switch_using_action use' -l all-drivers -f -d 'Apply to every registered driver'
complete -c model-switch -n '__fish_model_switch_using_action use' -s h -l help -f -d 'Show help'

# --- flags: model import ------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action import' -l merge -f -d 'Merge into existing models.toml'
complete -c model-switch -n '__fish_model_switch_using_action import' -s h -l help -f -d 'Show help'

# --- flags: model list / show / remove ----------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action list show remove' -s h -l help -f -d 'Show help'

# --- flags: status ------------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_command status' -l driver -rf -a '(__fish_model_switch_drivers)' -d 'Target agent driver'
complete -c model-switch -n '__fish_model_switch_using_command status' -l all-drivers -f -d 'Apply to every registered driver'
complete -c model-switch -n '__fish_model_switch_using_command status' -s h -l help -f -d 'Show help'

# --- file-completion suppression ----------------------------------------------
# Where nothing above produces candidates, don't fall back to filenames
# (e.g. after `model use <name>`, or `model add`'s free-form name positional).
# `import` is intentionally absent here: its positional IS a file path.
complete -c model-switch -n '__fish_model_switch_using_command init status' -f
complete -c model-switch -n '__fish_model_switch_using_action add list show remove use' -f
