"""Background QThread workers for acquisition."""

import os
import subprocess
import time

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from dapkel_rtp.functions.timing import CLK_PERIOD

# ---------------------------------------------------------------------------
# Power management worker  (replicates lines 1-72 of liveimaging.py)
# ---------------------------------------------------------------------------

NBITS = 17 * (32 * 32) - 1  # 17407
CLK_SHIFT = 2400

# Kelpie_v2.exe / Kelpie_v2_pwr_mgt.exe are console-subsystem executables.
# When this app itself has no console -- the case for the --noconsole
# PyInstaller build -- Windows would otherwise flash open a brand new
# console window for each one. Passed to every subprocess.run() call below.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW


# The live view keeps running until the user stops it. A pass can fail for
# reasons that are over by the next one -- the exe exiting non-zero, a 0-byte
# or short .bin (observed after an interrupted run), a decode error -- so a
# failed pass is reported and retried, never a reason to end the preview.
# Only this short pause is inserted, so a persistently failing exe cannot spin
# the loop at full speed.
_RETRY_PAUSE_S = 0.3


def _truncate_bin(filepath: str) -> None:
    """Empty a live-view '.bin' before the acquisition overwrites it.

    The '.bin' is at least as long as the readout's 16 MiB block, so a pass
    that writes fewer frames than the one before it would otherwise leave the
    previous acquisition's frames sitting in the tail, where they would be
    accumulated as if they were current -- the beam having moved in between, that shows up as blobs
    jumping around or doubling. Starting from an empty file makes anything
    this pass did not write either absent or zero, both of which the hitmap
    reduction detects and drops.
    """
    try:
        with open(filepath, "wb"):
            pass
    except OSError:
        pass  # the exe creates the file itself; nothing to clear


def _run_pwr_mgt_sync(exe_dir: str, program_file: str, cwd: str) -> tuple:
    """Synchronous, non-signalling variant of PowerMgtWorker.run() for use
    inside another worker's loop. Returns (success, message)."""
    exe_path = os.path.join(exe_dir, "Kelpie_v2_pwr_mgt.exe")
    if not os.path.isfile(exe_path):
        return False, f"Kelpie_v2_pwr_mgt.exe not found at: {exe_path}"

    cmd = [
        exe_path,
        str(NBITS),
        program_file,
        program_file,
        program_file,
        program_file,
        str(CLK_SHIFT),
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
            str(NBITS),
            self._program_file,
            self._program_file,
            self._program_file,
            self._program_file,
            str(CLK_SHIFT),
        ]
        self.log.emit(f"Running: {os.path.basename(exe_path)}")
        self.log.emit(
            f"  nbits={NBITS}, clk_shift={CLK_SHIFT}"
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
    """Runs Kelpie_v2.exe nacq times in a background thread.

    Also writes the run's ``metadata.json`` beside the data, when the caller
    put a ``metadata`` dict in ``params`` (see 'functions.metadata'). The record
    is built from the parameters this worker actually passed to the exe, not
    from a separate copy, so it cannot drift from what was run.

    It is written twice: once after the first file, with ``status='running'``,
    so a long run is documented from the start and a record exists even if the
    app is killed; and once at the end with the outcome. Both writes reuse the
    same ``run_id``, so the second replaces the first rather than adding to it.
    """

    log = pyqtSignal(str)
    progress = pyqtSignal(int)  # 0–100 percent
    finished = pyqtSignal(bool, str)  # (success, message)

    def __init__(self, params: dict):
        super().__init__()
        self.params = params
        self._abort = False
        self._run_id: str | None = None
        self._readout: dict | None = None
        self._bytes_per_file: int | None = None

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
        settings = self._metadata_settings(exe_path)
        started = time.time()
        elapsed: list[float] = []
        written = 0

        for i in range(nacq):
            if self._abort:
                self._write_metadata(
                    settings, "aborted", started, time.time(), elapsed, written
                )
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

            t0 = time.perf_counter()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=p["exe_dir"],
                creationflags=_NO_WINDOW,
            )
            took = time.perf_counter() - t0

            if result.stdout.strip():
                self.log.emit(f"  stdout: {result.stdout.strip()}")
            if result.returncode != 0:
                if result.stderr.strip():
                    self.log.emit(f"  stderr: {result.stderr.strip()}")
                self._write_metadata(
                    settings, "failed", started, time.time(), elapsed, written
                )
                self.finished.emit(
                    False,
                    f"Acquisition {i + 1} failed (exit code {result.returncode})",
                )
                return

            elapsed.append(took)
            written += 1
            filepath = os.path.join(p["folder"], filename_i + ".bin")
            if written == 1:
                # Measure the readout shape once per run: one byte pass over
                # one file confirms that everything past 'nframes' really is a
                # replay of earlier frames, so a firmware change shows up
                # instead of being assumed away.
                self._probe_first_file(filepath, p["nframes"])
                self._write_metadata(
                    settings, "running", started, None, elapsed, written
                )

            pct = int((i + 1) / nacq * 100)
            self.progress.emit(pct)
            self.log.emit(f"  Done ({pct}%)")

        self._write_metadata(
            settings, "completed", started, time.time(), elapsed, written
        )
        self.finished.emit(True, f"All {nacq} acquisitions complete.")

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _metadata_settings(self, exe_path: str) -> dict:
        """The tab's settings, overwritten with what was actually executed."""
        from dapkel_rtp.functions.hitmap import mode_for_program

        p = self.params
        settings = dict(p.get("metadata") or {})
        settings.update(
            {
                "folder": p["folder"],
                "filename_prefix": p["filename"],
                "program_tag": p["program_tag"],
                "mode": mode_for_program(p["program_tag"]),
                "start_index": p.get("start_index", 1),
                "nacq_requested": p["nacq"],
                "nframes": p["nframes"],
                "open_shutter_clks": p["exposure_time"],
                "chip_config": p["chip_config"],
                "exe": exe_path,
            }
        )
        return settings

    def _probe_first_file(self, filepath: str, nframes: int):
        """Record what the first '.bin' holds; never fail the run over it."""
        if not self.params.get("metadata"):
            return
        from dapkel_rtp.functions.metadata import probe_readout

        try:
            self._readout = probe_readout(filepath, int(nframes))
            self._bytes_per_file = self._readout["bytes_in_file"]
        except (OSError, ValueError) as exc:
            self.log.emit(f"  ! could not inspect {os.path.basename(filepath)}: {exc}")
            return
        if self._readout["verified"] is False:
            # Worth shouting about: every file measured so far has a replayed
            # tail, so one that does not may hold data this run wrote.
            self.log.emit(
                f"  ! {os.path.basename(filepath)}: slots past frame {nframes} "
                "are NOT a replay of earlier frames -- look at them before "
                "trusting or discarding them."
            )

    def _write_metadata(
        self,
        settings: dict,
        status: str,
        started: float,
        finished: float | None,
        elapsed: list,
        written: int,
    ):
        """Merge this run's record into the folder's metadata.json.

        Never raises: a run whose data landed fine must not be reported as
        failed because its record could not be written.
        """
        if not self.params.get("metadata"):
            return
        from dapkel_rtp.functions.metadata import build_run_record, new_run_id, upsert_run

        try:
            if self._run_id is None:
                self._run_id = new_run_id(
                    started, settings["folder"], settings["filename_prefix"]
                )
            record = build_run_record(
                settings,
                run_id=self._run_id,
                status=status,
                started=started,
                finished=finished,
                n_files_written=written,
                per_file_elapsed_s=elapsed,
                readout=self._readout,
                bytes_per_file=self._bytes_per_file,
            )
            path = upsert_run(settings["folder"], record)
        except Exception as exc:  # noqa: BLE001 - metadata never fails a run
            self.log.emit(f"  ! metadata not written: {exc}")
            return
        if status != "running":
            self.log.emit(
                f"  Metadata: {os.path.basename(path)} "
                f"({status}, {written} file(s), "
                f"{record['total_frames']:,} frames, "
                f"{record['wallclock_time_s']:.3f} s camera time)"
            )


# ---------------------------------------------------------------------------
# Live view worker
# ---------------------------------------------------------------------------


class LiveViewWorker(QThread):
    """Continuously runs Kelpie_v2.exe and previews a hitmap of each
    acquisition.

    Each pass emits an accumulated *hitmap* reduced over the frames of the
    acquisition — the same reduction dapkel's ``hitmap_analysis`` performs
    offline — not a single decoded frame. The frames are captured either
    way, and reducing over them is what makes the preview reproduce the
    offline hitmaps instead of a shot-noise-dominated snapshot.

    Which reduction depends on the loaded program: photon counts are summed
    for the ``*C`` programs, frames-with-a-valid-timestamp are counted for
    the timestamp programs (where the counts field holds timestamp bits and
    must not be summed). Frames that carry no data are dropped. Both live in
    dapkel_rtp.functions.hitmap.

    Two modes:

    * Single-channel (32x32): each pass reacquires ``nframes`` frames into
      one constantly-overwritten .bin file and accumulates them into a
      32x32 hitmap.
    * Full-array (64x64): cycles through the four quadrant programs
      (S0C/S1C/S2C/S3C), reprogramming the FPGA before each quadrant's
      acquisition (required because a quadrant is only exposed on the
      DDR3 bus while its program is loaded) and stitching the four
      accumulated 32x32 hitmaps into one 64x64 map using the same
      interleave pattern as the DCR Hitmap tab's 64x64 assembly.
    """

    # dict payload: {"hitmap": (32,32)/(64,64) accumulated counts or
    # occupancy, "frames": frames that carried data and were accumulated,
    # "frames_read": frames read, "frames_requested": frames asked for,
    # "mode": hitmap.MODE_*, "live_per_frame": live seconds per frame or
    # None, "unit": rate unit, "live_source": where the live time came from}
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
        # Whatever happens, 'finished' has to be emitted: if this thread died
        # on an unhandled exception the tab would sit there with Stop enabled,
        # no frames arriving and no way back -- which looks exactly like the
        # acquisition having stopped for no reason.
        try:
            self._run()
        except BaseException as exc:  # noqa: BLE001 - last-resort reporter
            self.error.emit(f"Live view stopped on an internal error: {exc!r}")
        finally:
            self.finished.emit()

    def _run(self):
        p = self.params
        exe_path = os.path.join(p["exe_dir"], "Kelpie_v2.exe")
        if not os.path.isfile(exe_path):
            self.error.emit(f"Kelpie_v2.exe not found at: {exe_path}")
            return

        try:
            os.makedirs(p["folder"], exist_ok=True)
        except OSError as exc:
            self.error.emit(f"Cannot create output folder: {exc}")
            return

        if p["mode_64"]:
            self._run_64(exe_path)
        else:
            self._run_32(exe_path)

    def _retry_pause(self):
        """Wait briefly after a failed pass, still responsive to Stop."""
        deadline = time.monotonic() + _RETRY_PAUSE_S
        while not self._abort and time.monotonic() < deadline:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Single-channel (32x32) loop
    # ------------------------------------------------------------------

    def _run_32(self, exe_path: str):
        from dapkel_rtp.functions.hitmap import (
            accumulate_hitmap,
            live_time_per_frame,
        )

        p = self.params
        # The exe does string concatenation so it needs a trailing separator
        folder_exe = p["folder"].rstrip(os.sep) + os.sep
        filepath = os.path.join(p["folder"], p["filename"] + ".bin")
        mode = p["hitmap_mode"]
        retries = 0

        while not self._abort:
            # Snapshot the parameters the GUI thread can change mid-run
            # (nframes/exposure via the spinboxes) ONCE per pass: the very
            # same nframes must drive the acquisition and the decode, or a
            # mid-pass edit would have us read frames this pass never wrote
            # and mix in leftovers from the previous one.
            nframes = int(p["nframes"])
            exposure_ticks = int(p["exposure_time"])

            _truncate_bin(filepath)
            cmd = [
                exe_path,
                str(p["chip_config"]),
                str(exposure_ticks),
                str(nframes),
                folder_exe,
                p["filename"],
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=p["exe_dir"],
                    creationflags=_NO_WINDOW,
                )
            except OSError as exc:
                retries += 1
                self.error.emit(f"Could not start the exe ({exc}); retry {retries}")
                self._retry_pause()
                continue
            if self._abort:
                break
            if result.returncode != 0:
                # Retry instead of ending the preview -- the next acquisition
                # usually succeeds, and the user decides when to stop.
                retries += 1
                self.error.emit(
                    f"Acquisition failed (exit code {result.returncode}), "
                    f"retrying [{retries}]: {result.stderr.strip()}"
                )
                self._retry_pause()
                continue

            # Reduce over every captured frame, not just frame 0 -- the
            # acquisition already holds them, and that is what makes the
            # preview match the offline hitmap analysis.
            try:
                hitmap, frames, frames_read = accumulate_hitmap(
                    filepath, nframes, mode
                )
            except Exception as exc:  # noqa: BLE001 - a bad pass must not stop us
                # An empty or short .bin means that one acquisition produced
                # nothing usable; report it and take the next one. Anything
                # else unexpected is treated the same way, because a live view
                # that quits on its own is worse than one that complains.
                retries += 1
                self.error.emit(
                    f"Unusable acquisition, retrying [{retries}]: {exc}"
                )
                self._retry_pause()
                continue
            retries = 0

            live, unit, live_source = live_time_per_frame(
                mode, p["firmware_version"], exposure_ticks * CLK_PERIOD
            )
            self.frame.emit(
                {
                    "hitmap": hitmap,
                    "frames": frames,
                    "frames_read": frames_read,
                    "frames_requested": nframes,
                    "mode": mode,
                    "live_per_frame": live,
                    "unit": unit,
                    "live_source": live_source,
                }
            )

    # ------------------------------------------------------------------
    # Full-array (64x64) quadrant-cycling loop
    # ------------------------------------------------------------------

    def _run_64(self, exe_path: str):
        from dapkel_rtp.functions.hitmap import (
            accumulate_hitmap,
            live_time_per_frame,
        )

        p = self.params
        folder_exe = p["folder"].rstrip(os.sep) + os.sep
        quadrant_programs = p["quadrant_programs"]  # tag -> program file path
        pwr_cwd = p["pwr_cwd"]
        mode = p["hitmap_mode"]
        retries = 0

        while not self._abort:
            # Per-quadrant accumulated hitmaps with their own frame counts:
            # each quadrant is a separate acquisition, so each is normalised by
            # the frames *it* delivered rather than rescaled onto a common
            # basis. Nothing is scaled to match anything else.
            quad_maps: dict[str, tuple[np.ndarray, int]] = {}
            # Snapshot once per composite frame, so all four quadrants share
            # one acquisition setting even if the GUI is edited mid-cycle.
            nframes = int(p["nframes"])
            exposure_ticks = int(p["exposure_time"])
            frames_read_min = nframes
            for i, (tag, (dr, dc)) in enumerate(self._SPAD_LAYOUT.items()):
                if self._abort:
                    return

                self.stage.emit(f"Programming {tag} ({i + 1}/4)…")
                ok, msg = _run_pwr_mgt_sync(
                    p["exe_dir"], quadrant_programs[tag], pwr_cwd
                )
                if not ok:
                    retries += 1
                    self.error.emit(
                        f"{tag} programming failed, retrying [{retries}]: {msg}"
                    )
                    self._retry_pause()
                    break
                if self._abort:
                    return

                self.stage.emit(f"Acquiring {tag} ({i + 1}/4)…")
                filename = f"live_{tag}"
                filepath = os.path.join(p["folder"], filename + ".bin")
                _truncate_bin(filepath)
                cmd = [
                    exe_path,
                    str(p["chip_config"]),
                    str(exposure_ticks),
                    str(nframes),
                    folder_exe,
                    filename,
                ]
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=p["exe_dir"],
                        creationflags=_NO_WINDOW,
                    )
                except OSError as exc:
                    retries += 1
                    self.error.emit(
                        f"Could not start the exe ({exc}); retry {retries}"
                    )
                    self._retry_pause()
                    break
                if result.returncode != 0:
                    retries += 1
                    self.error.emit(
                        f"{tag} acquisition failed (exit code "
                        f"{result.returncode}), retrying [{retries}]: "
                        f"{result.stderr.strip()}"
                    )
                    self._retry_pause()
                    break

                try:
                    quad, frames_q, read_q = accumulate_hitmap(
                        filepath, nframes, mode
                    )
                except Exception as exc:  # noqa: BLE001 - see _run_32
                    # One unusable quadrant means no composite frame this
                    # round; take the next cycle rather than ending the view.
                    retries += 1
                    self.error.emit(
                        f"{tag} unusable, retrying [{retries}]: {exc}"
                    )
                    self._retry_pause()
                    break
                quad_maps[tag] = (quad, frames_q)
                frames_read_min = min(frames_read_min, read_q)

            if self._abort:
                return
            if len(quad_maps) < len(self._SPAD_LAYOUT):
                continue  # a quadrant needs retrying; start the next cycle
            retries = 0

            # Stitch onto the full sensor grid, each quadrant carrying its own
            # valid-frame count so the rate can be formed per pixel from what
            # that quadrant actually measured -- no quadrant is scaled to
            # match another. Quadrants that delivered nothing keep a frame
            # count of 0 and are reported rather than filled in.
            hitmap64 = np.zeros((64, 64), dtype=np.float64)
            frames64 = np.zeros((64, 64), dtype=np.float64)
            for tag, (dr, dc) in self._SPAD_LAYOUT.items():
                quad, used = quad_maps[tag]
                rows = np.arange(32) * 2 + dr
                cols = np.arange(32) * 2 + dc
                hitmap64[np.ix_(rows, cols)] = quad
                frames64[np.ix_(rows, cols)] = used

            frames_by_tag = {t: used for t, (_, used) in quad_maps.items()}
            empty = [t for t, used in frames_by_tag.items() if not used]
            if empty:
                self.stage.emit(f"No data from {', '.join(empty)}")

            live, unit, live_source = live_time_per_frame(
                mode, p["firmware_version"], exposure_ticks * CLK_PERIOD
            )
            self.frame.emit(
                {
                    "hitmap": hitmap64,
                    "frames": frames64,
                    "frames_by_tag": frames_by_tag,
                    "frames_read": frames_read_min,
                    "frames_requested": nframes,
                    "mode": mode,
                    "live_per_frame": live,
                    "unit": unit,
                    "live_source": live_source,
                }
            )


# ---------------------------------------------------------------------------
# Data-quality worker
# ---------------------------------------------------------------------------


class DataQualityWorker(QThread):
    """Runs one data-quality check over a single '.bin' file.

    No hardware is touched: this only decodes a file that is already on disk.
    It runs off the GUI thread because a full-length acquisition is hundreds
    of chunks of decoding, and it reports progress per chunk so a long file
    can be watched and aborted.
    """

    progress = pyqtSignal(int)  # 0-100 percent of frames examined
    finished = pyqtSignal(object)  # summary dict from data_quality.check_file
    error = pyqtSignal(str)

    def __init__(self, params: dict):
        super().__init__()
        self.params = params
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        # An unhandled exception here would leave the tab with Abort enabled
        # and no result ever arriving, which looks exactly like a check that
        # silently hung -- report it instead.
        from dapkel_rtp.functions.data_quality import check_file

        p = self.params
        try:
            summary = check_file(
                p["filepath"],
                p["nframes"],
                p["pixel"],
                p["mode"],
                progress=self._on_progress,
                should_abort=lambda: self._abort,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort reporter
            self.error.emit(str(exc))
            return
        self.finished.emit(summary)

    def _on_progress(self, done: int, total: int):
        self.progress.emit(int(done / total * 100) if total else 0)
