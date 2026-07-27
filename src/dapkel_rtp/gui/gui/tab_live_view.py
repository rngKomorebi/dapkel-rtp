"""Tab 3 - Live View (continuous single-frame preview).

Python port of dapkel_rtp/matlab/liveimaging.m: runs Kelpie_v2.exe in a tight
loop against one constantly-overwritten .bin file and previews only the
first decoded frame of each acquisition until stopped.
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

from ._paths import functions_dir, params_camera_dir, programs_dir
from .style import BG, OUTLINE, TEXT_DIM
from .tab_acquisition import SettingsDialog
from .worker import LiveViewWorker, PowerMgtWorker

CLK_PERIOD = 5e-9  # 200 MHz clock -> 5 ns


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
        self.nframes_spin.setToolTip(
            "Frames captured per acquisition; only the first is previewed."
        )
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
            self.nframes_spin.setToolTip(
                "Frames captured per quadrant acquisition (x4 per composite "
                "frame, one per S0C/S1C/S2C/S3C); lower this for a faster refresh."
            )
            self.start_btn.setEnabled(True)
            self.start_btn.setToolTip(
                "Cycles S0C → S1C → S2C → S3C each frame, reprogramming the "
                "FPGA between quadrants; slower than single-channel mode."
            )
        else:
            self.nframes_spin.setToolTip(
                "Frames captured per acquisition; only the first is previewed."
            )
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

    def _rebuild_plot(self, data: np.ndarray, rows: int, cols: int):
        """Full rebuild: new axes/colorbar plus the two-pass centering fix.
        Expensive (two full-figure draws), so this only runs when the image
        shape or canvas size actually changed, not on every frame."""
        self.figure.clear()
        self.figure.set_tight_layout(True)
        ax = self.figure.add_subplot(111)
        im = ax.imshow(data, cmap="gray", aspect="equal", origin="lower")
        cb = self.figure.colorbar(im, ax=ax)
        cb.ax.tick_params(colors=TEXT_DIM)
        cb.outline.set_edgecolor(OUTLINE)
        ax.tick_params(colors=TEXT_DIM)
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

    def _on_frame(self, photon_counts: np.ndarray):
        self._frame_count += 1
        self._update_fps()
        rows, cols = photon_counts.shape
        data = np.fliplr(photon_counts)
        canvas_size = (self.canvas.width(), self.canvas.height())

        needs_rebuild = (
            self._plot_im is None
            or self._plot_shape != (rows, cols)
            or self._plot_canvas_size != canvas_size
        )
        if needs_rebuild:
            self._rebuild_plot(data, rows, cols)
        else:
            self._plot_im.set_data(data)
            self._plot_im.autoscale()

        self._plot_ax.set_title(
            f"Live frame #{self._frame_count}  {rows}x{cols}   ({self._fps:.1f} fps)",
            color=TEXT_DIM,
        )
        self.canvas.draw_idle()

        self.status_label.setText(
            f"Live, frame #{self._frame_count}, {self._fps:.1f} fps"
        )
