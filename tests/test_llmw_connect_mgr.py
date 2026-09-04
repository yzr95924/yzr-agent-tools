"""Tests for llmw_connect_mgr.

Every test redirects all paths via the LLMW_CONNECT_MGR_* env overrides
(paths.py seams) and injects a FakeRunner, so nothing here touches the
real ~/.cc-connect, /etc/systemd, npm, or systemctl.
"""
import os
import stat

import pytest

from llmw_connect_mgr import cli, ops, paths
from llmw_connect_mgr.runner import Result

NPM_LS_LATEST = (0, "/usr/lib\n└── @yzr95924/llmw-connect@1.5.0-llmw.4\n\n", "")
NPM_LS_OLD = (0, "/usr/lib\n└── @yzr95924/llmw-connect@1.5.0-llmw.3\n\n", "")
# Renamed binary's --version prints only the upstream baseline — no llmw
# marker, no -llmw.N suffix. Provenance is the bin NAME; version is npm ls.
NEW_BIN_VERSION = (0, "cc-connect v1.5.0\ncommit:  eb05484\n", "")


class FakeRunner(object):
    """Records every command; returns scripted results."""

    def __init__(self, which_map=None, results=None, root=True):
        self.which_map = which_map or {}
        self.results = results or {}
        self.calls = []
        self.root = root

    def run(self, argv):
        self.calls.append(list(argv))
        key = tuple(argv[:2]) if len(argv) > 1 else (argv[0],)
        r = self.results.get(key) or self.results.get(tuple(argv))
        if r is None:
            r = (0, "", "")
        rc, out, err = r
        return Result(rc, out, err, list(argv))

    def which(self, binary):
        return self.which_map.get(binary, "")

    def is_root(self):
        return self.root

    def called(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


@pytest.fixture
def isolate(monkeypatch, tmp_path):
    """Redirect every path into tmp and reset env-seam variables."""
    home = tmp_path / "home"
    data = home / ".cc-connect"
    monkeypatch.setenv(paths.HOME_OVERRIDE, str(data))
    monkeypatch.setenv(paths.SYSTEMD_DIR_OVERRIDE, str(tmp_path / "systemd"))
    monkeypatch.setenv(paths.UNIT_OVERRIDE,
                       str(tmp_path / "systemd" / "llmw-connect.service"))
    monkeypatch.setenv(paths.LOG_OVERRIDE, str(tmp_path / "daemon.log"))
    return tmp_path


# ---- env file ---------------------------------------------------------------


class TestEnvFile:
    def test_roundtrip_and_merge_preserves_unknown(self, isolate):
        p = paths.data_dir() / "env"
        p.parent.mkdir(parents=True)
        p.write_text("# comment\nTELEGRAM_BOT_TOKEN=old\nCUSTOM_KEY=keep\n", encoding="utf-8")
        changed = ops.write_env(p, {"TELEGRAM_BOT_TOKEN": "new"})
        assert changed == ["TELEGRAM_BOT_TOKEN"]
        merged = ops.read_env(p)
        assert merged == {"TELEGRAM_BOT_TOKEN": "new", "CUSTOM_KEY": "keep"}

    def test_no_change_returns_empty(self, isolate):
        p = paths.env_file()
        p.parent.mkdir(parents=True)
        ops.write_env(p, {"TELEGRAM_BOT_TOKEN": "t"})
        assert ops.write_env(p, {"TELEGRAM_BOT_TOKEN": "t"}) == []

    def test_write_is_atomic_and_0600(self, isolate):
        p = paths.env_file()
        ops.write_env(p, {"TELEGRAM_BOT_TOKEN": "t"})
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        assert not p.with_name(p.name + ".tmp").exists()

    def test_read_missing_returns_empty(self, isolate):
        assert ops.read_env(paths.env_file()) == {}


# ---- config generation --------------------------------------------------------

class TestConfig:
    def test_generate_telegram_only(self, isolate):
        ops.generate_config(paths.config_file(), with_dingtalk=False)
        text = paths.config_file().read_text(encoding="utf-8")
        assert 'token = "${TELEGRAM_BOT_TOKEN}"' in text
        assert "dingtalk" not in text
        assert "[log]" in text

    def test_generate_custom_allow_from(self, isolate):
        ops.generate_config(paths.config_file(), with_dingtalk=False,
                            allow_from="123456")
        text = paths.config_file().read_text(encoding="utf-8")
        assert 'allow_from = "123456"' in text

    def test_generate_with_dingtalk(self, isolate):
        ops.generate_config(paths.config_file(), with_dingtalk=True)
        text = paths.config_file().read_text(encoding="utf-8")
        assert 'client_id = "${DINGTALK_CLIENT_ID}"' in text
        assert 'client_secret = "${DINGTALK_CLIENT_SECRET}"' in text
        # dingtalk block must stay inside [[projects]] (before [log])
        assert text.index("[[projects.platforms]]") < text.index("dingtalk") < text.index("[log]")


# ---- unit ------------------------------------------------------------------


class TestUnit:
    def test_render_replaces_placeholders(self, isolate):
        content = ops.render_unit("/usr/bin/llmw-connect", "/root",
                                  "/root/.cc-connect/env", "/root/.cc-connect/config.toml")
        assert "ExecStart=/usr/bin/llmw-connect -config /root/.cc-connect/config.toml" in content
        assert "EnvironmentFile=/root/.cc-connect/env" in content
        assert "{" not in content.replace("{{", "")

    def test_render_defaults_config_path_from_paths(self, isolate):
        content = ops.render_unit("/usr/bin/llmw-connect", "/root", "/root/.cc-connect/env")
        assert "-config" in content

    def test_render_includes_path_env(self, isolate):
        content = ops.render_unit("/usr/bin/llmw-connect", "/root", "/e", "/c",
                                  path_env="/a:/root/.local/bin")
        assert 'Environment="PATH=/a:/root/.local/bin"' in content

    def test_render_sets_home_env(self, isolate):
        content = ops.render_unit("/usr/bin/llmw-connect", "/root", "/e", "/c")
        assert 'Environment="HOME=/root"' in content

    def test_render_explicit_home(self, isolate):
        content = ops.render_unit("/usr/bin/llmw-connect", "/root", "/e", "/c",
                                  home="/home/llmw")
        assert 'Environment="HOME=/home/llmw"' in content

    def test_service_path_merges_detected_dep_dirs(self, isolate):
        runner = FakeRunner(which_map={
            "llmw": "/root/.local/bin/llmw",
            "opencode": "/usr/local/bin/opencode",
            "tmux": "/usr/bin/tmux",
        })
        p = ops.service_path(runner)
        assert "/root/.local/bin" in p
        assert p.startswith(ops.SERVICE_PATH_DEFAULT)  # default dirs kept
        assert p.count("/usr/local/bin") == 1  # no duplicate from opencode

    def test_service_path_defaults_without_deps(self, isolate):
        assert ops.service_path(FakeRunner()) == ops.SERVICE_PATH_DEFAULT

    def test_install_restarts_when_unit_rewritten(self, isolate, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        runner = FakeRunner(
            which_map={"tmux": "/x", "opencode": "/x", "npm": "/x",
                       "systemctl": "/x", "llmw-connect": "/usr/bin/llmw-connect"},
            results={
                ("npm", "ls"): NPM_LS_LATEST,
                ("systemctl", "is-active"): (0, "active\n", ""),
                ("systemctl", "enable"): (0, "", ""),
                ("systemctl", "restart"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        import argparse
        args = argparse.Namespace(
            cmd="install", telegram_token="t", telegram_allow_from=None,
            dingtalk=False, dingtalk_id=None, dingtalk_secret=None, yes=True,
            no_systemd=False, verify_timeout=1)
        assert ops.do_install(runner, args) == 0
        assert runner.called("systemctl", "restart")
        assert runner.calls.index(["systemctl", "enable", "--now", "llmw-connect"]) < \
            runner.calls.index(["systemctl", "restart", "llmw-connect"])

    def test_install_unit_idempotent_no_reload(self, isolate, capsys):
        runner = FakeRunner()
        assert ops.install_unit(runner, "/usr/bin/llmw-connect") == "written"
        assert runner.called("systemctl", "daemon-reload")
        runner.calls.clear()
        assert ops.install_unit(runner, "/usr/bin/llmw-connect") == "unchanged"
        assert not runner.called("systemctl", "daemon-reload")

    def test_install_unit_overwrite_existing_prints_diff(self, isolate, capsys):
        unit = paths.unit_path()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text("[Unit]\nDescription=hand-written\n", encoding="utf-8")
        assert ops.install_unit(FakeRunner(), "/usr/bin/llmw-connect") == "written"
        out = capsys.readouterr().out
        assert "overwriting" in out
        assert "-Description=hand-written" in out
        assert "Description=llmw-connect daemon" in unit.read_text(encoding="utf-8")


# ---- legacy unit migration ----------------------------------------------------


class TestLegacyMigration:
    def test_migrate_removes_legacy_unit(self, isolate):
        legacy = paths.legacy_unit_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("[Unit]\nDescription=old\n", encoding="utf-8")
        runner = FakeRunner()
        assert ops.migrate_legacy_unit(runner) is True
        assert not legacy.exists()
        assert runner.called("systemctl", "disable")

    def test_migrate_noop_when_absent(self, isolate):
        runner = FakeRunner()
        assert ops.migrate_legacy_unit(runner) is False
        assert not runner.calls

    def test_install_migrates_legacy_unit(self, isolate, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        legacy = paths.legacy_unit_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("[Unit]\nDescription=old\n", encoding="utf-8")
        runner = FakeRunner(
            which_map={"tmux": "/x", "opencode": "/x", "npm": "/x",
                       "systemctl": "/x", "llmw-connect": "/usr/bin/llmw-connect"},
            results={
                ("npm", "ls"): NPM_LS_LATEST,
                ("systemctl", "enable"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        import argparse
        args = argparse.Namespace(
            cmd="install", telegram_token="t", telegram_allow_from=None,
            dingtalk=False, dingtalk_id=None, dingtalk_secret=None, yes=True,
            no_systemd=False, verify_timeout=1)
        assert ops.do_install(runner, args) == 0
        assert not legacy.exists()
        assert runner.called("systemctl", "disable")


# ---- verify -----------------------------------------------------------------


class TestVerify:
    def test_connected_marker_found(self, isolate, capsys):
        runner = FakeRunner(results={
            ("journalctl", "-u"): (0, 'msg="telegram: connected" bot=x\n', ""),
        })
        assert ops.verify_daemon(runner, timeout_s=3) is True

    def test_dingtalk_marker_found(self, isolate):
        runner = FakeRunner(results={
            ("journalctl", "-u"): (0, 'level=INFO msg="dingtalk: stream connected"\n', ""),
        })
        assert ops.verify_daemon(runner, timeout_s=3) is True

    def test_timeout_fails(self, isolate):
        runner = FakeRunner(results={("journalctl", "-u"): (0, "nothing here\n", "")})
        assert ops.verify_daemon(runner, timeout_s=1) is False


# ---- subcommand flows ---------------------------------------------------------


class TestFlows:
    def _full_which(self):
        return {
            "tmux": "/usr/bin/tmux", "opencode": "/usr/local/bin/opencode",
            "npm": "/usr/bin/npm", "systemctl": "/usr/bin/systemctl",
            "llmw-connect": "/usr/bin/llmw-connect",
        }

    def _install_args(self, **kw):
        import argparse
        base = dict(
            telegram_token="123:ABC", telegram_allow_from=None, dingtalk=False,
            dingtalk_id=None, dingtalk_secret=None, yes=True,
            no_systemd=False, verify_timeout=1,
        )
        base.update(kw)
        return argparse.Namespace(cmd="install", **base)

    def test_install_full_flow(self, isolate, monkeypatch, capsys):
        monkeypatch.setattr("time.sleep", lambda s: None)
        runner = FakeRunner(
            which_map=self._full_which(),
            results={
                ("npm", "ls"): NPM_LS_LATEST,
                ("/usr/bin/llmw-connect", "--version"): NEW_BIN_VERSION,
                ("systemctl", "enable"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        assert ops.do_install(runner, self._install_args()) == 0
        # order: unit written+reloaded before enable
        assert runner.calls.index(["systemctl", "daemon-reload"]) < \
            [i for i, c in enumerate(runner.calls) if c[:2] == ["systemctl", "enable"]][0]
        env = ops.read_env(paths.env_file())
        assert env["TELEGRAM_BOT_TOKEN"] == "123:ABC"
        assert paths.config_file().exists()

    def test_install_missing_dep_aborts(self, isolate, capsys):
        runner = FakeRunner(which_map={"npm": "/usr/bin/npm"})
        assert ops.do_install(runner, self._install_args()) == 1
        assert not runner.calls  # nothing executed

    def test_install_not_root_prints_manual(self, isolate, capsys):
        runner = FakeRunner(which_map=self._full_which(), root=False,
                            results={("npm", "ls"): NPM_LS_LATEST})
        rc = ops.do_install(runner, self._install_args())
        assert rc == 0
        assert not runner.called("systemctl", "enable")
        assert "manual steps" in capsys.readouterr().out

    def test_install_npm_installs_when_absent(self, isolate, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        which = self._full_which()
        del which["llmw-connect"]
        runner = FakeRunner(
            which_map=which,
            results={
                ("npm", "install"): (0, "added 1 package\n", ""),
                ("npm", "ls"): NPM_LS_LATEST,
                ("systemctl", "enable"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        # npm install makes the binary appear
        runner.which_map = dict(runner.which_map)
        orig_run = runner.run

        def run(argv):
            r = orig_run(argv)
            if argv[:2] == ["npm", "install"]:
                runner.which_map["llmw-connect"] = "/usr/bin/llmw-connect"
            return r

        runner.run = run
        assert ops.do_install(runner, self._install_args()) == 0
        assert runner.called("npm", "install")

    def test_upgrade_flow(self, isolate, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        runner = FakeRunner(
            which_map={"llmw-connect": "/usr/bin/llmw-connect",
                       "systemctl": "/x", "npm": "/x"},
            results={
                ("npm", "ls"): NPM_LS_OLD,
                ("npm", "view"): (1, "", "offline — fall through"),
                ("npm", "install"): (0, "", ""),
                ("systemctl", "restart"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        import argparse
        args = argparse.Namespace(cmd="upgrade", verify_timeout=1)
        assert ops.do_upgrade(runner, args) == 0
        assert runner.called("systemctl", "restart", "llmw-connect")

    def test_uninstall_keeps_data_by_default(self, isolate):
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text("x=1", encoding="utf-8")
        ops.install_unit(FakeRunner(), "/usr/bin/llmw-connect")
        import argparse
        args = argparse.Namespace(cmd="uninstall", remove_npm=False, purge=False)
        runner = FakeRunner()
        assert ops.do_uninstall(runner, args) == 0
        assert paths.config_file().exists()
        assert not paths.unit_path().exists()
        assert runner.called("systemctl", "disable", "--now", "llmw-connect")
        assert not runner.called("npm", "uninstall")

    def test_uninstall_purge(self, isolate):
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        import argparse
        args = argparse.Namespace(cmd="uninstall", remove_npm=True, purge=True)
        assert ops.do_uninstall(FakeRunner(), args) == 0
        assert not paths.data_dir().exists()


# ---- dingtalk block insert + consistency --------------------------------------


class TestConfigInsert:
    def _existing_cfg(self, with_log=True):
        cfg = paths.config_file()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "[[projects]]\n"
            "  name = \"llmw\"\n"
            "\n"
            "  [[projects.platforms]]\n"
            "    type = \"telegram\"\n"
            "\n"
        )
        if with_log:
            body += "[log]\n  level = \"info\"\n"
        cfg.write_text(body, encoding="utf-8")
        return cfg

    def test_insert_lands_before_first_top_level_table(self, isolate):
        cfg = self._existing_cfg()
        assert ops._insert_platform_block(cfg, ops.DINGTALK_BLOCK) is True
        lines = cfg.read_text(encoding="utf-8").splitlines()
        dp = next(i for i, l in enumerate(lines) if l.strip() == "[[projects]]")
        dt = next(i for i, l in enumerate(lines) if l.strip() == "type = \"dingtalk\"")
        log = next(i for i, l in enumerate(lines) if l.strip() == "[log]")
        assert dp < dt < log

    def test_insert_appends_when_no_top_level_table(self, isolate):
        cfg = self._existing_cfg(with_log=False)
        assert ops._insert_platform_block(cfg, ops.DINGTALK_BLOCK) is True
        text = cfg.read_text(encoding="utf-8")
        assert "dingtalk" in text

    def test_insert_writes_backup(self, isolate):
        cfg = self._existing_cfg()
        before = cfg.read_text(encoding="utf-8")
        ops._insert_platform_block(cfg, ops.DINGTALK_BLOCK)
        assert cfg.with_name(cfg.name + ".bak").read_text(encoding="utf-8") == before

    def test_insert_without_projects_returns_false(self, isolate):
        cfg = paths.config_file()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("[log]\nlevel=\"info\"\n", encoding="utf-8")
        assert ops._insert_platform_block(cfg, ops.DINGTALK_BLOCK) is False

    def test_do_config_yes_auto_inserts_block(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {
            "TELEGRAM_BOT_TOKEN": "t",
            "DINGTALK_CLIENT_ID": "i", "DINGTALK_CLIENT_SECRET": "s"})
        self._existing_cfg()
        rc = ops.do_config(FakeRunner(), dingtalk=True, yes=True, restart=False)
        assert rc == 0
        assert "dingtalk" in paths.config_file().read_text(encoding="utf-8")
        assert "已插入" in capsys.readouterr().out


class TestConsistency:
    def test_env_credentials_without_config_block_warns(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {
            "TELEGRAM_BOT_TOKEN": "t",
            "DINGTALK_CLIENT_ID": "i", "DINGTALK_CLIENT_SECRET": "s"})
        paths.config_file().write_text('[[projects]]\nname="x"\n', encoding="utf-8")
        rc = ops.do_config(FakeRunner(), telegram_token=None, yes=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "钉钉平台不会启动" in out

    def test_config_block_without_env_credentials_warns(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {"TELEGRAM_BOT_TOKEN": "t"})
        paths.config_file().write_text(
            '[[projects]]\n[[projects.platforms]]\ntype="dingtalk"\n', encoding="utf-8")
        rc = ops.do_config(FakeRunner(), yes=True)
        assert rc == 0
        assert "缺 DINGTALK" in capsys.readouterr().out

    def test_consistent_state_no_warning(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {"TELEGRAM_BOT_TOKEN": "t"})
        paths.config_file().write_text(
            '[[projects]]\n[[projects.platforms]]\ntype="telegram"\n[log]\n', encoding="utf-8")
        rc = ops.do_config(FakeRunner(), yes=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "warning" not in out


# ---- config auto-restart -------------------------------------------------------


class TestConfigRestart:
    def _prepared_env(self):
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {"TELEGRAM_BOT_TOKEN": "old"})
        paths.config_file().write_text(
            '[[projects]]\n[[projects.platforms]]\ntype="telegram"\n[log]\n',
            encoding="utf-8")

    def test_change_restarts_and_verifies(self, isolate, monkeypatch, capsys):
        monkeypatch.setattr("time.sleep", lambda s: None)
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared_env()
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={
                ("systemctl", "is-active"): (0, "active\n", ""),
                ("systemctl", "restart"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        rc = ops.do_config(runner, telegram_token="new", yes=True)
        assert rc == 0
        assert runner.called("systemctl", "restart")
        assert "restarted" in capsys.readouterr().out

    def test_no_change_never_touches_systemctl(self, isolate, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared_env()
        runner = FakeRunner(which_map={"systemctl": "/x"})
        rc = ops.do_config(runner, yes=True)
        assert rc == 0
        # drift check may call `systemctl show`, but nothing that mutates
        assert not runner.called("systemctl", "is-active")
        assert not runner.called("systemctl", "restart")

    def test_change_with_inactive_service_only_hints(self, isolate, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared_env()
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={("systemctl", "is-active"): (3, "inactive\n", "")},
        )
        rc = ops.do_config(runner, telegram_token="new", yes=True)
        assert rc == 0
        assert not runner.called("systemctl", "restart")
        assert "手动" in capsys.readouterr().out

    def test_change_as_non_root_only_hints(self, isolate, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared_env()
        runner = FakeRunner(
            which_map={"systemctl": "/x"}, root=False,
            results={("systemctl", "is-active"): (0, "active\n", "")},
        )
        rc = ops.do_config(runner, telegram_token="new", yes=True)
        assert rc == 0
        assert not runner.called("systemctl", "restart")

    def test_restart_failure_returns_1(self, isolate, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared_env()
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={
                ("systemctl", "is-active"): (0, "active\n", ""),
                ("systemctl", "restart"): (1, "", "unit not found"),
            },
        )
        rc = ops.do_config(runner, telegram_token="new", yes=True)
        assert rc == 1
        assert "restart failed" in capsys.readouterr().err


# ---- daemon env drift ----------------------------------------------------------

class TestEnvDrift:
    def _prepared(self):
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        ops.write_env(paths.env_file(), {"TELEGRAM_BOT_TOKEN": "new"})
        paths.config_file().write_text(
            '[[projects]]\n[[projects.platforms]]\ntype="telegram"\n[log]\n',
            encoding="utf-8")

    def test_drift_triggers_restart(self, isolate, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        monkeypatch.setattr("time.sleep", lambda s: None)
        self._prepared()
        monkeypatch.setattr(ops, "_daemon_env_drifted", lambda r, e: True)
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={
                ("systemctl", "is-active"): (0, "active\n", ""),
                ("systemctl", "restart"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        assert ops.do_config(runner, yes=True) == 0
        assert runner.called("systemctl", "restart")
        assert "不一致" in capsys.readouterr().out

    def test_no_drift_no_restart(self, isolate, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        self._prepared()
        monkeypatch.setattr(ops, "_daemon_env_drifted", lambda r, e: False)
        runner = FakeRunner(which_map={"systemctl": "/x"})
        assert ops.do_config(runner, yes=True) == 0
        assert not runner.calls

    def test_drift_detection_reads_proc_environ(self, isolate, monkeypatch):
        # systemctl show returns a fake pid; /proc/<pid>/environ is monkeypatched
        self._prepared()
        fake_pid_dir = isolate / "proc" / "123"
        fake_pid_dir.mkdir(parents=True)
        (fake_pid_dir / "environ").write_bytes(
            b"TELEGRAM_BOT_TOKEN=old\0PATH=/x\0")
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={("systemctl", "show"): (0, "123\n", "")},
        )
        # the code formats the template with a POSITIONAL pid ({0})
        monkeypatch.setattr(ops, "_PROC_ENV_TEMPLATE",
                            str(isolate / "proc" / "{0}" / "environ"))
        assert ops._daemon_env_drifted(runner, paths.env_file()) is True

    def test_drift_false_when_proc_environ_matches_file(self, isolate, monkeypatch):
        self._prepared()
        fake_pid_dir = isolate / "proc" / "123"
        fake_pid_dir.mkdir(parents=True)
        (fake_pid_dir / "environ").write_bytes(
            b"TELEGRAM_BOT_TOKEN=new\0PATH=/x\0")
        runner = FakeRunner(
            which_map={"systemctl": "/x"},
            results={("systemctl", "show"): (0, "123\n", "")},
        )
        monkeypatch.setattr(ops, "_PROC_ENV_TEMPLATE",
                            str(isolate / "proc" / "{0}" / "environ"))
        assert ops._daemon_env_drifted(runner, paths.env_file()) is False

    def test_drift_skipped_for_non_root(self, isolate):
        self._prepared()
        runner = FakeRunner(which_map={"systemctl": "/x"}, root=False)
        assert ops._daemon_env_drifted(runner, paths.env_file()) is False


# ---- provenance / version parsing / non-interactive guards ----------------------


class TestGuards:
    def _runner(self, which_map, results):
        return FakeRunner(which_map=which_map, results=results)

    def test_installed_pkg_version_parses_npm_ls(self):
        runner = FakeRunner(results={("npm", "ls"): NPM_LS_LATEST})
        assert ops._installed_pkg_version(runner) == "1.5.0-llmw.4"

    def test_installed_pkg_version_empty_when_missing(self):
        runner = FakeRunner(results={("npm", "ls"): (1, "", "empty")})
        assert ops._installed_pkg_version(runner) == ""

    def test_ensure_binary_accepts_llmw_connect_by_name(self, capsys):
        # Renamed bin: the NAME is provenance — no npm install, no marker
        # sniffing (the --version line has no llmw marker anymore).
        runner = FakeRunner(
            which_map={"llmw-connect": "/usr/bin/llmw-connect", "npm": "/x"},
            results={
                ("npm", "ls"): NPM_LS_LATEST,
                ("/usr/bin/llmw-connect", "--version"): NEW_BIN_VERSION,
            },
        )
        assert ops.ensure_binary(runner) == "/usr/bin/llmw-connect"
        assert not runner.called("npm", "install")
        assert "1.5.0-llmw.4" in capsys.readouterr().out

    def test_ensure_binary_accepts_legacy_fork(self, capsys):
        runner = FakeRunner(
            which_map={"cc-connect": "/usr/local/bin/cc-connect", "npm": "/x"},
            results={
                ("/usr/local/bin/cc-connect", "--version"):
                    (0, "cc-connect v1.5.0-llmw.2\n", ""),
            },
        )
        assert ops.ensure_binary(runner) == "/usr/local/bin/cc-connect"
        assert not runner.called("npm", "install")
        assert "legacy" in capsys.readouterr().out

    def test_ensure_binary_rejects_upstream_and_reinstalls(self, monkeypatch):
        # Legacy world: cc-connect on PATH is upstream (no llmw marker) →
        # npm install the fork → renamed llmw-connect binary appears.
        runner = FakeRunner(
            which_map={"cc-connect": "/usr/local/bin/cc-connect", "npm": "/x"},
            results={
                ("/usr/local/bin/cc-connect", "--version"): (0, "cc-connect v1.5.0\n", ""),
                ("npm", "install"): (0, "", ""),
                ("npm", "ls"): NPM_LS_LATEST,
            },
        )
        orig_run = runner.run

        def run(argv):
            r = orig_run(argv)
            if argv[:2] == ["npm", "install"]:
                runner.which_map["llmw-connect"] = "/usr/bin/llmw-connect"
            return r

        runner.run = run
        assert ops.ensure_binary(runner) == "/usr/bin/llmw-connect"
        assert runner.called("npm", "install")

    def test_ensure_binary_fails_when_still_wrong(self):
        runner = FakeRunner(
            which_map={"cc-connect": "/usr/local/bin/cc-connect", "npm": "/x"},
            results={
                ("/usr/local/bin/cc-connect", "--version"): (0, "cc-connect v1.5.0\n", ""),
                ("npm", "install"): (0, "", ""),
            },
        )
        with pytest.raises(SystemExit):
            ops.ensure_binary(runner)

    def test_config_yes_missing_token_errors(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))  # non-tty
        rc = ops.do_config(FakeRunner(), telegram_token=None, yes=True)
        assert rc == 1
        assert "TELEGRAM_BOT_TOKEN missing" in capsys.readouterr().err

    def test_config_yes_dingtalk_incomplete_errors(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        rc = ops.do_config(FakeRunner(), telegram_token="t",
                           dingtalk=True, dingtalk_id="i",
                           dingtalk_secret=None, yes=True)
        assert rc == 1
        assert "dingtalk" in capsys.readouterr().err

    def test_config_yes_with_flags_generates_allow_from(self, isolate, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", open("/dev/null"))
        rc = ops.do_config(FakeRunner(), telegram_token="t",
                           allow_from="999", yes=True, restart=False)
        assert rc == 0
        text = paths.config_file().read_text(encoding="utf-8")
        assert 'allow_from = "999"' in text

    def test_upgrade_already_latest_skips_install_and_restart(self, isolate, capsys):
        runner = FakeRunner(
            which_map={"llmw-connect": "/usr/bin/llmw-connect",
                       "systemctl": "/x", "npm": "/x"},
            results={
                ("npm", "ls"): NPM_LS_LATEST,
                ("npm", "view"): (0, "1.5.0-llmw.4\n", ""),
            },
        )
        import argparse
        args = argparse.Namespace(cmd="upgrade", verify_timeout=1)
        assert ops.do_upgrade(runner, args) == 0
        assert "already at latest" in capsys.readouterr().out
        assert not runner.called("npm", "install")
        assert not runner.called("systemctl", "restart")

    def test_upgrade_registry_unreachable_falls_through(self, isolate, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda s: None)
        runner = FakeRunner(
            which_map={"llmw-connect": "/usr/bin/llmw-connect",
                       "systemctl": "/x", "npm": "/x"},
            results={
                ("npm", "ls"): NPM_LS_OLD,
                ("npm", "view"): (1, "", "ENOTFOUND"),
                ("npm", "install"): (0, "", ""),
                ("systemctl", "restart"): (0, "", ""),
                ("journalctl", "-u"): (0, 'msg="telegram: connected"\n', ""),
            },
        )
        import argparse
        args = argparse.Namespace(cmd="upgrade", verify_timeout=1)
        assert ops.do_upgrade(runner, args) == 0
        assert runner.called("npm", "install")

    def test_upgrade_not_installed_errors(self, isolate):
        runner = FakeRunner(which_map={"npm": "/x", "systemctl": "/x"})
        import argparse
        args = argparse.Namespace(cmd="upgrade", verify_timeout=1)
        assert ops.do_upgrade(runner, args) == 1
        assert not runner.calls  # nothing executed

    def test_upgrade_rejects_legacy_upstream(self, isolate, capsys):
        runner = FakeRunner(
            which_map={"cc-connect": "/usr/local/bin/cc-connect",
                       "systemctl": "/x", "npm": "/x"},
            results={
                ("/usr/local/bin/cc-connect", "--version"): (0, "cc-connect v1.5.0\n", ""),
            },
        )
        import argparse
        args = argparse.Namespace(cmd="upgrade", verify_timeout=1)
        assert ops.do_upgrade(runner, args) == 1
        assert "not the llmw fork" in capsys.readouterr().err


# ---- CLI parsing --------------------------------------------------------------


class TestCli:
    def test_all_subcommands_parse(self):
        parser = cli.build_parser()
        for argv in (
            ["install", "--yes"],
            ["install", "--no-systemd", "--telegram-token", "t"],
            ["config", "--telegram-token", "t"],
            ["config", "--dingtalk", "--dingtalk-id", "i", "--dingtalk-secret", "s"],
            ["upgrade"],
            ["uninstall"],
            ["uninstall", "--remove-npm", "--purge"],
        ):
            parser.parse_args(argv)

    def test_unknown_command_rejected(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["frobnicate"])
