"""Fail if the package version and CHANGELOG.md disagree.

CHANGELOG.md is the source of truth: its newest numbered section is the current
version, and that is what the app reports, what the release is tagged with, and
what a `pip install` records. Nothing else may state a version independently.

This exists because they drifted. ``pyproject.toml`` was never bumped past 0.0.1
while the CHANGELOG went to 0.1.0, and the release workflow tagged builds
``build-<n>-<sha>`` so the version never appeared anywhere a human would look.
Two versions passed unnoticed.

Run it directly, or as a CI step before the build:

    python tools/check_version.py

Exits 0 when consistent, 1 with an explanation when not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# '## [1.2.3] - 2026-08-02'. Only numbered sections count -- '## [Unreleased]'
# is deliberately skipped, so work in progress does not claim to be a release.
_RELEASE_RE = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]\s*-\s*(\S+)", re.MULTILINE)
_ANY_SECTION_RE = re.compile(r"^##\s*\[([^\]]+)\]", re.MULTILINE)


def changelog_version(path: Path) -> tuple[str, str]:
    """Return (version, date) of the newest numbered CHANGELOG section."""
    text = path.read_text(encoding="utf-8")
    match = _RELEASE_RE.search(text)
    if match is None:
        sections = _ANY_SECTION_RE.findall(text)
        raise SystemExit(
            f"No numbered release section in {path.name}. Sections found: "
            f"{sections or 'none'}. A release heading looks like "
            "'## [0.2.0] - 2026-08-04'."
        )
    return match.group(1), match.group(2)


def package_version() -> str:
    """Return dapkel_rtp.__version__ without importing the whole package.

    Read as text rather than imported so this runs before dependencies are
    installed and cannot be affected by an import side effect.
    """
    init = ROOT / "src" / "dapkel_rtp" / "__init__.py"
    match = re.search(
        r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", init.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise SystemExit(f"No __version__ assignment found in {init}.")
    return match.group(1)


def unreleased_body(path: Path) -> bool:
    """Whether CHANGELOG has an '[Unreleased]' section with content in it."""
    text = path.read_text(encoding="utf-8")
    start = re.search(r"^##\s*\[Unreleased\]", text, re.MULTILINE)
    if start is None:
        return False
    rest = text[start.end():]
    end = _RELEASE_RE.search(rest)
    body = rest[: end.start()] if end else rest
    return bool(body.strip())


def main() -> int:
    changelog = ROOT / "CHANGELOG.md"
    want, date = changelog_version(changelog)
    have = package_version()

    if have != want:
        print(
            f"VERSION MISMATCH\n"
            f"  CHANGELOG.md newest release : {want}  ({date})\n"
            f"  dapkel_rtp.__version__      : {have}\n\n"
            f"CHANGELOG.md is the source of truth. Either bump __version__ to "
            f"{want}, or add the '## [{have}] - <date>' section that releases it.\n"
            f"pyproject.toml reads __version__, so it needs no separate edit.",
            file=sys.stderr,
        )
        return 1

    note = ""
    if unreleased_body(changelog):
        # Not a failure: work in progress legitimately sits above the last
        # release. Worth saying, because the exe built from it will report the
        # previous version until that section is given a number.
        note = (
            f"\n  note: CHANGELOG has an [Unreleased] section with content, so a "
            f"build from this tree reports {have} while containing changes not in "
            f"the {have} release. Give it a number before releasing."
        )

    print(f"version OK: {have} (CHANGELOG {want}, {date}){note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
