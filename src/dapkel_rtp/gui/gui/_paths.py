"""Resolve resource paths for source-tree and PyInstaller onefile bundle.

When packed with ``pyinstaller --onefile``, bundled data files are extracted
to ``sys._MEIPASS`` at runtime.  All path helpers here handle both cases.
"""

import os
import sys

# Re-exported so the GUI has one import for the firmware vocabulary. Defined in
# functions.timing, which pulls in nothing heavy.
from dapkel_rtp.functions.timing import (  # noqa: F401
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    FIRMWARE_VERSIONS,
)


def _base() -> str:
    """Root of the dapkel_rtp package, regardless of execution context."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile — files extracted to sys._MEIPASS
        return os.path.join(sys._MEIPASS, "dapkel_rtp")  # type: ignore[attr-defined]
    # Source tree: this file is at  dapkel_rtp/gui/gui/_paths.py
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "../.."))


def functions_dir() -> str:
    """dapkel_rtp/functions/helpers/ — Kelpie_v2.exe and related binaries live here."""
    return os.path.join(_base(), "functions", "helpers")


def programs_dir() -> str:
    """dapkel_rtp/params/camera/programs/ — program_*.txt FPGA configuration files."""
    return os.path.join(_base(), "params", "camera", "programs")


def bitfile_dir() -> str:
    """dapkel_rtp/params/camera/bitfile/ — legacy single-firmware bitfile."""
    return os.path.join(_base(), "params", "camera", "bitfile")


def params_camera_dir() -> str:
    """dapkel_rtp/params/camera/ — legacy cwd for Kelpie_v2_pwr_mgt.exe.

    The exe opens './bitfile/Kelpie_top.bit' relative to its working directory,
    so it must be launched from this directory. Prefer 'resolve_pwr_mgt_cwd',
    which picks the folder for a chosen firmware version and falls back here.
    """
    return os.path.join(_base(), "params", "camera")


# ---------------------------------------------------------------------------
# Firmware versions
# ---------------------------------------------------------------------------
#
# Kelpie_v2_pwr_mgt.exe takes no bitstream argument: it opens the hardcoded
# relative path './bitfile/Kelpie_top.bit' from its working directory. So the
# only way to choose between firmware builds is to launch it from a different
# directory — one per version, each with its own 'bitfile/Kelpie_top.bit'.
# Nothing is copied or overwritten, and both bitstreams stay inspectable.
#
# Named as in dapkel.core.timing.resolve_cycle_time, deliberately: the two
# repos must not grow a second vocabulary for the same two modes.

BITFILE_NAME = "Kelpie_top.bit"


def firmware_dir(firmware: str) -> str:
    """dapkel_rtp/params/camera/<firmware>/ — cwd for that firmware's pwr_mgt."""
    return os.path.join(_base(), "params", "camera", firmware)


def firmware_bitfile(firmware: str) -> str | None:
    """Return that firmware's '.bit' path, or None when it is not placed yet."""
    path = os.path.join(firmware_dir(firmware), "bitfile", BITFILE_NAME)
    return path if os.path.isfile(path) else None


def available_firmwares() -> list[str]:
    """Firmware versions whose bitfile is actually present."""
    return [f for f in FIRMWARE_VERSIONS if firmware_bitfile(f) is not None]


def resolve_pwr_mgt_cwd(firmware: str | None) -> tuple[str, str | None]:
    """Return the working directory to run Kelpie_v2_pwr_mgt.exe from.

    Falls back to the legacy 'params/camera/' when the requested firmware has
    no bitfile placed there, so the app keeps working exactly as before until
    both versions are in place. The returned bitfile path is None when nothing
    was found at all, which the caller should report rather than let the exe
    fail on a missing relative path.

    Parameters
    ----------
    firmware : str | None
        A member of 'FIRMWARE_VERSIONS', or None to use the legacy folder.

    Returns
    -------
    tuple[str, str | None]
        The working directory, and the '.bit' that will be loaded from it.
    """
    if firmware:
        found = firmware_bitfile(firmware)
        if found is not None:
            return firmware_dir(firmware), found

    legacy = params_camera_dir()
    legacy_bit = os.path.join(legacy, "bitfile", BITFILE_NAME)
    return legacy, (legacy_bit if os.path.isfile(legacy_bit) else None)
