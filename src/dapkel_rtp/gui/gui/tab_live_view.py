"""Tab 3 - Live View (continuous hitmap preview).

Runs Kelpie_v2.exe in a tight loop against one constantly-overwritten .bin
file and previews a *hitmap* of each acquisition until stopped: the frames of
the acquisition reduced to one per-pixel map, shown as a photon rate.

Everything shown is counted out of the raw data, never modelled:

* every frame the acquisition wrote is reduced over, not sampled at frame 0 —
  a single 20 µs frame is shot noise, the reduction is the map (see
  dapkel_rtp.functions.hitmap);
* which reduction depends on the loaded program: summed photon counts for the
  ``*C`` programs, frames-with-a-valid-timestamp for the timestamp programs
  (whose counts field holds timestamp bits and must never be summed);
* frames that carry no data are dropped, so the map does not dim and brighten
  with however many idle frames a pass happened to start with;
* the colour scale spans the full measured range — hot pixels are shown as
  measured, nothing is clipped or smoothed;
* the colourbar is a photon rate: cps (counts / exposure) in count mode, Hz
  (firings / measured frame period) in timestamp mode. When the frame period
  cannot be measured, the counted map is shown in its own units instead of a
  rate derived from an assumed period.

The loop keeps acquiring until Stop: a failed acquisition is reported and
retried, never a reason to end the preview.
"""

import glob
import os
import time

import numpy as np
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dapkel_rtp.functions.hitmap import (
    MODE_COUNT,
    color_limits,
    mode_for_program,
    photon_rate,
)

from ._paths import functions_dir, params_camera_dir, programs_dir
from .style import BG, OUTLINE, TEXT_DIM
from .tab_acquisition import SettingsDialog
from .worker import LiveViewWorker, PowerMgtWorker

CLK_PERIOD = 5e-9  # 200 MHz clock -> 5 ns

# Tooltip for Frames/acq, kept in one place: it is re-set on every mode change.
_NFRAMES_TIP_32 = (
    "Frames captured per acquisition; every one of them is counted into\n"
    "the previewed hitmap.\n"
    "More frames = smoother map, slower refresh."
)
_NFRAMES_TIP_64 = (
    "Frames captured per quadrant acquisition (x4 per composite frame,\n"
    "one per S0C/S1C/S2C/S3C); every one of them is counted into the\n"
    "previewed hitmap.\n"
    "Lower this for a faster refresh."
)


class LiveViewTab(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: LiveViewWorker | None = None
        self._pwr_worker: PowerMgtWorker | None = None
        self._chip_state: dict = {
            "chip_debug": False,
            "chip_timing": True,
            "clk_shift": False,
            "chip_artif_rdout": False,
            "single_shot_noise": False,
            "memory_select0": False,
            "memory_select1": False,
            "debug_last_row": False,
            "external_frame_trigger": False,
        }
        self._exe_dir = functions_dir()
        self._frame_count = 0
        self._last_frame_time: float | None = None
        self._fps = 0.0
        # Cached plot artists; rebuilt only on shape/canvas-size change so a
        # window resize (or fullscreen) doesn't force a full rebuild+double
        # redraw on every single incoming frame.
        self._plot_ax = None
        self._plot_im = None
        self._plot_cb = None
        self._plot_shape = None
        self._plot_canvas_size = None
        self._plot_clabel = None  # colourbar units currently drawn
        self._pwr_mgt_program: str | None = None  # program currently loaded on the FPGA
        self._pwr_mgt_pending_program: str | None = None
        self._startup_complete = False
        self._build_ui()
        self._populate_programs()
        self.program_combo.currentIndexChanged.connect(self._on_program_change)
        # _on_mode_change's 32x32 branch calls _on_program_change, which
        # would otherwise auto-fire a real Power Mgt run during widget
        # construction, before the user has done anything.
        self._on_mode_change(self.mode_combo.currentIndex())
        self._startup_complete = True

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- Output folder ----
        out_grp = QGroupBox("Output Folder")
        out_lay = QHBoxLayout(out_grp)
        out_lay.setContentsMargins(8, 6, 8, 8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(
            "Folder for the live-view .bin file…"
        )
        self.folder_edit.setMinimumHeight(32)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.setFixedHeight(32)
        browse_btn.clicked.connect(self._browse_folder)
        out_lay.addWidget(self.folder_edit)
        out_lay.addWidget(browse_btn)
        root.addWidget(out_grp)

        # ---- Compact params row ----
        params = QHBoxLayout()
        params.setSpacing(8)

        params.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("32×32 (single channel)")
        self.mode_combo.addItem("64×64 (S0C→S1C→S2C→S3C cycle)")
        self.mode_combo.setMinimumWidth(210)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        params.addWidget(self.mode_combo)

        params.addWidget(QLabel("Program:"))
        self.program_combo = QComboBox()
        self.program_combo.setMinimumWidth(130)
        params.addWidget(self.program_combo)

        params.addWidget(QLabel("Frames/acq:"))
        self.nframes_spin = QSpinBox()
        self.nframes_spin.setRange(1, 1_100_000)
        self.nframes_spin.setValue(800)
        self.nframes_spin.setSingleStep(100)
        self.nframes_spin.setFixedWidth(90)
        self.nframes_spin.setToolTip(_NFRAMES_TIP_32)
        params.addWidget(self.nframes_spin)

        params.addWidget(QLabel("Exp:"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.0, 1_000_000.0)
        self.exp_spin.setDecimals(3)
        self.exp_spin.setValue(20.0)
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setFixedWidth(110)
        self.exp_spin.setToolTip(
            "Exposure time, set directly: whatever you enter here is the\n"
            "actual exposure achieved, e.g. 0.2 µs → 200 ns exposure.\n"
            "Readout takes the rest of the fixed ~9 µs frame period:\n"
            "readout = 9 µs - exposure. (Requires external_frame_trigger\n"
            "OFF in Settings -- that's a separate SMA hardware-sync feature.)"
        )
        params.addWidget(self.exp_spin)

        self.nframes_spin.valueChanged.connect(self._on_live_param_change)
        self.exp_spin.valueChanged.connect(self._on_live_param_change)

        params.addStretch()

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedWidth(120)
        settings_btn.clicked.connect(self._open_settings)
        params.addWidget(settings_btn)

        root.addLayout(params)

        # ---- Power management / Start / Stop ----
        btn_row = QHBoxLayout()

        self.pwr_btn = QPushButton("⚡  Power Mgt")
        self.pwr_btn.setObjectName("pwr_btn")
        self.pwr_btn.setFixedHeight(46)
        self.pwr_btn.setFixedWidth(150)
        self.pwr_btn.setToolTip("Initialise FPGA via Kelpie_v2_pwr_mgt.exe")
        self.pwr_btn.clicked.connect(self._run_pwr_mgt)

        self.start_btn = QPushButton("▶   Start Live View")
        self.start_btn.setObjectName("run_btn")
        self.start_btn.setFixedHeight(46)
        self.start_btn.setEnabled(False)
        self.start_btn.setToolTip("Run Power Mgt first to activate acquisition")
        self.start_btn.clicked.connect(self._start)

        self.stop_btn = QPushButton("■   Stop")
        self.stop_btn.setObjectName("abort_btn")
        self.stop_btn.setFixedHeight(46)
        self.stop_btn.setFixedWidth(130)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)

        btn_row.addWidget(self.pwr_btn)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        root.addLayout(btn_row)

        # ---- Status ----
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        root.addWidget(self.status_label)

        # ---- Matplotlib toolbar + canvas ----
        self.figure = Figure(tight_layout=True, facecolor=BG)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setStyleSheet(f"background: {BG}; border: none;")
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas, stretch=1)

    def _populate_programs(self):
        prog_dir = programs_dir()
        if os.path.isdir(prog_dir):
            for fp in sorted(
                glob.glob(os.path.join(prog_dir, "program_*.txt"))
            ):
                self.program_combo.addItem(os.path.basename(fp), userData=fp)
            for i in range(self.program_combo.count()):
                if "ORC" in self.program_combo.itemText(i):
                    self.program_combo.setCurrentIndex(i)
                    break
        self.folder_edit.setText(os.path.join(functions_dir(), "live"))

    @staticmethod
    def _resolve_quadrant_programs():
        """Locate program_S0C/S1C/S2C/S3C.txt; None if any is missing."""
        prog_dir = programs_dir()
        programs = {}
        for tag in ("S0C", "S1C", "S2C", "S3C"):
            fp = os.path.join(prog_dir, f"program_{tag}.txt")
            if not os.path.isfile(fp):
                return None
            programs[tag] = fp
        return programs

    def _on_mode_change(self, idx: int):
        is_64 = idx == 1
        self.program_combo.setEnabled(not is_64)
        self.pwr_btn.setEnabled(not is_64)
        if is_64:
            self.nframes_spin.setToolTip(_NFRAMES_TIP_64)
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip(
                "Cycles S0C → S1C → S2C → S3C each frame, reprogramming the "
                "FPGA between quadrants; slower than single-channel mode."
            )
        else:
            self.nframes_spin.setToolTip(_NFRAMES_TIP_32)
            self._on_program_change(self.program_combo.currentIndex())

    def _on_live_param_change(self, _value=None):
        """Push nframes/exposure edits into the running worker's params dict
        so they take effect on the next acquisition instead of only after a
        Stop/Start cycle."""
        if self._worker is None or not self._worker.isRunning():
            return
        self._worker.params["nframes"] = self.nframes_spin.value()
        self._worker.params["exposure_time"] = round(
            self.exp_spin.value() * 1e-6 / CLK_PERIOD
        )

    def _on_program_change(self, _idx: int):
        """Auto-run Power Mgt whenever the selected program actually
        changes, since the FPGA must be reprogrammed each time -- Power Mgt
        is no longer something you have to remember to click first. Start
        stays gated on whether the FPGA is already programmed for the
        current selection, so an unchanged program doesn't reprogram."""
        if not self._startup_complete:
            return  # still constructing; don't auto-fire before ready
        if self.stop_btn.isEnabled():
            return  # live view currently running; state will settle on stop
        if self.mode_combo.currentIndex() == 1:
            return  # 64x64 mode manages its own programming per quadrant
        if self._pwr_worker is not None and self._pwr_worker.isRunning():
            return  # a Power Mgt run is already in flight

        current = self.program_combo.currentData()
        if current is None:
            return

        if current == self._pwr_mgt_program:
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip("")
        else:
            self._run_pwr_mgt()

    def _browse_folder(self):
        start = self.folder_edit.text() or functions_dir()
        d = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", start
        )
        if d:
            self.folder_edit.setText(d)

    def _open_settings(self):
        dlg = SettingsDialog(self._chip_state, self._exe_dir, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._chip_state = dlg.chip_state()
            self._exe_dir = dlg.exe_dir()

    def _run_pwr_mgt(self):
        program_path = self.program_combo.currentData()
        if not program_path or not os.path.isfile(program_path):
            self.status_label.setText("⚠  Program file not found.")
            return

        self.pwr_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.program_combo.setEnabled(False)
        self.status_label.setText("Initialising FPGA…")

        self._pwr_mgt_pending_program = program_path
        self._pwr_worker = PowerMgtWorker(
            self._exe_dir, program_path, params_camera_dir()
        )
        self._pwr_worker.finished.connect(self._on_pwr_mgt_finished)
        self._pwr_worker.start()

    def _on_pwr_mgt_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        self.program_combo.setEnabled(True)
        if success:
            self._pwr_mgt_program = self._pwr_mgt_pending_program
            # Live View only re-enables Start once mode/program still match
            # what was just programmed; re-check rather than force True.
            self._on_program_change(self.program_combo.currentIndex())
        self.status_label.setText(("✓ " if success else "✗ ") + msg)

    def _start(self):
        folder = self.folder_edit.text()
        if not folder:
            self.status_label.setText("⚠  Select an output folder first.")
            return

        s = self._chip_state
        chip_config = (
            int(s["external_frame_trigger"]) << 8
            | int(s["debug_last_row"]) << 7
            | int(s["memory_select1"]) << 6
            | int(s["memory_select0"]) << 5
            | int(s["single_shot_noise"]) << 4
            # bit 3 reserved/unused
            | int(s["chip_artif_rdout"]) << 2
            | int(s["chip_timing"]) << 1
            | int(s["chip_debug"])
        )
        exposure_time = round(self.exp_spin.value() * 1e-6 / CLK_PERIOD)

        mode_64 = self.mode_combo.currentIndex() == 1
        if mode_64:
            quadrant_programs = self._resolve_quadrant_programs()
            if quadrant_programs is None:
                self.status_label.setText(
                    "⚠  Missing one or more of program_S0C/S1C/S2C/S3C.txt"
                )
                return
            params = {
                "exe_dir": self._exe_dir,
                "chip_config": chip_config,
                "exposure_time": exposure_time,
                "nframes": self.nframes_spin.value(),
                "folder": folder,
                "mode_64": True,
                "quadrant_programs": quadrant_programs,
                "pwr_cwd": params_camera_dir(),
                # All four quadrant programs are S*C, hence count mode; read
                # it off one of them rather than hardcoding the reduction.
                "hitmap_mode": mode_for_program(quadrant_programs["S0C"]),
            }
        else:
            program_path = self.program_combo.currentData()
            if not program_path or not os.path.isfile(program_path):
                self.status_label.setText("⚠  Program file not found.")
                return
            params = {
                "exe_dir": self._exe_dir,
                "chip_config": chip_config,
                "exposure_time": exposure_time,
                "nframes": self.nframes_spin.value(),
                "folder": folder,
                "filename": "live",
                "mode_64": False,
                # The program decides the reduction: summing the counts field
                # of a timestamp program would sum coarse-timestamp bits.
                "hitmap_mode": mode_for_program(program_path),
            }

        self._frame_count = 0
        self._last_frame_time = None
        self._fps = 0.0
        self._plot_shape = None  # force a clean rebuild for this run
        self.mode_combo.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pwr_btn.setEnabled(False)
        self.status_label.setText("Starting live view…")

        self._worker = LiveViewWorker(params)
        self._worker.frame.connect(self._on_frame)
        self._worker.stage.connect(self._on_stage)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.abort()
            self.status_label.setText("Stopping…")

    def _on_stage(self, msg: str):
        self.status_label.setText(msg)

    def _on_error(self, msg: str):
        self.status_label.setText(f"⚠  {msg}")

    def _on_finished(self):
        is_64 = self.mode_combo.currentIndex() == 1
        self.mode_combo.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pwr_btn.setEnabled(not is_64)
        if is_64:
            self.start_btn.setEnabled(True)
        else:
            # FPGA is still programmed for the same program from before this
            # run, so re-enable Start without forcing another Power Mgt call.
            self._on_program_change(self.program_combo.currentIndex())
        self.status_label.setText(f"Stopped after {self._frame_count} frame(s).")

    def _update_fps(self):
        now = time.perf_counter()
        if self._last_frame_time is not None:
            dt = now - self._last_frame_time
            if dt > 0:
                inst_fps = 1.0 / dt
                self._fps = (
                    inst_fps if self._fps == 0.0 else 0.8 * self._fps + 0.2 * inst_fps
                )
        self._last_frame_time = now

    def _rebuild_plot(
        self,
        data: np.ndarray,
        rows: int,
        cols: int,
        clabel: str,
        clim: tuple[float, float],
        title: str,
    ):
        """Full rebuild: new axes/colorbar plus the two-pass centering fix.
        Expensive (two full-figure draws), so this only runs when the image
        shape, canvas size or colourbar units actually changed, not on every
        frame. The title is set *here*, before the layout pass, because it is
        two lines tall and tight_layout has to reserve room for it."""
        self.figure.clear()
        self.figure.set_tight_layout(True)
        ax = self.figure.add_subplot(111)
        im = ax.imshow(
            data,
            cmap="gray",
            aspect="equal",
            origin="lower",
            vmin=clim[0],
            vmax=clim[1],
        )
        cb = self.figure.colorbar(im, ax=ax, label=clabel)
        cb.ax.tick_params(colors=TEXT_DIM)
        cb.ax.yaxis.label.set_color(TEXT_DIM)
        cb.outline.set_edgecolor(OUTLINE)
        ax.set_title(title, color=TEXT_DIM)
        ax.set_xlabel("Column", color=TEXT_DIM)
        ax.set_ylabel("Row", color=TEXT_DIM)
        ax.tick_params(colors=TEXT_DIM)
        # The dark theme turns the grid on globally; over a hitmap it just
        # draws lines across the pixels, so keep the image clean.
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_edgecolor(OUTLINE)

        # First pass lets tight_layout run and aspect="equal" shrink ax to a
        # square; only after that does ax.get_position() reflect the real
        # box, so centering has to happen as an explicit second pass. The
        # second draw must run with tight_layout disabled, otherwise it
        # recomputes the layout from scratch and silently discards the
        # manual set_position() calls below.
        self.figure.canvas.draw()
        pos_ax = ax.get_position()
        pos_cb = cb.ax.get_position()
        left = min(pos_ax.x0, pos_cb.x0)
        right = max(pos_ax.x1, pos_cb.x1)
        shift = (1.0 - (right - left)) / 2.0 - left
        if abs(shift) > 1e-6:
            ax.set_position(
                [pos_ax.x0 + shift, pos_ax.y0, pos_ax.width, pos_ax.height]
            )
            cb.ax.set_position(
                [pos_cb.x0 + shift, pos_cb.y0, pos_cb.width, pos_cb.height]
            )
        self.figure.set_tight_layout(False)

        self._plot_ax = ax
        self._plot_im = im
        self._plot_cb = cb
        self._plot_shape = (rows, cols)
        self._plot_canvas_size = (self.canvas.width(), self.canvas.height())
        self._plot_clabel = clabel

    def _on_frame(self, payload: dict):
        """Render one accumulated hitmap emitted by the worker.

        ``payload`` carries the reduced map plus what is needed to normalise
        it: the reduction mode, the number of frames that carried data, and
        the live seconds per frame. The map is shown as a photon rate
        whenever that live time is known — the same quantity the offline
        'hitmap_analysis' rate map plots.
        """
        self._frame_count += 1
        self._update_fps()

        hitmap = payload["hitmap"]
        frames = payload["frames"]  # a number, or per-pixel in 64x64 mode
        frames_req = payload["frames_requested"]
        mode = payload["mode"]
        rows, cols = hitmap.shape

        # Rate when the live time is known, the counted map otherwise (a zero
        # exposure, or no measured frame period) — a rate is never formed from
        # an assumed time. In timestamp mode the map is an occupancy, in Hz.
        raw_label = "photon counts" if mode == MODE_COUNT else "frames fired"
        rate = photon_rate(hitmap, frames, payload["live_per_frame"])
        if rate is None:
            data, clabel, unit = hitmap, raw_label, ""
        else:
            data = rate
            clabel = f"photon rate [{payload['unit']}]"
            unit = f" {payload['unit']}"

        # Full measured range: every pixel is drawn as counted, hot ones
        # included. Nothing is clipped and the scale is not carried over
        # between refreshes.
        clim = color_limits(data)
        canvas_size = (self.canvas.width(), self.canvas.height())

        median = float(np.median(data))
        peak = float(data.max())
        frames_txt = self._frames_text(frames, frames_req)
        # The colourbar spans the full range, so it already shows the scale --
        # no need to restate it here (and a long second line would run into
        # the colourbar's exponent label).
        title = (
            f"Live hitmap #{self._frame_count}  {rows}×{cols}   "
            f"{mode} mode   ({self._fps:.1f} fps)\n"
            f"{frames_txt}  ·  median {median:.3g}{unit}  ·  "
            f"max {peak:.3g}{unit}"
        )

        needs_rebuild = (
            self._plot_im is None
            or self._plot_shape != (rows, cols)
            or self._plot_canvas_size != canvas_size
            or self._plot_clabel != clabel
        )
        if needs_rebuild:
            self._rebuild_plot(data, rows, cols, clabel, clim, title)
        else:
            self._plot_im.set_data(data)
            self._plot_im.set_clim(*clim)
            self._plot_ax.set_title(title, color=TEXT_DIM)
        self.canvas.draw_idle()

        if not np.any(np.asarray(frames) > 0):
            self.status_label.setText(
                f"⚠  hitmap #{self._frame_count}: no frame carried data "
                f"({payload['frames_read']} read) — chip idle?"
            )
            return

        read = payload["frames_read"]
        status = (
            f"Live, hitmap #{self._frame_count}, {self._fps:.1f} fps, "
            f"{frames_txt}, {payload['live_source']}, "
            f"median {median:.3g}{unit}, max {peak:.3g}{unit}"
        )
        if read < frames_req:
            status += f"  [only {read} frames in the file]"
        self.status_label.setText(status)

    @staticmethod
    def _frames_text(frames, frames_req: int) -> str:
        """Describe how many frames carried data, per quadrant if they differ.

        In 64x64 mode ``frames`` is a per-pixel array because each quadrant is
        its own acquisition; report the spread rather than a single number that
        would not be true of the whole map.
        """
        arr = np.asarray(frames, dtype=np.float64)
        if arr.ndim == 0:
            return f"{int(arr)}/{frames_req} frames with data"
        lo, hi = int(arr.min()), int(arr.max())
        if lo == hi:
            return f"{lo}/{frames_req} frames with data"
        return f"{lo}–{hi}/{frames_req} frames with data (per quadrant)"
