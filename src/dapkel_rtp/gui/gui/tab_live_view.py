"""Tab 3 - Live View (continuous hitmap preview).

Runs Kelpie_v2.exe in a tight loop against one constantly-overwritten .bin
file and previews a *hitmap* of each acquisition until stopped: the frames of
the acquisition reduced to one per-pixel map, shown as a photon rate.

Everything shown is counted out of the raw data, never modelled:

* every frame the acquisition wrote is reduced over, not sampled at frame 0 —
  a single frame is shot noise, the reduction is the map (see
  dapkel_rtp.functions.hitmap);
* which reduction depends on the loaded program: summed photon counts for the
  ``*C`` programs, frames-with-a-valid-timestamp for the timestamp programs
  (whose counts field holds timestamp bits and must never be summed);
* frames that carry no data are dropped, so the map does not dim and brighten
  with however many idle frames a pass happened to start with;
* the colour scale spans the full measured range — hot pixels are shown as
  measured, nothing is clipped or smoothed;
* the colourbar is a photon rate, and both modes divide by the same thing —
  the frame length, stated by the selected firmware and the shutter time
  (9 µs fixed under short_exposure, shutter + 9 µs under long_exposure). Count
  mode reads as cps, timestamp mode as Hz, bounded by one firing per frame.
  Nothing is read out of frame_rate_cnt.txt: that counter is not a frame
  period, see dapkel_rtp.functions.timing.
* timestamp mode also states the peak occupancy — the fraction of frames the
  single busiest pixel fired in, with that pixel's Row/Column, not an array
  average. It is the measured count over the measured frames, shown bare with
  no word judging it, because the Hz alone cannot tell a bright pixel from one
  that has run out of frames to fire in: high occupancy makes a long shutter
  read a *lower* rate on a bright pixel than a short shutter does. The
  coordinates say which case it is — in the beam spot, or a hot pixel alone in
  the dark field. See 'peak_occupancy' in dapkel_rtp.functions.hitmap.

No repaint rate is shown. The preview refreshes a few times a second, each pass
a whole acquisition plus its decode, and stating that next to the word "frame" —
which here means a 9 µs camera frame, i.e. 111 kfps — put two numbers four
orders of magnitude apart under one name and helped nobody read the map.

The loop keeps acquiring until Stop: a failed acquisition is reported and
retried, never a reason to end the preview.
"""

import glob
import os

import numpy as np
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dapkel_rtp.functions.timing import CLK_PERIOD

from dapkel_rtp.functions.hitmap import (
    MODE_COUNT,
    color_limits,
    mode_for_program,
    peak_occupancy,
    photon_rate,
)

from ._paths import (
    BITFILE_NAME,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    firmware_bitfile,
    functions_dir,
    masks_dir,
    programs_dir,
    resolve_pwr_mgt_cwd,
)
from .fpga_state import FPGA
from .pixel_mask import (
    PixelMaskWindow,
    SaveMaskDialog,
    mask_key,
    read_mask_file,
    saved_pixels,
    write_mask_file,
)
from .style import restyle_figure
from .theme import current_theme, theme_manager
from .tab_acquisition import EXP_UI, FIRMWARE_TIP, FRAME_READOUT_US, SettingsDialog
from .widgets import FRAME_MAX
from .worker import LiveViewWorker, PowerMgtWorker

# Tooltip for Frames/acq, kept in one place: it is re-set on every mode change.
# Unlike the acquisition tabs this box is free-running, not stepped to the
# readout's 8192-frame block: the preview throws every pass away, so a run that
# stops mid-block never leaves a replayed tail in a file anyone keeps.
_NFRAMES_TIP_STATS = (
    "This does not change the rate, only how well it is measured: the\n"
    "rate divides by the frames it counted, so more frames buy precision,\n"
    "not a bigger number. One photon is worth 1/(frames x shutter), and no\n"
    "pixel can read between two multiples of that — which is why a short\n"
    "pass makes the median and the colourbar top jump while the mean,\n"
    "shown first, holds steady."
)
_NFRAMES_TIP_32 = (
    "Frames captured per acquisition; every one of them is counted into\n"
    "the previewed hitmap.\n"
    "More frames = smoother map, slower refresh.\n" + _NFRAMES_TIP_STATS
)
_NFRAMES_TIP_64 = (
    "Frames captured per quadrant acquisition (x4 per composite frame,\n"
    "one per S0C/S1C/S2C/S3C); every one of them is counted into the\n"
    "previewed hitmap.\n"
    "Lower this for a faster refresh.\n" + _NFRAMES_TIP_STATS
)

# Mouse zoom on the map: each wheel notch shows this fraction of the view's
# width, and the view never narrows below a few pixels across.
_ZOOM_STEP = 0.8
_MIN_VIEW_PIXELS = 4


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
        # Cached plot artists; rebuilt only on shape/canvas-size change so a
        # window resize (or fullscreen) doesn't force a full rebuild+double
        # redraw on every single incoming frame.
        self._plot_ax = None
        self._plot_im = None
        self._plot_cb = None
        self._plot_shape = None
        self._plot_canvas_size = None
        self._plot_clabel = None  # colourbar units currently drawn
        self._plot_marks = None  # the crosses over masked pixels
        # The last hitmap drawn, so a change of mask redraws it at once
        # instead of waiting for the next pass (or for ever, once stopped).
        self._last_payload: dict | None = None
        # Mouse-drag pan in progress: start position and the view it began on.
        self._pan = None
        # Boards the mask was last saved for or loaded from, offered again
        # the next time it is saved.
        self._mask_boards = ("", "")
        # (program, firmware) pair this tab last programmed; shared with the
        # other tabs via fpga_state so nobody acts on a stale belief.
        self._pwr_mgt_state: tuple[str, str] | None = None
        self._pwr_mgt_pending_state: tuple[str, str] | None = None
        self._startup_complete = False
        self._build_ui()
        self._populate_programs()
        self._on_firmware_change()  # apply the default firmware's shutter rules
        self.program_combo.currentIndexChanged.connect(self._on_program_change)
        self.firmware_combo.currentIndexChanged.connect(self._on_firmware_change)
        # _on_mode_change's 32x32 branch calls _on_program_change, which
        # would otherwise auto-fire a real Power Mgt run during widget
        # construction, before the user has done anything.
        self._on_mode_change(self.mode_combo.currentIndex())
        self._startup_complete = True
        theme_manager().changed.connect(self._apply_theme)

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

        # The preview's rate divides by the frame length, and the frame length
        # depends on the firmware -- 9 µs fixed, or shutter + 9 µs. Without
        # knowing which, the colourbar would be a number with no defensible
        # unit, which is what reading it out of frame_rate_cnt.txt used to be.
        params.addWidget(QLabel("Firmware:"))
        self.firmware_combo = QComboBox()
        self.firmware_combo.setMinimumWidth(175)
        self.firmware_combo.setToolTip(FIRMWARE_TIP)
        for version, text in (
            (FIRMWARE_SHORT_EXPOSURE, "short_exposure"),
            (FIRMWARE_LONG_EXPOSURE, "long_exposure"),
        ):
            missing = firmware_bitfile(version) is None
            self.firmware_combo.addItem(
                text + ("   [bitstream missing]" if missing else ""),
                userData=version,
            )
        params.addWidget(self.firmware_combo)

        params.addWidget(QLabel("Frames/acq:"))
        self.nframes_spin = QSpinBox()
        self.nframes_spin.setRange(1, FRAME_MAX)
        # Not the acquisition tabs' 16 384, and not stepped to their 8192
        # block: this is a preview that reacquires every pass, so the frame
        # count is a refresh-rate choice, not a file-layout one.
        self.nframes_spin.setValue(1000)
        self.nframes_spin.setSingleStep(100)
        self.nframes_spin.setFixedWidth(90)
        self.nframes_spin.setToolTip(_NFRAMES_TIP_32)
        params.addWidget(self.nframes_spin)

        self.exp_label = QLabel("Shutter:")
        params.addWidget(self.exp_label)
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.0, FRAME_READOUT_US)
        self.exp_spin.setDecimals(3)
        self.exp_spin.setValue(0.2)
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setFixedWidth(110)
        params.addWidget(self.exp_spin)

        self.frame_label = QLabel()
        self.frame_label.setObjectName("monoLabel")
        self.frame_label.setToolTip(
            "One frame's length, from the firmware and the shutter time.\n"
            "The previewed rate does not divide by this but by the live\n"
            "(shutter-open) part of it, as dapkel does — under\n"
            "short_exposure the rest of the frame is readout."
        )
        params.addWidget(self.frame_label)

        self.nframes_spin.valueChanged.connect(self._on_live_param_change)
        self.exp_spin.valueChanged.connect(self._on_live_param_change)
        self.exp_spin.valueChanged.connect(self._refresh_frame_label)

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
        theme = current_theme()
        self.figure = Figure(tight_layout=True, facecolor=theme.figure_bg)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setStyleSheet(f"background: {theme.figure_bg}; border: none;")
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.canvas.setToolTip(
            "Ctrl+click a pixel to mask or unmask it.\n"
            "Scroll to zoom, drag to pan, double-click for the full map."
        )
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)

        # ---- Pixel mask, beside the toolbar ----
        self.mask_window = PixelMaskWindow(self)
        self.mask_window.changed.connect(self._on_mask_changed)
        plot_bar = QHBoxLayout()
        plot_bar.addWidget(self.toolbar)
        plot_bar.addStretch()
        self.mask_label = QLabel(self.mask_window.summary())
        self.mask_label.setToolTip(
            "Masked pixels are drawn blank with a cross and left out of the\n"
            "colour scale, the mean/median/max and the peak occupancy.\n"
            "Ctrl+click a pixel on the map to mask or unmask it."
        )
        edit_mask_btn = QPushButton("Edit mask…")
        edit_mask_btn.setToolTip(
            "Open the pixel mask in a window of its own; it can stay open\n"
            "beside the map while the preview runs."
        )
        edit_mask_btn.clicked.connect(self.mask_window.open_beside)
        reset_mask_btn = QPushButton("Reset mask")
        reset_mask_btn.setToolTip("Unmask every pixel of the map in view.")
        reset_mask_btn.clicked.connect(self.mask_window.clear)
        save_mask_btn = QPushButton("Save mask…")
        save_mask_btn.setToolTip(
            "Save the mask of the map in view for one daughterboard and\n"
            f"motherboard, as e.g. D0_M0.json in\n{masks_dir()}"
        )
        save_mask_btn.clicked.connect(self._save_mask)
        load_mask_btn = QPushButton("Load mask…")
        load_mask_btn.setToolTip(
            "Replace the mask of the map in view with one saved earlier."
        )
        load_mask_btn.clicked.connect(self._load_mask)
        plot_bar.addWidget(self.mask_label)
        plot_bar.addWidget(edit_mask_btn)
        plot_bar.addWidget(reset_mask_btn)
        plot_bar.addWidget(save_mask_btn)
        plot_bar.addWidget(load_mask_btn)
        root.addLayout(plot_bar)
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
        # Each mode keeps its own mask: (5, 12) is a different SPAD in each.
        self.mask_window.set_shape(*((64, 64) if is_64 else (32, 32)))
        self.mask_label.setText(self.mask_window.summary())
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

    def _firmware(self) -> str:
        return self.firmware_combo.currentData() or FIRMWARE_SHORT_EXPOSURE

    def _on_firmware_change(self, _idx: int = 0):
        """Re-label the shutter box for the new firmware, then reprogram."""
        ui = EXP_UI[self._firmware()]
        self.exp_label.setText(ui["label"])
        self.exp_spin.setToolTip(ui["tip"])
        before = self.exp_spin.value()
        self.exp_spin.setMaximum(ui["maximum"])
        after = self.exp_spin.value()
        if after != before:
            self.status_label.setText(
                f"Shutter capped at {after:.3f} µs by {self._firmware()} "
                f"(was {before:.3f} µs)."
            )
        self._refresh_frame_label()
        self._on_live_param_change()
        self._on_program_change(self.program_combo.currentIndex())

    def _refresh_frame_label(self):
        """Show the frame length the previewed rate divides by."""
        frame_us = (
            self.exp_spin.value() + FRAME_READOUT_US
            if self._firmware() == FIRMWARE_LONG_EXPOSURE
            else FRAME_READOUT_US
        )
        self.frame_label.setText(f"{frame_us:.3f} µs/frame")

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

        if (current, self._firmware()) == self._pwr_mgt_state:
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

        firmware = self._firmware()
        cwd, bitfile = resolve_pwr_mgt_cwd(firmware)
        if bitfile is None:
            self.status_label.setText(
                f"⚠  No {BITFILE_NAME} for {firmware}, nor in the legacy folder."
            )
            return

        self.pwr_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.program_combo.setEnabled(False)
        self.firmware_combo.setEnabled(False)
        self.status_label.setText(f"Initialising FPGA ({firmware})…")

        self._pwr_mgt_pending_state = (program_path, firmware)
        self._pwr_worker = PowerMgtWorker(self._exe_dir, program_path, cwd)
        self._pwr_worker.finished.connect(self._on_pwr_mgt_finished)
        self._pwr_worker.start()

    def _on_pwr_mgt_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        self.program_combo.setEnabled(True)
        self.firmware_combo.setEnabled(True)
        if success:
            self._pwr_mgt_state = self._pwr_mgt_pending_state
            FPGA.set_loaded(*self._pwr_mgt_pending_state)
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
            # 64x64 reprograms per quadrant inside the worker loop, so from now
            # on what is loaded is whichever quadrant ran last. Unknown is the
            # honest answer; see fpga_state.
            FPGA.clear()
            self._pwr_mgt_state = None
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
                "pwr_cwd": resolve_pwr_mgt_cwd(self._firmware())[0],
                "firmware_version": self._firmware(),
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
                "firmware_version": self._firmware(),
                # The program decides the reduction: summing the counts field
                # of a timestamp program would sum coarse-timestamp bits.
                "hitmap_mode": mode_for_program(program_path),
            }

        self._frame_count = 0
        # Force a clean rebuild for this run. The shape is kept, so a run on
        # the same map keeps the zoom the last one was left at.
        self._plot_im = None
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

    def _apply_theme(self):
        """Recolour the hitmap on screen for a theme just chosen.

        Recoloured in place rather than redrawn: while a run is going the next
        frame replaces it within a second anyway. Forgetting the canvas size
        makes that next frame take the full rebuild, so a new plot font size
        gets its layout pass too.
        """
        theme = current_theme()
        self.canvas.setStyleSheet(f"background: {theme.figure_bg}; border: none;")
        restyle_figure(self.figure, theme)
        if self._plot_marks is not None:
            self._plot_marks.set_color(theme.axes_fg)
        self._plot_canvas_size = None
        self.canvas.draw_idle()

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
        # Same map, same zoom: a rebuild for a resized window or a new
        # colourbar unit must not throw away where the map was zoomed to.
        keep = None
        if self._plot_ax is not None and self._plot_shape == (rows, cols):
            keep = (self._plot_ax.get_xlim(), self._plot_ax.get_ylim())
        self._pan = None
        self.figure.clear()
        self.figure.set_tight_layout(True)
        ax = self.figure.add_subplot(111)
        theme = current_theme()
        im = ax.imshow(
            data,
            cmap=theme.colormap,
            aspect="equal",
            origin="lower",
            vmin=clim[0],
            vmax=clim[1],
        )
        # A cross on each masked pixel, which imshow leaves blank. Not
        # scaling the axes to it keeps the image's own limits.
        (marks,) = ax.plot(
            [],
            [],
            linestyle="none",
            marker="x",
            color=theme.axes_fg,
            scalex=False,
            scaley=False,
        )
        cb = self.figure.colorbar(im, ax=ax, label=clabel)
        cb.ax.tick_params(colors=theme.axes_fg)
        cb.ax.yaxis.label.set_color(theme.axes_fg)
        cb.outline.set_edgecolor(theme.axes_edge)
        ax.set_title(title, color=theme.axes_fg)
        ax.set_xlabel("Column", color=theme.axes_fg)
        ax.set_ylabel("Row", color=theme.axes_fg)
        ax.tick_params(colors=theme.axes_fg)
        # The dark theme turns the grid on globally; over a hitmap it just
        # draws lines across the pixels, so keep the image clean.
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_edgecolor(theme.axes_edge)

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

        # Home on the toolbar returns to this full view. Recorded only now,
        # after the centering, because Home restores the axes' positions
        # along with their limits.
        self.toolbar.update()
        self.toolbar.push_current()
        if keep is not None:
            ax.set_xlim(keep[0])
            ax.set_ylim(keep[1])

        self._plot_ax = ax
        self._plot_im = im
        self._plot_cb = cb
        self._plot_marks = marks
        self._plot_shape = (rows, cols)
        self._plot_canvas_size = (self.canvas.width(), self.canvas.height())
        self._plot_clabel = clabel

    def _on_frame(self, payload: dict):
        """Count and keep one accumulated hitmap emitted by the worker, then
        draw it."""
        self._frame_count += 1
        self._last_payload = payload
        self._render(payload)

    def _render(self, payload: dict):
        """Draw one accumulated hitmap, with the current mask applied.

        ``payload`` carries the reduced map plus what is needed to normalise
        it: the reduction mode, the number of frames that carried data, and
        the live seconds per frame. The map is shown as a photon rate
        whenever that live time is known — the same quantity the offline
        'hitmap_analysis' rate map plots.
        """
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

        # Masked pixels are left out of everything read off the map -- the
        # colour scale, the stats, the peak occupancy -- and drawn blank with
        # a cross, so a hot pixel stops setting the scale once it is masked.
        self.mask_window.set_shape(rows, cols)
        masked = self.mask_window.mask_for(rows, cols)
        n_masked = int(masked.sum())
        shown = data[~masked]
        if not shown.size:
            shown = np.zeros(1)  # every pixel masked: nothing left to scale to

        # Full measured range of the unmasked pixels: each is drawn as
        # counted, hot ones included. Nothing is clipped and the scale is not
        # carried over between refreshes.
        clim = color_limits(shown)
        canvas_size = (self.canvas.width(), self.canvas.height())

        mean = float(np.mean(shown))
        median = float(np.median(shown))
        peak = float(shown.max())
        step = self._rate_step(rate, frames, payload["live_per_frame"])
        frames_txt = self._frames_text(frames, frames_req)
        # Only in timestamp mode is the hitmap an occupancy with a ceiling of
        # one; count mode sums real counts, so the ratio would be a fraction
        # of nothing. See 'peak_occupancy'. A masked pixel counts as never
        # having fired, so it cannot be named the busiest.
        occ = (
            None
            if mode == MODE_COUNT
            else peak_occupancy(np.where(masked, 0.0, hitmap), frames)
        )
        # On the first line, not with the stats: the second line already runs
        # close to the colourbar's exponent label. Stated as a bare number,
        # with no word judging it -- where the response stops being linear
        # enough for the work is the operator's call, not this tab's, and a
        # label like 'saturating' reads as 'pinned' when 64% is not.
        #
        # The coordinates are what make the number actionable: read against the
        # map, they say whether the busiest pixel is in the beam spot (the
        # shutter is too long for the signal) or alone in the dark field (a hot
        # pixel, and shortening the shutter would only cost signal). They are
        # the plotted Row/Column, so they read off the axes as printed.
        occ_txt = ""
        if occ is not None:
            frac, occ_row, occ_col = occ
            occ_txt = f", peak {frac:.1%} of frames"
            # A map where nothing fired has no busiest pixel -- 'peak 0.0% at
            # row 0, col 0' would point at a pixel that did nothing to earn it.
            if frac > 0:
                occ_txt += f" at row {occ_row}, col {occ_col}"
        # Mean first: it is the only one of the three that does not move with
        # the frame count. See '_rate_step' for why the other two do.
        # The colourbar spans the full range, so it already shows the scale --
        # no need to restate it here (and a long second line would run into
        # the colourbar's exponent label).
        title = (
            f"Live hitmap #{self._frame_count}  {rows}×{cols}   "
            f"{mode} mode{occ_txt}\n"
            f"{frames_txt}  ·  mean {mean:.3g}{unit}  ·  "
            f"median {median:.3g}{unit}  ·  max {peak:.3g}{unit}"
        )

        needs_rebuild = (
            self._plot_im is None
            or self._plot_shape != (rows, cols)
            or self._plot_canvas_size != canvas_size
            or self._plot_clabel != clabel
        )
        display = np.ma.masked_array(data, mask=masked)
        if needs_rebuild:
            self._rebuild_plot(display, rows, cols, clabel, clim, title)
        else:
            self._plot_im.set_data(display)
            self._plot_im.set_clim(*clim)
            self._plot_ax.set_title(title, color=current_theme().axes_fg)
        mark_rows, mark_cols = np.nonzero(masked)
        self._plot_marks.set_data(mark_cols, mark_rows)
        self.canvas.draw_idle()

        if not np.any(np.asarray(frames) > 0):
            self.status_label.setText(
                f"⚠  hitmap #{self._frame_count}: no frame carried data "
                f"({payload['frames_read']} read) — chip idle?"
            )
            return

        read = payload["frames_read"]
        status = (
            f"Live, hitmap #{self._frame_count}, "
            f"{frames_txt}, {payload['live_source']}, "
            f"mean {mean:.3g}{unit}, median {median:.3g}{unit}, "
            f"max {peak:.3g}{unit}"
        )
        if step is not None:
            status += f", one count = {step:.3g}{unit}"
        if occ is not None:
            # Spelled out here where there is room: the title's "peak" is one
            # named pixel's occupancy, not the array's and not a per-frame fill.
            frac, occ_row, occ_col = occ
            if frac > 0:
                status += (
                    f", pixel (row {occ_row}, col {occ_col}) fired in "
                    f"{frac:.1%} of its frames"
                )
            else:
                status += ", no pixel fired in any frame"
        if n_masked:
            status += f", {n_masked} masked pixel(s) left out"
        if read < frames_req:
            status += f"  [only {read} frames in the file]"
        self.status_label.setText(status)

    # ------------------------------------------------------------------
    # Pixel mask and mouse zoom
    # ------------------------------------------------------------------

    def _on_mask_changed(self):
        """Update the count and redraw the last map with the new mask."""
        self.mask_label.setText(self.mask_window.summary())
        if self._last_payload is not None:
            self._render(self._last_payload)

    def _save_mask(self):
        """Save the mask of the map in view under a daughterboard and
        motherboard, keeping the other map's mask already in that file."""
        pixels = self.mask_window.pixels()
        rows, cols = self.mask_window.shape
        if not pixels:
            QMessageBox.information(
                self, "Save mask", "No pixel is masked, so there is nothing to save."
            )
            return
        dlg = SaveMaskDialog(
            self, masks_dir(), len(pixels), (rows, cols), *self._mask_boards
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        db, mb = dlg.names()
        path = dlg.path()

        existing = None
        if os.path.isfile(path):
            try:
                existing = read_mask_file(path)
            except (OSError, ValueError) as err:
                answer = QMessageBox.question(
                    self,
                    "Save mask",
                    f"{path} exists but cannot be read as a mask ({err}).\n\n"
                    "Overwrite it?",
                )
                if answer != QMessageBox.Yes:
                    return
            else:
                before = existing["masks"].get(mask_key(rows, cols))
                if before is not None and sorted(map(tuple, before)) != pixels:
                    answer = QMessageBox.question(
                        self,
                        "Save mask",
                        f"{db}_{mb} already has a {rows}×{cols} mask of "
                        f"{len(before)} pixel(s).\n\nReplace it with these "
                        f"{len(pixels)}?",
                    )
                    if answer != QMessageBox.Yes:
                        return
        try:
            write_mask_file(path, db, mb, (rows, cols), pixels, existing)
        except OSError as err:
            QMessageBox.warning(self, "Save mask", f"Could not save the mask:\n{err}")
            return
        self._mask_boards = (db, mb)
        self.status_label.setText(
            f"Saved {len(pixels)} masked pixel(s) ({rows}×{cols}) to {path}"
        )

    def _load_mask(self):
        """Replace the mask of the map in view with a saved one."""
        rows, cols = self.mask_window.shape
        folder = masks_dir()
        paths = sorted(glob.glob(os.path.join(folder, "*.json")))
        if not paths:
            QMessageBox.information(
                self, "Load mask", f"No saved masks yet in\n{folder}"
            )
            return
        names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
        name, ok = QInputDialog.getItem(
            self,
            "Load mask",
            f"Mask for the {rows}×{cols} map, by daughterboard_motherboard:",
            names,
            0,
            False,
        )
        if not ok:
            return
        path = paths[names.index(name)]
        try:
            data = read_mask_file(path)
            pixels = saved_pixels(data, rows, cols)
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, "Load mask", f"Could not load {path}:\n{err}")
            return
        if pixels is None:
            saved = ", ".join(data["masks"]) or "none"
            QMessageBox.information(
                self,
                "Load mask",
                f"{name} has no {rows}×{cols} mask (saved: {saved}).",
            )
            return
        self.mask_window.replace(pixels)
        self._mask_boards = (
            data.get("daughterboard", ""),
            data.get("motherboard", ""),
        )
        self.status_label.setText(
            f"Loaded {len(pixels)} masked pixel(s) ({rows}×{cols}) from {path}"
        )

    def _full_view(self):
        """The axes limits that show the whole map, as imshow sets them."""
        rows, cols = self._plot_shape
        return (-0.5, cols - 0.5), (-0.5, rows - 0.5)

    @staticmethod
    def _clamp(lo: float, hi: float, full: tuple[float, float]):
        """Slide (lo, hi) back inside 'full', narrowing it only if wider."""
        width = min(hi - lo, full[1] - full[0])
        lo = min(max(lo, full[0]), full[1] - width)
        return lo, lo + width

    def _on_press(self, event):
        """Ctrl+click masks a pixel, double-click shows the full map, and a
        plain press starts a drag-pan."""
        ax = self._plot_ax
        if ax is None or event.inaxes is not ax or event.button != 1:
            return
        if self.toolbar.mode:
            return  # the toolbar's own pan or zoom tool has the mouse
        # Read from Qt, not event.key: matplotlib only learns of modifiers
        # through key events, which reach the canvas once it has focus, so the
        # first Ctrl+click after clicking elsewhere would look like a plain one.
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            rows, cols = self._plot_shape
            row, col = int(round(event.ydata)), int(round(event.xdata))
            if 0 <= row < rows and 0 <= col < cols:
                self.mask_window.toggle(row, col)
            return
        if event.dblclick:
            self._pan = None
            full_x, full_y = self._full_view()
            ax.set_xlim(full_x)
            ax.set_ylim(full_y)
            self.canvas.draw_idle()
            return
        self._pan = (event.x, event.y, ax.get_xlim(), ax.get_ylim())

    def _on_motion(self, event):
        """Drag-pan: move the view with the mouse, kept inside the map."""
        if self._pan is None or self._plot_ax is None:
            return
        x0, y0, xlim, ylim = self._pan
        ax = self._plot_ax
        # Pixels to data units. Panning only shifts the transform, never
        # scales it, so the difference of two points is the same throughout.
        start, now = ax.transData.inverted().transform(
            [(x0, y0), (event.x, event.y)]
        )
        dx, dy = now - start
        full_x, full_y = self._full_view()
        ax.set_xlim(self._clamp(xlim[0] - dx, xlim[1] - dx, full_x))
        ax.set_ylim(self._clamp(ylim[0] - dy, ylim[1] - dy, full_y))
        self.canvas.draw_idle()

    def _on_release(self, _event):
        self._pan = None

    def _on_scroll(self, event):
        """Wheel zoom about the pixel under the mouse."""
        ax = self._plot_ax
        if ax is None or event.inaxes is not ax:
            return
        scale = _ZOOM_STEP**event.step  # wheel up (step > 0) zooms in
        views = []
        for (lo, hi), centre, full in (
            (ax.get_xlim(), event.xdata, self._full_view()[0]),
            (ax.get_ylim(), event.ydata, self._full_view()[1]),
        ):
            width = min(
                max((hi - lo) * scale, _MIN_VIEW_PIXELS), full[1] - full[0]
            )
            # The point under the mouse stays under the mouse.
            lo = centre - (centre - lo) / (hi - lo) * width
            views.append(self._clamp(lo, lo + width, full))
        ax.set_xlim(views[0])
        ax.set_ylim(views[1])
        self.canvas.draw_idle()

    @staticmethod
    def _rate_step(
        rate, frames, live_per_frame: float | None
    ) -> float | None:
        """What one photon is worth on the rate map, in the rate's own unit.

        A pixel that fired ``k`` times in ``N`` frames reads ``k / (N * live)``,
        so the whole map is a grid of this step and no pixel can land between
        two of its rungs. That is the entire reason the median and the
        colourbar top move when the frame count changes while the light does
        not: at 200 ns shutter one count is 100 kHz over 50 frames but 610 Hz
        over 8192, against a typical pixel of a few kHz — so a short pass
        rounds most pixels to 0 or to one whole rung. The mean over the array
        averages the rounding away and holds steady; these two cannot.

        Returns None when no rate is being shown, or when the map is per-pixel
        (64x64 mode) with no frame count above zero. In 64x64 mode the
        quadrants have their own frame counts, so the coarsest one is used --
        the step the operator would notice first.
        """
        if rate is None or not live_per_frame:
            return None
        counted = np.asarray(frames, dtype=np.float64)
        counted = counted[counted > 0]
        if not counted.size:
            return None
        return 1.0 / (float(counted.min()) * live_per_frame)

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
