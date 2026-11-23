"""A fake macOS + Homebrew machine for the install scripts' tests.

Each ``scripts/<tool>.sh`` links its bash completion into
``$(brew --prefix)/share/bash-completion/completions`` when ``uname`` reports
Darwin and ``brew`` is on PATH. On a real Mac that is the user's own
directory, so the stubs here answer both probes with paths under ``tmp_path``:
the branch runs on every platform and writes nowhere real.
"""
import os
from pathlib import Path


def fake_homebrew(tmp_path: Path, env: dict) -> None:
    """Put stub ``uname`` (Darwin) and ``brew`` ahead of ``env``'s PATH.

    ``brew`` prints a prefix under ``tmp_path``. The scripts link into it only
    when that directory exists, so it is created here.
    """
    stubs = tmp_path / "stubs"
    prefix = _prefix(tmp_path)
    stubs.mkdir()
    prefix.mkdir()
    (stubs / "uname").write_text("#!/bin/sh\necho Darwin\n")
    (stubs / "brew").write_text(
        "#!/bin/sh\nprintf '%s\\n' \"{}\"\n".format(prefix))
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    env["PATH"] = str(stubs) + os.pathsep + env["PATH"]
    env["HOMEBREW_PREFIX"] = str(prefix)


def bash_completion_link(tmp_path: Path, tool: str) -> Path:
    """Where a script links ``tool``'s bash completion under `fake_homebrew`."""
    return (_prefix(tmp_path) / "share" / "bash-completion" / "completions"
            / tool)


def drop_brew_from_path(env: dict) -> None:
    """Remove every PATH entry that holds a ``brew``, the stub included."""
    env["PATH"] = os.pathsep.join(
        entry for entry in env["PATH"].split(os.pathsep)
        if not os.path.exists(os.path.join(entry, "brew")))


def _prefix(tmp_path: Path) -> Path:
    return tmp_path / "homebrew"
