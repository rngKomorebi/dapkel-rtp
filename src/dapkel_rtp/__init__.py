"""dapkel-rtp — real-time acquisition and preview for the Kelpie v2 SPAD camera."""

# THE version for this package. CHANGELOG.md is the source of truth for what it
# should be — the newest numbered section there is the current version — and this
# literal must match it. 'tools/check_version.py' enforces that, and CI fails the
# build when they drift.
#
# Declared here rather than in pyproject.toml because pyproject reads it *from*
# here (dynamic version), so there is one place to change, and because the app
# ships as a PyInstaller onefile bundle where importlib.metadata cannot resolve
# an installed distribution.
__version__ = "0.1.0"
