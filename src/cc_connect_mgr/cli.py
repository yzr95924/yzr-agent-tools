"""argparse-based CLI for cc-connect-mgr.

Four commands, all idempotent:

  install    deps check → npm-install binary if absent → config →
             systemd unit → enable --now → verify "connected"
  config     manage credentials/env + generate config.toml when absent
  upgrade    npm install @latest → systemctl restart → verify
  uninstall  disable service, remove unit (data kept; --purge deletes)

Exit codes: 0 = success; 1 = user/env error; 2 = argparse error.

The production daemon runs the npm-published artifact (@yzr95924/llmw-connect)
under systemd; rc-dev builds are run manually outside the unit and are
deliberately NOT managed here.
"""
import argparse
import sys
from typing import List, Optional

from cc_connect_mgr import ops
from cc_connect_mgr.runner import Runner


def build_parser() -> argparse.ArgumentParser:
    from cc_connect_mgr import __version__
    parser = argparse.ArgumentParser(
        prog="cc-connect-mgr",
        description=(
            "Install / configure / upgrade / uninstall the cc-connect "
            "daemon (llmw fork) on this host."
        ),
    )
    parser.add_argument("--version", action="version",
                        version="%(prog)s {0}".format(__version__))
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    def add_config_flags(p, *, with_yes=True):
        p.add_argument("--telegram-token", default=None,
                       help="Telegram bot token (omit to prompt; existing kept otherwise)")
        p.add_argument("--telegram-allow-from", default=None, metavar="ID",
                       help="telegram allow_from when generating config.toml "
                            "(default \"*\" = anyone — lock to your TG user id)")
        p.add_argument("--dingtalk", action="store_true",
                       help="configure DingTalk credentials as well")
        p.add_argument("--dingtalk-id", default=None, help="DingTalk client_id (AppKey)")
        p.add_argument("--dingtalk-secret", default=None, help="DingTalk client_secret (AppSecret)")
        if with_yes:
            p.add_argument("--yes", "-y", action="store_true",
                           help="non-interactive: take defaults, never prompt")

    p_install = sub.add_parser(
        "install", help="first-time install: binary + credentials + systemd")
    add_config_flags(p_install)
    p_install.add_argument("--no-systemd", action="store_true",
                           help="skip systemctl actions; print the unit + manual steps")
    p_install.add_argument("--verify-timeout", type=int, default=20,
                           help="seconds to wait for the daemon 'connected' log (default 20)")

    p_config = sub.add_parser(
        "config", help="manage credentials (env) + generate config.toml if absent")
    add_config_flags(p_config)
    p_config.add_argument("--no-restart", action="store_true",
                          help="do not restart the daemon after changes "
                               "(default: restart + verify when changed and running)")
    p_config.add_argument("--verify-timeout", type=int, default=20,
                          help="seconds to wait for the daemon 'connected' log after restart (default 20)")

    p_upgrade = sub.add_parser(
        "upgrade", help="npm install @latest + systemctl restart + verify")
    p_upgrade.add_argument("--verify-timeout", type=int, default=20,
                           help="seconds to wait for the daemon 'connected' log (default 20)")

    p_uninstall = sub.add_parser(
        "uninstall", help="stop + remove unit; data kept unless --purge")
    p_uninstall.add_argument("--remove-npm", action="store_true",
                             help="also npm uninstall -g the package")
    p_uninstall.add_argument("--purge", action="store_true",
                             help="delete ~/.cc-connect (config, env, sessions) — irreversible")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = Runner()
    if args.cmd == "install":
        return ops.do_install(runner, args)
    if args.cmd == "config":
        return ops.do_config(
            runner,
            telegram_token=args.telegram_token,
            dingtalk=args.dingtalk,
            dingtalk_id=args.dingtalk_id,
            dingtalk_secret=args.dingtalk_secret,
            yes=args.yes,
            allow_from=args.telegram_allow_from,
            restart=not args.no_restart,
            verify_timeout=args.verify_timeout,
        )
    if args.cmd == "upgrade":
        return ops.do_upgrade(runner, args)
    if args.cmd == "uninstall":
        return ops.do_uninstall(runner, args)
    parser.error("unknown command: {0}".format(args.cmd))  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
