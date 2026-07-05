"""Resolve resource paths for source-tree and PyInstaller onefile bundle.

When packed with ``pyinstaller --onefile``, bundled data files are extracted
to ``sys._MEIPASS`` at runtime.  All path helpers here handle both cases.
"""

import os
import sys


def _base() -> str:
    """Root of the dapkel package, regardless of execution context."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile — files extracted to sys._MEIPASS
        return os.path.join(sys._MEIPASS, "dapkel")  # type: ignore[attr-defined]
    # Source tree: this file is at  dapkel/gui/gui/_paths.py
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "../.."))


def functions_dir() -> str:
    """dapkel/functions/helpers/ — Kelpie_v2.exe and related binaries live here."""
    return os.path.join(_base(), "functions", "helpers")


def programs_dir() -> str:
    """dapkel/params/camera/programs/ — program_*.txt FPGA configuration files."""
    return os.path.join(_base(), "params", "camera", "programs")


def bitfile_dir() -> str:
    """dapkel/params/camera/bitfile/ — FPGA bitfile (.bit)."""
    return os.path.join(_base(), "params", "camera", "bitfile")


def params_camera_dir() -> str:
    """dapkel/params/camera/ — cwd for Kelpie_v2_pwr_mgt.exe.

    The exe opens './bitfile/Kelpie_top.bit' relative to its working directory,
    so it must be launched from this directory.
    """
    return os.path.join(_base(), "params", "camera")
