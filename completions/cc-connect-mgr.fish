# fish completion for cc-connect-mgr
#
# Static command surface: install / config / upgrade / uninstall.
# scripts/cc-connect-mgr.sh install symlinks this file into
# ~/.config/fish/completions/.

complete -c cc-connect-mgr -f
complete -c cc-connect-mgr -n '__fish_use_subcommand' -a install -d 'first-time install: binary + credentials + systemd'
complete -c cc-connect-mgr -n '__fish_use_subcommand' -a config -d 'manage credentials (env) + generate config.toml if absent'
complete -c cc-connect-mgr -n '__fish_use_subcommand' -a upgrade -d 'npm install @latest + systemctl restart + verify'
complete -c cc-connect-mgr -n '__fish_use_subcommand' -a uninstall -d 'stop + remove unit; data kept unless --purge'

complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l telegram-token -d 'Telegram bot token (omit to prompt)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l telegram-allow-from -d 'telegram allow_from when generating config.toml (default * = anyone)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l dingtalk -d 'configure DingTalk credentials as well'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l telegram-allow-from -d 'telegram allow_from when generating config.toml (default * = anyone)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l dingtalk-id -d 'DingTalk client_id (AppKey)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l telegram-allow-from -d 'telegram allow_from when generating config.toml (default * = anyone)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l dingtalk-secret -d 'DingTalk client_secret (AppSecret)'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install config' -l yes -s y -d 'non-interactive'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install' -l no-systemd -d 'skip systemctl; print unit + manual steps'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from install upgrade config' -l verify-timeout -d 'seconds to wait for connected log'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from config' -l no-restart -d 'do not restart daemon after changes' -d 'seconds to wait for connected log'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from uninstall' -l remove-npm -d 'also npm uninstall -g'
complete -c cc-connect-mgr -n '__fish_seen_subcommand_from uninstall' -l purge -d 'delete ~/.cc-connect (irreversible)'
