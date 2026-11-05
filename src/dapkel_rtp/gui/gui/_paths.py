"""Resolve resource paths for source-tree and PyInstaller onefile bundle.

When packed with ``pyinstaller --onefile``, bundled data files are extracted
to ``sys._MEIPASS`` at runtime.  All path helpers here handle both cases.
"""

import os
import shutil
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


def user_data_dir() -> str:
    """Per-user folder for what the user adds: masks, custom firmware.

    ``%LOCALAPPDATA%\\DAPKEL\\dapkel-rtp`` on Windows (the same DAPKEL /
    dapkel-rtp names the theme's QSettings key uses), ``~/.local/share/DAPKEL/
    dapkel-rtp`` elsewhere. Not beside the exe: people keep the exe on the
    desktop, and a folder appearing next to it there is clutter -- and a newer
    exe downloaded to another folder would start with none of it. Not inside
    the package either: a frozen exe unpacks itself to a temporary folder that
    is deleted on exit. The exe and a run from source share this folder.
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "DAPKEL", "dapkel-rtp")


# Written into the masks folder once the old mask folders have been copied in,
# so a mask deleted from the new folder by hand does not come back next start.
_MASKS_MIGRATED = ".migrated"


def legacy_masks_dirs() -> list[str]:
    """Where masks were saved before they moved to 'user_data_dir'.

    A 'masks' folder beside the exe when frozen; dapkel_rtp/params/masks/ when
    run from source.
    """
    if getattr(sys, "frozen", False):
        return [os.path.join(os.path.dirname(sys.executable), "masks")]
    return [os.path.join(_base(), "params", "masks")]


def _migrate_masks(folder: str) -> None:
    """Copy masks from the old folders, once, never over a newer file.

    The old files are left where they are. Failing to copy must not stop the
    app, so errors are swallowed; the marker is then not written and the copy
    is tried again next start.
    """
    marker = os.path.join(folder, _MASKS_MIGRATED)
    if os.path.exists(marker):
        return
    try:
        os.makedirs(folder, exist_ok=True)
        for old in legacy_masks_dirs():
            if not os.path.isdir(old):
                continue
            for name in os.listdir(old):
                src = os.path.join(old, name)
                dst = os.path.join(folder, name)
                if (
                    name.lower().endswith(".json")
                    and os.path.isfile(src)
                    and not os.path.exists(dst)
                ):
                    shutil.copy2(src, dst)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("Masks from the old folders were copied here once.\n")
    except OSError:
        pass


def masks_dir() -> str:
    """Where saved pixel masks are written and read: <user_data_dir>/masks.

    The first call copies in any masks saved in the old places (see
    'legacy_masks_dirs'), so moving the folder loses nothing.
    """
    folder = os.path.join(user_data_dir(), "masks")
    _migrate_masks(folder)
    return folder


def custom_firmware_dir() -> str:
    """Where firmware added from Firmware ▸ "Add custom firmware…" is kept.

    <user_data_dir>/firmware -- see 'user_data_dir' for why there. An added
    bitstream belongs to this user, not to the repo or the release, and the
    shipped short_exposure / long_exposure bitstreams are never touched.
    """
    return os.path.join(user_data_dir(), "firmware")


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
