import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_changelog():
    # The same gate the release build runs, so a drift fails on every push
    # rather than only when main is built.
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_version.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_requirements_match_pyproject():
    # The exe is built from requirements.txt, a pip install from pyproject.toml.
    # Two lists of the same three dependencies drift unless something checks.
    tomllib = pytest.importorskip("tomllib")  # stdlib from 3.11
    with open(ROOT / "pyproject.toml", "rb") as fh:
        declared = tomllib.load(fh)["project"]["dependencies"]

    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    required = [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]

    assert sorted(required) == sorted(declared)
