"""Seam for every external command the CLI crosses.

The real Runner shells out via subprocess; tests inject fakes so pytest
never runs systemctl / npm / journalctl for real (repo invariant: tests
must not touch machine state outside tmp paths).
"""
import os
import shutil
import subprocess
from typing import List


class Result(object):
    """One command invocation's outcome. rc!=0 never raises."""

    def __init__(self, rc: int, out: str, err: str, argv: List[str]) -> None:
        self.rc = rc
        self.out = out
        self.err = err
        self.argv = argv

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Result(rc={0}, argv={1!r})".format(self.rc, self.argv)


class Runner(object):
    """Executes argv lists, capturing stdout/stderr."""

    def run(self, argv: List[str]) -> Result:
        p = subprocess.run(argv, capture_output=True, text=True)
        return Result(p.returncode, p.stdout, p.stderr, argv)

    def which(self, binary: str) -> str:
        return shutil.which(binary) or ""

    def is_root(self) -> bool:
        return os.geteuid() == 0
