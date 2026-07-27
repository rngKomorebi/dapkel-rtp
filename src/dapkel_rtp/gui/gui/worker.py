"""Background QThread workers for acquisition."""

import os
import subprocess

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

# ---------------------------------------------------------------------------
# Power management worker  (replicates lines 1-72 of liveimaging.py)
# ---------------------------------------------------------------------------

_NBITS = 17 * (32 * 32) - 1  # 17407
_CLK_SHIFT = 2400

# Kelpie_v2.exe / Kelpie_v2_pwr_mgt.exe are console-subsystem executables.
# When this app itself has no console -- the case for the --noconsole
# PyInstaller build -- Windows would otherwise flash open a brand new
# console window for each one. Passed to every subprocess.run() call below.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _run_pwr_mgt_sync(exe_dir: str, program_file: str, cwd: str) -> tuple:
    """Synchronous, non-signalling variant of PowerMgtWorker.run() for use
    inside another worker's loop. Returns (success, message)."""
    exe_path = os.path.join(exe_dir, "Kelpie_v2_pwr_mgt.exe")
    if not os.path.isfile(exe_path):
        return False, f"Kelpie_v2_pwr_mgt.exe not found at: {exe_path}"

    cmd = [
        exe_path,
        str(_NBITS),
        program_file,
        program_file,
        program_file,
        program_file,
        str(_CLK_SHIFT),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        return False, str(exc)

    if result.returncode != 0:
        return (
            False,
            f"Power management failed (exit code {result.returncode})",
        )
    return True, "ok"


class PowerMgtWorker(QThread):
    """Runs Kelpie_v2_pwr_mgt.exe once to initialise the FPGA."""

    log = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, exe_dir: str, program_file: str, bitfile_dir: str):
        super().__init__()
        self._exe_dir = exe_dir
        self._program_file = program_file
        self._bitfile_dir = bitfile_dir

    def run(self):
        exe_path = os.path.join(self._exe_dir, "Kelpie_v2_pwr_mgt.exe")
        if not os.path.isfile(exe_path):
            self.finished.emit(
                False, f"Kelpie_v2_pwr_mgt.exe not found at: {exe_path}"
            )
            return

        cmd = [
            exe_path,
            str(_NBITS),
            self._program_file,
            self._program_file,
            self._program_file,
            self._program_file,
            str(_CLK_SHIFT),
        ]
        self.log.emit(f"Running: {os.path.basename(exe_path)}")
        self.log.emit(
            f"  nbits={_NBITS}, clk_shift={_CLK_SHIFT}"
            f", program={os.path.basename(self._program_file)}"
        )

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self._bitfile_dir,  # exe resolves ./bitfile/Kelpie_top.bit from here
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            self.finished.emit(False, str(exc))
            return

        output = result.stdout.decode(errors="replace").strip()
        if output:
            self.log.emit(f"  {output.replace(chr(10), chr(10) + '  ')}")
        if result.returncode != 0:
            self.finished.emit(
                False,
                f"Power management failed (exit code {result.returncode})",
            )
            return

        self.finished.emit(True, "Power management initialisation complete.")


# ---------------------------------------------------------------------------
# Acquisition worker
# ---------------------------------------------------------------------------


class AcquisitionWorker(QThread):
    """Runs Kelpie_v2.exe nacq times in a background thread."""

    log = pyqtSignal(str)
    progress = pyqtSignal(int)  # 0–100 percent
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, params: dict):
        super().__init__()
        self.params = params
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        p = self.params
        exe_path = os.path.join(p["exe_dir"], "Kelpie_v2.exe")

        if not os.path.isfile(exe_path):
            self.finished.emit(
                False, f"Kelpie_v2.exe not found at: {exe_path}"
            )
            return

        try:
            os.makedirs(p["folder"], exist_ok=True)
        except OSError as exc:
            self.finished.emit(False, f"Cannot create output folder: {exc}")
            return

        # The exe does string concatenation so it needs a trailing separator
        folder_exe = p["folder"].rstrip(os.sep) + os.sep

        nacq = p["nacq"]
        start_index = p.get("start_index", 1)
        for i in range(nacq):
            if self._abort:
                self.finished.emit(False, "Aborted by user")
                return

            filename_i = f"{p['filename']}_{p['program_tag']}{start_index + i}"
            cmd = [
                exe_path,
                str(p["chip_config"]),
                str(p["exposure_time"]),
                str(p["nframes"]),
                folder_exe,
                filename_i,
            ]
            self.log.emit(f"[{i + 1}/{nacq}] Running: {filename_i}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=p["exe_dir"],
                creationflags=_NO_WINDOW,
            )

            if result.stdout.strip():
                self.log.emit(f"  stdout: {result.stdout.strip()}")
            if result.returncode != 0:
                if result.stderr.strip():
                    self.log.emit(f"  stderr: {result.stderr.strip()}")
                self.finished.emit(
                    False,
                    f"Acquisition {i + 1} failed (exit code {result.returncode})",
                )
                return

            pct = int((i + 1) / nacq * 100)
            self.progress.emit(pct)
            self.log.emit(f"  Done ({pct}%)")

        self.finished.emit(True, f"All {nacq} acquisitions complete.")


# ---------------------------------------------------------------------------
# Live view worker
# ---------------------------------------------------------------------------


class LiveViewWorker(QThread):
    """Continuously runs Kelpie_v2.exe and previews the first decoded frame
    of each acquisition.

    Two modes:

    * Single-channel (32x32): python port of the acquire-decode-display
      loop in dapkel_rtp/matlab/liveimaging.m (lines 51-71): each pass
      reacquires ``nframes`` frames into one constantly-overwritten .bin
      file and decodes only frame 0 for the live preview, since the loop
      itself supplies the frame rate.
    * Full-array (64x64): cycles through the four quadrant programs
      (S0C/S1C/S2C/S3C), reprogramming the FPGA before each quadrant's
      acquisition (required because a quadrant is only exposed on the
      DDR3 bus while its program is loaded) and stitching the four
      32x32 results into one 64x64 frame using the same interleave
      pattern as the DCR Hitmap tab's 64x64 assembly.
    """

    # 32x32 ndarray for single-channel mode, 64x64 for full-array mode
    frame = pyqtSignal(object)
    stage = pyqtSignal(str)  # progress text within one composite frame
    error = pyqtSignal(str)
    finished = pyqtSignal()

    _SPAD_LAYOUT = {
        "S0C": (0, 0),
        "S1C": (0, 1),
        "S2C": (1, 0),
        "S3C": (1, 1),
    }

    def __init__(self, params: dict):
        super().__init__()
        self.params = params
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        p = self.params
        exe_path = os.path.join(p["exe_dir"], "Kelpie_v2.exe")
        if not os.path.isfile(exe_path):
            self.error.emit(f"Kelpie_v2.exe not found at: {exe_path}")
            self.finished.emit()
            return

        try:
            os.makedirs(p["folder"], exist_ok=True)
        except OSError as exc:
            self.error.emit(f"Cannot create output folder: {exc}")
            self.finished.emit()
            return

        if p["mode_64"]:
            self._run_64(exe_path)
        else:
            self._run_32(exe_path)

        self.finished.emit()

    # ------------------------------------------------------------------
    # Single-channel (32x32) loop
    # ------------------------------------------------------------------

    def _run_32(self, exe_path: str):
        from dapkel_rtp.functions.unpack import unpack_kelpie_binary_data

        p = self.params
        # The exe does string concatenation so it needs a trailing separator
        folder_exe = p["folder"].rstrip(os.sep) + os.sep
        filepath = os.path.join(p["folder"], p["filename"] + ".bin")

        while not self._abort:
            # Rebuilt every pass (not hoisted above the loop) so that
            # nframes/exposure_time/chip_config edits made in the GUI while
            # live view is running take effect on the very next acquisition
            # instead of only after a Stop/Start cycle.
            cmd = [
                exe_path,
                str(p["chip_config"]),
                str(p["exposure_time"]),
                str(p["nframes"]),
                folder_exe,
                p["filename"],
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=p["exe_dir"],
                creationflags=_NO_WINDOW,
            )
            if self._abort:
                break
            if result.returncode != 0:
                self.error.emit(
                    f"Acquisition failed (exit code {result.returncode}): "
                    f"{result.stderr.strip()}"
                )
                break

            try:
                _, photon_counts = unpack_kelpie_binary_data(filepath, 1)
            except (OSError, ValueError) as exc:
                self.error.emit(f"Cannot decode frame: {exc}")
                break

            self.frame.emit(photon_counts[:, :, 0])

    # ------------------------------------------------------------------
    # Full-array (64x64) quadrant-cycling loop
    # ------------------------------------------------------------------

    def _run_64(self, exe_path: str):
        from dapkel_rtp.functions.unpack import unpack_kelpie_binary_data

        p = self.params
        folder_exe = p["folder"].rstrip(os.sep) + os.sep
        quadrant_programs = p["quadrant_programs"]  # tag -> program file path
        pwr_cwd = p["pwr_cwd"]

        while not self._abort:
            dcr64 = np.zeros((64, 64), dtype=np.float64)
            for i, (tag, (dr, dc)) in enumerate(self._SPAD_LAYOUT.items()):
                if self._abort:
                    return

                self.stage.emit(f"Programming {tag} ({i + 1}/4)…")
                ok, msg = _run_pwr_mgt_sync(
                    p["exe_dir"], quadrant_programs[tag], pwr_cwd
                )
                if not ok:
                    self.error.emit(f"{tag} programming failed: {msg}")
                    return
                if self._abort:
                    return

                self.stage.emit(f"Acquiring {tag} ({i + 1}/4)…")
                filename = f"live_{tag}"
                filepath = os.path.join(p["folder"], filename + ".bin")
                cmd = [
                    exe_path,
                    str(p["chip_config"]),
                    str(p["exposure_time"]),
                    str(p["nframes"]),
                    folder_exe,
                    filename,
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=p["exe_dir"],
                    creationflags=_NO_WINDOW,
                )
                if result.returncode != 0:
                    self.error.emit(
                        f"{tag} acquisition failed (exit code {result.returncode}): "
                        f"{result.stderr.strip()}"
                    )
                    return

                try:
                    _, photon_counts = unpack_kelpie_binary_data(filepath, 1)
                except (OSError, ValueError) as exc:
                    self.error.emit(f"Cannot decode {tag}: {exc}")
                    return

                rows = np.arange(32) * 2 + dr
                cols = np.arange(32) * 2 + dc
                dcr64[np.ix_(rows, cols)] = photon_counts[:, :, 0]

            if self._abort:
                return
            self.frame.emit(dcr64)
