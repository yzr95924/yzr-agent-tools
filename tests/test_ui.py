"""Tests for the interactive prompt helpers (`model_switch.ui`)."""
import io
import sys

import pytest

from model_switch import ui


def _stdin(monkeypatch, text, tty=True):
    fake = io.StringIO(text)
    fake.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", fake)


def test_ask_reads_one_line(monkeypatch):
    _stdin(monkeypatch, "hello\n")
    assert ui.ask("> ") == "hello"


def test_ask_eof_aborts(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.ask("> ")
    assert "input exhausted" in capsys.readouterr().err


def test_pick_one_returns_zero_based_index(monkeypatch, capsys):
    _stdin(monkeypatch, "2\n")
    assert ui.pick_one("Models:", ["a", "b", "c"]) == 1
    assert "1) a" in capsys.readouterr().out


def test_pick_one_reprompts_on_garbage(monkeypatch, capsys):
    _stdin(monkeypatch, "x\n9\n2\n")
    assert ui.pick_one("Models:", ["a", "b"]) == 1
    assert capsys.readouterr().out.count("Enter a number") == 2


def test_pick_one_empty_list_fails(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", [])
    assert "nothing to pick" in capsys.readouterr().err


def test_pick_one_eof_aborts(monkeypatch, capsys):
    _stdin(monkeypatch, "")
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", ["a"])
    assert "input exhausted" in capsys.readouterr().err


def test_pick_one_non_tty_fails(monkeypatch, capsys):
    _stdin(monkeypatch, "1\n", tty=False)
    with pytest.raises(SystemExit):
        ui.pick_one("Models:", ["a"])
    assert "needs a TTY" in capsys.readouterr().err


def test_confirm_accepts_yes_and_no_and_default(monkeypatch):
    _stdin(monkeypatch, "y\n")
    assert ui.confirm("Ok?") is True
    _stdin(monkeypatch, "no\n")
    assert ui.confirm("Ok?") is False
    _stdin(monkeypatch, "\n")
    assert ui.confirm("Ok?", default=False) is False


def test_confirm_reprompts_on_garbage(monkeypatch, capsys):
    _stdin(monkeypatch, "maybe\nY\n")
    assert ui.confirm("Ok?") is True
    assert "answer 'y' or 'n'" in capsys.readouterr().out


def test_confirm_non_tty_fails(monkeypatch, capsys):
    _stdin(monkeypatch, "", tty=False)
    with pytest.raises(SystemExit):
        ui.confirm("Ok?", default=False)
    assert "needs a TTY" in capsys.readouterr().err
