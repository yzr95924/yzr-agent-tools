"""Tests for yzr_agent_style: marker-block logic + CLI orchestration.

The autouse conftest fixture redirects all three target paths into tmp, so
these tests never touch the real global rules files.
"""
import pytest

from yzr_agent_style import cli, markers


@pytest.fixture
def yzr_paths(_isolate_yzr_state):
    """Convenience alias matching the autouse fixture's yielded dict."""
    return _isolate_yzr_state


def _read(path):
    return path.read_text(encoding="utf-8")


# --- markers: install --------------------------------------------------------

class TestInstall:
    def test_creates_new_file(self, tmp_path):
        p = tmp_path / "out" / "AGENTS.md"
        status = markers.install_block(p, "# yzr-agent-style\n")
        assert status == "created"
        assert p.exists()
        text = _read(p)
        assert "<!-- yzr-agent-style begin -->" in text
        assert "# yzr-agent-style" in text
        assert "<!-- yzr-agent-style end -->" in text

    def test_appends_when_file_has_no_marker(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("# my manual rules\nkeep me\n", encoding="utf-8")
        status = markers.install_block(p, "RULES\n")
        assert status == "appended"
        text = _read(p)
        assert text.startswith("# my manual rules\nkeep me\n")
        assert "RULES" in text

    def test_updates_existing_block_idempotently(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        markers.install_block(p, "OLD\n")
        status = markers.install_block(p, "NEW\n")
        assert status == "updated"
        text = _read(p)
        assert text.count("<!-- yzr-agent-style begin -->") == 1
        assert "OLD" not in text
        assert "NEW" in text

    def test_replaces_block_and_preserves_surrounding_content(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("before\n", encoding="utf-8")
        markers.install_block(p, "A\n")
        markers.install_block(p, "B\n")
        text = _read(p)
        assert text.startswith("before\n")
        assert "B" in text
        assert "A" not in text

    def test_cleans_up_truncated_block(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        p.write_text(
            "keep\n<!-- yzr-agent-style begin -->\nstale\n", encoding="utf-8"
        )
        status = markers.install_block(p, "FRESH\n")
        assert status == "updated"
        text = _read(p)
        assert text.startswith("keep\n")
        assert "stale" not in text
        assert "FRESH" in text
        assert "<!-- yzr-agent-style end -->" in text


# --- markers: uninstall ------------------------------------------------------

class TestUninstall:
    def test_strips_block_keeps_user_content(self, tmp_path):
        p = tmp_path / "CLAUDE.md"
        p.write_text("manual\n", encoding="utf-8")
        markers.install_block(p, "managed\n")
        status = markers.remove_block(p)
        assert status == "stripped"
        assert _read(p) == "manual\n"

    def test_removes_file_when_only_block_remains(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        markers.install_block(p, "x\n")
        status = markers.remove_block(p)
        assert status == "removed-file"
        assert not p.exists()

    def test_leaves_file_without_marker_untouched(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        p.write_text("mine\n", encoding="utf-8")
        status = markers.remove_block(p)
        assert status == "untouched"
        assert _read(p) == "mine\n"

    def test_absent_file(self, tmp_path):
        assert markers.remove_block(tmp_path / "nope.md") == "absent"


# --- CLI ---------------------------------------------------------------------

class TestCli:
    def test_install_creates_all_three(self, tmp_path, yzr_paths):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".config" / "opencode").mkdir(parents=True)
        (tmp_path / ".qoder").mkdir()

        rc = cli.main(["install"])
        assert rc == 0
        assert yzr_paths["claude_md"].exists()
        assert yzr_paths["opencode_agents"].exists()
        assert yzr_paths["qoder_agents"].exists()
        for target in yzr_paths["claude_md"], yzr_paths["opencode_agents"], yzr_paths["qoder_agents"]:
            assert "<!-- yzr-agent-style begin -->" in _read(target)

    def test_install_skips_missing_parent(self, tmp_path, capsys):
        rc = cli.main(["install"])
        assert rc == 0
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / ".config" / "opencode").exists()
        assert not (tmp_path / ".qoder").exists()
        out = capsys.readouterr().out
        assert sum(1 for line in out.splitlines() if line.startswith("skip ")) == 3

    def test_install_is_idempotent(self, tmp_path, yzr_paths):
        (tmp_path / ".claude").mkdir()
        rc = cli.main(["install"])
        assert rc == 0
        rc = cli.main(["install"])
        assert rc == 0
        assert _read(yzr_paths["claude_md"]).count("<!-- yzr-agent-style begin -->") == 1

    def test_uninstall_removes_managed_files(self, tmp_path, yzr_paths):
        (tmp_path / ".claude").mkdir()
        cli.main(["install"])
        rc = cli.main(["uninstall"])
        assert rc == 0
        assert not yzr_paths["claude_md"].exists()

    def test_uninstall_keeps_unmanaged_files(self, tmp_path, yzr_paths):
        (tmp_path / ".claude").mkdir()
        yzr_paths["claude_md"].write_text("mine\n", encoding="utf-8")
        rc = cli.main(["uninstall"])
        assert rc == 0
        assert _read(yzr_paths["claude_md"]) == "mine\n"

    def test_unknown_command_exits_2(self):
        with pytest.raises(SystemExit) as exc:
            cli.main(["bogus"])
        assert exc.value.code == 2