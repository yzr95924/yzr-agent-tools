# fish completion for model-switch
#
# Dynamic model references come from the hidden `model-switch _complete
# models` plumbing command, so completion always reflects the real
# models.toml registry.
#
# scripts/model-switch.sh install symlinks this file into ~/.config/fish/completions/.
#
# Note on helpers: `commandline -opc` under completion yields only the
# *completed* tokens (the partial token under the cursor is excluded), so
#   count == 1            -> completing the top-level command word
#   count == 2, cmd[2]=model -> completing the `model` action word

function __fish_model_switch_models
    model-switch _complete models 2>/dev/null
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

# True while the model-reference positional after `show|remove|use|align` is unfilled.
function __fish_model_switch_needs_model_name
    set -l cmd (commandline -opc)
    __fish_model_switch_using_action show remove use align; or return 1
    # Completing a valued flag's argument right now is not a model reference.
    test "$cmd[-1]" = --catalog-provider; and return 1
    # Scan words after the action for an already-given positional
    # (skipping --catalog-provider's value, which is a provider id).
    # NOTE: no negative range bounds ($cmd[4..-1]) — fish 3.0+ only; on
    # fish 2.x a negative or descending range is an "Array index out of
    # bounds" error. Slice with an explicit ascending in-bounds end instead.
    set -l n (count $cmd)
    set -l skip_next 0
    if test $n -ge 4
        for tok in $cmd[4..$n]
            if test $skip_next -eq 1
                set skip_next 0
                continue
            end
            switch $tok
                case --catalog-provider
                    set skip_next 1
                case '--*'
                    # valueless flag (--help, --yes)
                case '*'
                    return 1
            end
        end
    end
    return 0
end

# --- top-level commands -------------------------------------------------------
complete -c model-switch -n __fish_model_switch_needs_command -f -a model -d 'Manage model definitions'
complete -c model-switch -n __fish_model_switch_needs_command -f -a status -d 'Show the current OpenCode state'

# --- model actions ------------------------------------------------------------
complete -c model-switch -n __fish_model_switch_needs_action -f -a add -d 'Add or replace a model'
complete -c model-switch -n __fish_model_switch_needs_action -f -a list -d 'List all configured models'
complete -c model-switch -n __fish_model_switch_needs_action -f -a show -d 'Show one model as JSON'
complete -c model-switch -n __fish_model_switch_needs_action -f -a remove -d 'Remove a model'
complete -c model-switch -n __fish_model_switch_needs_action -f -a use -d 'Activate a model'
complete -c model-switch -n __fish_model_switch_needs_action -f -a align -d 'Align model fields with the OpenCode catalog cache'

# --- model reference positional (show/remove/use/align) -----------------------
complete -c model-switch -n __fish_model_switch_needs_model_name -f -a '(__fish_model_switch_models)' -d 'model'

# --- flags: model add ---------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action add' -l api-key -r -f -d 'API key (stored plaintext in models.toml)'
complete -c model-switch -n '__fish_model_switch_using_action add' -l catalog-provider -r -f -d 'Pin the built-in provider a new yzr-* group inherits from'
complete -c model-switch -n '__fish_model_switch_using_action add' -s y -l yes -f -d 'Assume yes: skip confirmation and overwrite'
complete -c model-switch -n '__fish_model_switch_using_action add' -s h -l help -f -d 'Show help'

# --- flags: model align -------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_action align' -s h -l help -f -d 'Show help'

# --- flags: model list / show / remove / use ----------------------------------
complete -c model-switch -n '__fish_model_switch_using_action list show remove use' -s h -l help -f -d 'Show help'
complete -c model-switch -n '__fish_model_switch_using_action remove' -s y -l yes -f -d 'Skip the removal confirmation'

# --- flags: status ------------------------------------------------------------
complete -c model-switch -n '__fish_model_switch_using_command status' -s h -l help -f -d 'Show help'

# --- file-completion suppression ----------------------------------------------
# Where nothing above produces candidates, don't fall back to filenames
# (e.g. after `model use <provider/model>`, or `model add`'s reference positional).
complete -c model-switch -n '__fish_model_switch_using_command status' -f
complete -c model-switch -n '__fish_model_switch_using_action add list show remove use align' -f
