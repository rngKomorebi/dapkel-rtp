"""Self-test for the built exe: does what ships actually start?

The test suite runs the source tree, which always has every file. The release
is a PyInstaller onefile bundle, which has only what 'main.spec' lists, and
nothing ever started it before it was published. A data file missing from
the spec, or a module PyInstaller failed to see, only showed up on a user's PC.

Set ``DAPKEL_RTP_SMOKE_TEST`` to a file path and start the exe: instead of
waiting for the user it builds the main window, checks that the files the
acquisitions need were bundled, quits on its own, writes what it found to that
path and exits 0 only if nothing is wrong. The release workflow does exactly
that before publishing. The report file exists because the windowed exe has
no stdout to print to.

This file can also be imported as a module and contains the following
functions:

    * bundle_problems - files the acquisitions need that are not there.

    * run_smoke_test - build the window, quit, report; returns the exit code.
"""

from __future__ import annotations

import glob
import os
import sys
import traceback
from collections.abc import Callable

from dapkel_rtp.gui.app_icon import ICON_SIZES, icon_file
from dapkel_rtp.gui.gui._paths import (
    FIRMWARE_VERSIONS,
    available_firmwares,
    functions_dir,
    programs_dir,
    resolve_pwr_mgt_cwd,
)

ENV_VAR = "DAPKEL_RTP_SMOKE_TEST"

# Every vendor binary main.spec bundles. Kelpie_v2*.exe are what the app runs;
# the two DLLs are what those load from their own folder.
HELPER_FILES = (
    "Kelpie_v2.exe",
    "Kelpie_v2_pwr_mgt.exe",
    "okFrontPanel.dll",
    "okimpl_fpoip.dll",
)

# The programs the tabs select by default (ORT for acquisition, ORC for the
# live view, S0C..S3C for its 64x64 mode). The rest are checked as a count.
DEFAULT_PROGRAMS = ("ORT", "ORC", "S0C", "S1C", "S2C", "S3C")

# How long the window is left to run before the test quits it: long enough
# for every tab's deferred setup to have fired.
RUN_MS = 2000


def bundle_problems() -> list[str]:
    """Return what is missing for an acquisition to work. Empty when complete."""
    problems = []
    helpers = functions_dir()
    for name in HELPER_FILES:
        if not os.path.isfile(os.path.join(helpers, name)):
            problems.append(f"missing helper: {os.path.join(helpers, name)}")

    programs = programs_dir()
    if not glob.glob(os.path.join(programs, "program_*.txt")):
        problems.append(f"no program_*.txt in {programs}")
    for tag in DEFAULT_PROGRAMS:
        path = os.path.join(programs, f"program_{tag}.txt")
        if not os.path.isfile(path):
            problems.append(f"missing program: {path}")

    missing_fw = sorted(set(FIRMWARE_VERSIONS) - set(available_firmwares()))
    if missing_fw:
        problems.append(f"no bitfile for firmware: {', '.join(missing_fw)}")
    if resolve_pwr_mgt_cwd(None)[1] is None:
        problems.append("no legacy bitfile (params/camera/bitfile/Kelpie_top.bit)")

    for size in ICON_SIZES:
        if not icon_file(size).is_file():
            problems.append(f"missing icon: {icon_file(size)}")
    return problems


def run_smoke_test(report_path: str, start: Callable[[], object]) -> int:
    """Start the app the normal way, quit it, and report what went wrong.

    Parameters
    ----------
    report_path : str
        File to write the result to: ``OK``, or one problem per line.
    start : callable
        The app's own 'main', so the window is built exactly as a user gets
        it. Must return the main window and return once the event loop ends.

    Returns
    -------
    int
        0 when the window built and nothing is missing, 1 otherwise.
    """
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QTabWidget

    problems = bundle_problems()
    try:
        # Created here, before 'start' reuses it, so the quit can be scheduled
        # ahead of the event loop that 'start' then blocks in.
        app = QApplication.instance() or QApplication(sys.argv)
        QTimer.singleShot(RUN_MS, app.quit)
        window = start()
        tabs = window.findChild(QTabWidget) if window is not None else None
        if tabs is None or tabs.count() == 0:
            problems.append("the main window has no tabs")
    except Exception:  # noqa: BLE001 - this is what the test is looking for
        problems.append("the app failed to start:\n" + traceback.format_exc())

    frozen = "frozen exe" if getattr(sys, "frozen", False) else "source tree"
    lines = problems or ["OK"]
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(f"DAPKEL-RTP smoke test ({frozen})\n")
        fh.write("\n".join(lines) + "\n")
    return 1 if problems else 0
