"""Tests for the numbered-menu / confirmation helpers (`model_switch.ui`)."""
import io
import sys

import pytest

from model_switch import ui


def _stdin(monkeypatch, text, tty=True):
    """Point sys.stdin at scripted input; pretend it is (or is not) a TTY."""
    fake = io.StringIO(text)
    fake.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", fake)
    return fake


# --- ask -----------------------------------------------------------------------

def test_ask_reads_one_line(monkeypatch):
    _stdin(monkeypatch, "hello\n")
    assert ui.ask("> ") == "hello"


def test_ask_eof_aborts(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.ask("> ")
    assert "input exhausted" in capsys.readouterr().err


# --- pick_one ------------------------------------------------------------------

def test_pick_one_returns_zero_based_index(monkeypatch, capsys):
    _stdin(monkeypatch, "2\n")
    assert ui.pick_one("Models:", ["a", "b", "c"], str) == 1
    out = capsys.readouterr().out
    assert "1) a" in out and "3) c" in out


def test_pick_one_enter_takes_the_default(monkeypatch):
    _stdin(monkeypatch, "\n")
    assert ui.pick_one("Models:", ["a", "b"], str, default=1) == 1


def test_pick_one_reprompts_on_garbage_and_out_of_range(monkeypatch, capsys):
    _stdin(monkeypatch, "x\n9\n0\n2\n")
    assert ui.pick_one("Models:", ["a", "b"], str) == 1
    assert capsys.readouterr().out.count("Enter a number") == 3


def test_pick_one_back_returns_none(monkeypatch):
    _stdin(monkeypatch, "b\n")
    assert ui.pick_one("Models:", ["a"], str, allow_back=True) is None


def test_pick_one_prompt_shows_default_and_back_hint(monkeypatch, capsys):
    _stdin(monkeypatch, "1\n")
    ui.pick_one("Models:", ["a"], str, default=0, allow_back=True)
    assert "Pick a number [1] ('b' = back)" in capsys.readouterr().out


def test_pick_one_truncates_with_a_hint(monkeypatch, capsys):
    _stdin(monkeypatch, "1\n")
    items = [str(i) for i in range(ui.MENU_MAX + 3)]
    assert ui.pick_one("Many:", items, str) == 0
    assert "3 more" in capsys.readouterr().out


def test_pick_one_rejects_hidden_rows(monkeypatch, capsys):
    _stdin(monkeypatch, "{}\n1\n".format(ui.MENU_MAX + 1))
    items = [str(i) for i in range(ui.MENU_MAX + 3)]
    assert ui.pick_one("Many:", items, str) == 0
    out = capsys.readouterr().out
    assert "Enter a number between 1 and {}".format(ui.MENU_MAX) in out
    assert "hidden row(s), narrow the search" in out


def test_pick_one_rejects_an_out_of_range_default(monkeypatch, capsys):
    """A default must land on a shown row — otherwise Enter returns an index
    the caller cannot map back."""
    _stdin(monkeypatch, "\n")
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", ["a"], str, default=5)
    assert "default index 5" in capsys.readouterr().err


def test_pick_one_empty_list_fails(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", [], str)
    assert "nothing to pick" in capsys.readouterr().err


def test_pick_one_eof_aborts(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", ["a"], str)
    assert "input exhausted" in capsys.readouterr().err


def test_pick_one_non_tty_fails(monkeypatch, capsys):
    _stdin(monkeypatch, "1\n", tty=False)
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", ["a"], str)
    assert "needs a TTY" in capsys.readouterr().err


# --- confirm -------------------------------------------------------------------

def test_confirm_accepts_yes_and_no(monkeypatch):
    _stdin(monkeypatch, "y\n")
    assert ui.confirm("Ok?") is True
    _stdin(monkeypatch, "no\n")
    assert ui.confirm("Ok?") is False


def test_confirm_enter_takes_the_default(monkeypatch):
    _stdin(monkeypatch, "\n")
    assert ui.confirm("Ok?", default=True) is True
    _stdin(monkeypatch, "\n")
    assert ui.confirm("Ok?", default=False) is False


def test_confirm_prompt_shows_the_default(monkeypatch, capsys):
    _stdin(monkeypatch, "y\n")
    ui.confirm("Ok?", default=False)
    assert "Ok? [y/N]" in capsys.readouterr().out


def test_confirm_reprompts_on_garbage(monkeypatch, capsys):
    _stdin(monkeypatch, "maybe\nY\n")
    assert ui.confirm("Ok?") is True
    assert "answer 'y' or 'n'" in capsys.readouterr().out


def test_confirm_non_tty_fails(monkeypatch, capsys):
    """A confirmation is never answered silently on the user's behalf."""
    _stdin(monkeypatch, "", tty=False)
    with pytest.raises(SystemExit):
        ui.confirm("Ok?", default=False)
    assert "needs a TTY" in capsys.readouterr().err
