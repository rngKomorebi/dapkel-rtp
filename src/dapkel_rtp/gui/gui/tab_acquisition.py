"""Tab 1 — Acquisition (compact layout).

The output folder is the primary, prominent control. All other acquisition
parameters live in a compact single-row toolbar. Chip configuration is
accessed via the Settings dialog (rarely changed in practice).
"""

import glob
import os

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dapkel_rtp.functions.timing import CLK_PERIOD, FRAME_READOUT_S

from ._paths import (
    BITFILE_NAME,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    firmware_bitfile,
    functions_dir,
    programs_dir,
    resolve_pwr_mgt_cwd,
)
from .fpga_state import FPGA
from .widgets import FRAMES_TIP_BLOCK, make_nframes_combo
from .worker import CLK_SHIFT, NBITS, AcquisitionWorker, PowerMgtWorker

# Microseconds, for the spin boxes; functions.timing owns the value.
FRAME_READOUT_US = FRAME_READOUT_S * 1e6

# What the Exposure box means, per firmware. Under short_exposure the frame is
# a fixed 9 µs and the shutter opens inside it, so a value above 9 µs is not a
# longer exposure -- it is meaningless, hence the cap. Under long_exposure the
# firmware adds the 9 µs readout to whatever the shutter time is.
EXP_UI = {
    FIRMWARE_SHORT_EXPOSURE: {
        "label": "Shutter:",
        "maximum": FRAME_READOUT_US,
        "tip": (
            "How long the shutter is open inside the fixed 9 µs frame, set\n"
            "directly: whatever you enter here is what the register gets,\n"
            "e.g. 0.2 µs → 200 ns. Readout takes the rest of the frame:\n"
            "readout = 9 µs - shutter, so the frame is 9 µs regardless.\n"
            "Capped at 9 µs because a longer shutter has nowhere to go in\n"
            "this firmware -- switch to long_exposure for that.\n"
            "(Requires external_frame_trigger OFF in Settings -- that's a\n"
            "separate SMA hardware-sync feature.)"
        ),
    },
    FIRMWARE_LONG_EXPOSURE: {
        "label": "Shutter X:",
        "maximum": 1_000_000.0,
        "tip": (
            "How long the shutter is open, set directly. This firmware adds\n"
            "9 µs of readout on top, so the frame is X + 9 µs and the run\n"
            "takes correspondingly longer -- watch the frame time shown\n"
            "beside this box before starting a long acquisition.\n"
            "(Requires external_frame_trigger OFF in Settings -- that's a\n"
            "separate SMA hardware-sync feature.)"
        ),
    },
}

FIRMWARE_TIP = (
    "Which FPGA bitstream to load. Changing this reprograms the FPGA\n"
    "immediately, exactly as changing the program does -- the bitstream is\n"
    "only loaded by Power Mgt, so a selection that has not been programmed\n"
    "would be a claim about a combo box rather than about the hardware.\n"
    "\n"
    "short_exposure: the frame is always 9 µs; the shutter opens for part\n"
    "of it (50-500 ns in practice).\n"
    "long_exposure: the frame is shutter + 9 µs.\n"
    "\n"
    "Recorded in metadata.json together with the bitstream's SHA-256."
)

BIAS_TIP = (
    "SPAD bias voltage, for the record only -- the app cannot set it, you\n"
    "still dial it on the supply. Written to metadata.json, which is the\n"
    "first time this number has been recorded anywhere machine-readable\n"
    "(until now it lived only in folder names like '22V').\n"
    "Set it to 0 to leave it blank in the record rather than guess."
)


# ---------------------------------------------------------------------------
# Settings dialog  (chip configuration + exe directory)
# ---------------------------------------------------------------------------


class SettingsDialog(QDialog):
    """Chip-config bits and Kelpie_v2.exe directory."""

    _BITS = [
        ("chip_debug",        "chip_debug"),
        ("chip_timing",       "chip_timing  (external trigger)"),
        ("clk_shift",         "clk_shift"),
        ("chip_artif_rdout",  "chip_artif_rdout"),
        ("single_shot_noise", "single_shot_noise"),
        ("memory_select0",    "memory_select0"),
        ("memory_select1",    "memory_select1"),
        ("debug_last_row",    "debug_last_row"),
        ("external_frame_trigger", "external_frame_trigger  (wait for SMA sync trigger)"),
    ]

    # Extra guidance for bits whose behavior isn't obvious from the label
    # alone; shown as a tooltip on that checkbox specifically.
    _TOOLTIPS = {
        "external_frame_trigger": (
            "When checked: each frame's acquisition starts on an external\n"
            "trigger pulse (SMA input) instead of free-running. With N\n"
            "frames set, the acquisition only completes once you've supplied\n"
            "N trigger pulses -- each pulse must be spaced >9 µs apart from\n"
            "the last (to let one frame's readout finish before the next\n"
            "trigger arrives). Exposure time itself can be set as low as 5 ns.\n"
            "When unchecked: free-running as before, same ~5 ns exposure floor."
        ),
    }

    def __init__(self, chip_state: dict, exe_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(320)
        root = QVBoxLayout(self)

        # ---- Chip configuration (each row is a full QCheckBox — entire row clickable) ----
        chip_grp = QGroupBox("Chip Configuration")
        chip_lay = QVBoxLayout(chip_grp)

        self._cbs: dict = {}
        for key, label in self._BITS:
            cb = QCheckBox(label)
            cb.setChecked(bool(chip_state.get(key, False)))
            cb.toggled.connect(self._refresh_label)
            if key in self._TOOLTIPS:
                cb.setToolTip(self._TOOLTIPS[key])
            self._cbs[key] = cb
            chip_lay.addWidget(cb)

        config_row = QHBoxLayout()
        config_row.addWidget(QLabel("chip_config ="))
        self._config_label = QLabel()
        self._config_label.setStyleSheet(
            "font-family: Consolas, monospace; font-weight: bold;"
        )
        config_row.addWidget(self._config_label)
        config_row.addStretch()
        chip_lay.addLayout(config_row)
        root.addWidget(chip_grp)

        # ---- Exe directory ----
        exe_grp = QGroupBox("Kelpie_v2.exe Directory")
        exe_lay = QHBoxLayout(exe_grp)
        self._exe_edit = QLineEdit(exe_dir)
        exe_btn = QPushButton("Browse…")
        exe_btn.setFixedWidth(75)
        exe_btn.clicked.connect(self._browse_exe)
        exe_lay.addWidget(self._exe_edit)
        exe_lay.addWidget(exe_btn)
        root.addWidget(exe_grp)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._refresh_label()

    def _browse_exe(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Kelpie_v2.exe Directory", self._exe_edit.text()
        )
        if d:
            self._exe_edit.setText(d)

    def _compute_config(self) -> int:
        c = self._cbs
        return (
            int(c["external_frame_trigger"].isChecked()) << 8
            | int(c["debug_last_row"].isChecked()) << 7
            | int(c["memory_select1"].isChecked()) << 6
            | int(c["memory_select0"].isChecked()) << 5
            | int(c["single_shot_noise"].isChecked()) << 4
            # bit 3 reserved/unused
            | int(c["chip_artif_rdout"].isChecked()) << 2
            | int(c["chip_timing"].isChecked()) << 1
            | int(c["chip_debug"].isChecked())
        )

    def _refresh_label(self):
        self._config_label.setText(str(self._compute_config()))

    def chip_state(self) -> dict:
        return {k: cb.isChecked() for k, cb in self._cbs.items()}

    def chip_config(self) -> int:
        return self._compute_config()

    def exe_dir(self) -> str:
        return self._exe_edit.text()


# ---------------------------------------------------------------------------
# Acquisition tab
# ---------------------------------------------------------------------------


class AcquisitionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: AcquisitionWorker | None = None
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
        # What is loaded on the FPGA is shared state, not this tab's -- Live
        # View and the chain tab reprogram it too (see fpga_state). Only the
        # in-flight request is local.
        self._pwr_mgt_pending_state: tuple[str, str] | None = None
        self._build_ui()
        self._populate_programs()
        self._on_exp_context_change()
        # Connected after the initial population settles, so app startup
        # doesn't auto-trigger a Power Mgt run before the user does anything.
        self.program_combo.currentIndexChanged.connect(self._on_program_change)
        self.firmware_combo.currentIndexChanged.connect(self._on_firmware_change)
        for spin in (self.exp_spin, self.nacq_spin):
            spin.valueChanged.connect(self._refresh_frame_label)
        self.nframes_combo.currentIndexChanged.connect(self._refresh_frame_label)
        FPGA.changed.connect(self._on_fpga_changed)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- Output folder (prominent) ----
        out_grp = QGroupBox("Output Folder")
        out_lay = QHBoxLayout(out_grp)
        out_lay.setContentsMargins(8, 6, 8, 8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(
            "Select output folder for .bin files…"
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

        params.addWidget(QLabel("Program:"))
        self.program_combo = QComboBox()
        self.program_combo.setMinimumWidth(130)
        params.addWidget(self.program_combo)

        params.addWidget(QLabel("Frames:"))
        # 16 384 = 2 x REPLAY_BLOCK_FRAMES, so the file holds exactly what was
        # asked for: the readout's 16 MiB quantum is filled and no slot is a
        # replay of an earlier one (which is what a 10 000-frame run gets).
        self.nframes_combo = make_nframes_combo()
        self.nframes_combo.setToolTip(
            "Frames per .bin file.\n" + FRAMES_TIP_BLOCK
        )
        params.addWidget(self.nframes_combo)

        params.addWidget(QLabel("#Acq:"))
        self.nacq_spin = QSpinBox()
        self.nacq_spin.setRange(1, 100_000)
        self.nacq_spin.setValue(10)
        self.nacq_spin.setFixedWidth(70)
        params.addWidget(self.nacq_spin)

        self.exp_label = QLabel("Shutter:")
        params.addWidget(self.exp_label)
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.0, FRAME_READOUT_US)
        self.exp_spin.setDecimals(3)
        self.exp_spin.setValue(0.0)
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setFixedWidth(110)
        params.addWidget(self.exp_spin)

        params.addWidget(QLabel("File:"))
        self.filename_edit = QLineEdit("data")
        self.filename_edit.setFixedWidth(90)
        self.filename_edit.setToolTip(
            "Output filename prefix (e.g. 'data' → data1.bin, data2.bin, …)"
        )
        params.addWidget(self.filename_edit)

        start_num_label = QLabel("Start#:")
        start_num_label.setMinimumWidth(start_num_label.sizeHint().width())
        params.addWidget(start_num_label)
        self.start_num_spin = QSpinBox()
        self.start_num_spin.setRange(1, 1_000_000)
        self.start_num_spin.setValue(1)
        self.start_num_spin.setFixedWidth(80)
        self.start_num_spin.setToolTip(
            "Number to start the filename suffix from. Leave at 1 for a\n"
            "fresh run, or set to one past your last file (e.g. 535 if you\n"
            "stopped at data_ORT534.bin) to continue an interrupted run\n"
            "without overwriting existing files."
        )
        params.addWidget(self.start_num_spin)

        params.addStretch()

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedWidth(120)
        settings_btn.clicked.connect(self._open_settings)
        params.addWidget(settings_btn)

        root.addLayout(params)

        # ---- Firmware / derived frame time / bias ----
        # Second row rather than more widgets in the first: the firmware is rig
        # state (one bitstream is loaded at a time), the frame time is derived
        # from it, and the bias is a note for the record. Grouping them keeps
        # the cause next to its effect.
        fw_row = QHBoxLayout()
        fw_row.setSpacing(8)

        fw_row.addWidget(QLabel("Firmware:"))
        self.firmware_combo = QComboBox()
        self.firmware_combo.setMinimumWidth(200)
        self.firmware_combo.setToolTip(FIRMWARE_TIP)
        for version, text in (
            (FIRMWARE_SHORT_EXPOSURE, "short_exposure  (9 µs frame)"),
            (FIRMWARE_LONG_EXPOSURE, "long_exposure  (shutter + 9 µs)"),
        ):
            missing = firmware_bitfile(version) is None
            self.firmware_combo.addItem(
                text + ("   [bitstream missing]" if missing else ""),
                userData=version,
            )
        fw_row.addWidget(self.firmware_combo)

        self.frame_label = QLabel()
        self.frame_label.setStyleSheet(
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        self.frame_label.setToolTip(
            "One frame's length, derived from the firmware and the shutter\n"
            "time — and the run's total camera time at the current frame\n"
            "count. Worth a glance before a long acquisition: it is the\n"
            "number that says whether a run takes 0.1 s or 100 s."
        )
        fw_row.addWidget(self.frame_label)

        fw_row.addSpacing(16)
        fw_row.addWidget(QLabel("Bias:"))
        self.bias_spin = QDoubleSpinBox()
        self.bias_spin.setRange(0.0, 100.0)
        self.bias_spin.setDecimals(2)
        self.bias_spin.setValue(22.0)
        self.bias_spin.setSuffix(" V")
        self.bias_spin.setSpecialValueText("")  # 0 shows blank → null on record
        self.bias_spin.setFixedWidth(90)
        self.bias_spin.setToolTip(BIAS_TIP)
        fw_row.addWidget(self.bias_spin)

        fw_row.addStretch()

        self.fpga_label = QLabel()
        self.fpga_label.setStyleSheet(f"color: {'#849495'};")
        fw_row.addWidget(self.fpga_label)

        root.addLayout(fw_row)

        # ---- Power management / Run / Abort ----
        btn_row = QHBoxLayout()

        self.pwr_btn = QPushButton("⚡  Power Mgt")
        self.pwr_btn.setObjectName("pwr_btn")
        self.pwr_btn.setFixedHeight(46)
        self.pwr_btn.setFixedWidth(150)
        self.pwr_btn.setToolTip("Initialise FPGA via Kelpie_v2_pwr_mgt.exe")
        self.pwr_btn.clicked.connect(self._run_pwr_mgt)

        self.run_btn = QPushButton("▶   Run Acquisition")
        self.run_btn.setObjectName("run_btn")
        self.run_btn.setFixedHeight(46)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip("Run Power Mgt first to activate acquisition")
        self.run_btn.clicked.connect(self._run)

        self.abort_btn = QPushButton("■   Abort")
        self.abort_btn.setObjectName("abort_btn")
        self.abort_btn.setFixedHeight(46)
        self.abort_btn.setFixedWidth(130)
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self._abort)

        btn_row.addWidget(self.pwr_btn)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.abort_btn)
        root.addLayout(btn_row)

        # ---- Progress ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(22)
        root.addWidget(self.progress_bar)

        # ---- Log ----
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(320)
        root.addWidget(self.log_edit, stretch=1)

    def _populate_programs(self):
        prog_dir = programs_dir()
        if os.path.isdir(prog_dir):
            for fp in sorted(
                glob.glob(os.path.join(prog_dir, "program_*.txt"))
            ):
                self.program_combo.addItem(os.path.basename(fp), userData=fp)
            for i in range(self.program_combo.count()):
                if "S3C" in self.program_combo.itemText(i):
                    self.program_combo.setCurrentIndex(i)
                    break
        self.folder_edit.setText(os.path.join(functions_dir(), "data"))

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

    # ------------------------------------------------------------------
    # Firmware, exposure semantics and derived timing
    # ------------------------------------------------------------------

    def _firmware(self) -> str:
        return self.firmware_combo.currentData() or FIRMWARE_SHORT_EXPOSURE

    def _on_firmware_change(self, _idx: int = 0):
        """Relabel the shutter box for the new firmware, then reprogram.

        Both halves matter: the same register means a different thing in each
        firmware, and the bitstream is only loaded by Power Mgt, so a selection
        that has not been programmed is not yet true of the hardware.
        """
        clamped = self._on_exp_context_change()
        self._on_program_change()
        if clamped is not None:
            # Logged after the reprogram, not before: _run_pwr_mgt clears the
            # log, which would swallow this. Never silently -- the operator
            # entered a number and got another one.
            before, after = clamped
            self._log(
                f"Shutter time capped at {after:.3f} µs by "
                f"{self._firmware()} (was {before:.3f} µs)."
            )

    def _on_exp_context_change(self) -> tuple[float, float] | None:
        """Apply the current firmware's meaning to the shutter box.

        Returns ``(before, after)`` when the new cap moved the value, so the
        caller can report it, else None.
        """
        ui = EXP_UI[self._firmware()]
        self.exp_label.setText(ui["label"])
        self.exp_spin.setToolTip(ui["tip"])
        before = self.exp_spin.value()
        self.exp_spin.setMaximum(ui["maximum"])
        after = self.exp_spin.value()
        self._refresh_frame_label()
        self._refresh_fpga_label()
        return (before, after) if after != before else None

    def _refresh_frame_label(self):
        """Show the derived frame length and the run's total camera time."""
        shutter_us = self.exp_spin.value()
        frame_us = (
            shutter_us + FRAME_READOUT_US
            if self._firmware() == FIRMWARE_LONG_EXPOSURE
            else FRAME_READOUT_US
        )
        total_s = (
            frame_us
            * 1e-6
            * self.nframes_combo.currentData()
            * self.nacq_spin.value()
        )
        self.frame_label.setText(
            f"frame = {frame_us:.3f} µs   ·   run = {total_s:.4g} s camera time"
        )

    def _on_fpga_changed(self):
        """Another tab reprogrammed the FPGA: stop claiming it is ready.

        Deliberately does not reprogram — two tabs reacting to the same signal
        would race to drive one board. Reprogramming stays a consequence of a
        user action on the tab in front of them.
        """
        self._refresh_fpga_label()
        busy = (self._worker is not None and self._worker.isRunning()) or (
            self._pwr_worker is not None and self._pwr_worker.isRunning()
        )
        if busy:
            return
        ready = FPGA.loaded == (
            self.program_combo.currentData(),
            self._firmware(),
        )
        self.run_btn.setEnabled(ready)
        self.run_btn.setToolTip(
            ""
            if ready
            else "The FPGA was reprogrammed on another tab — run Power Mgt "
            "again before acquiring."
        )

    def _refresh_fpga_label(self):
        """Say what is actually loaded, not what is selected."""
        if FPGA.loaded is None:
            self.fpga_label.setText("FPGA: not programmed this session")
            return
        program, firmware = FPGA.loaded
        self.fpga_label.setText(
            f"FPGA: {firmware} · {os.path.basename(program)}"
        )

    # ------------------------------------------------------------------
    # Power management
    # ------------------------------------------------------------------

    def _on_program_change(self, _idx: int = 0):
        """Auto-run Power Mgt whenever the program or firmware actually
        changes, since the FPGA must be reprogrammed for either; Power Mgt
        is no longer something you have to remember to click first."""
        if self._worker is not None and self._worker.isRunning():
            return  # acquisition in progress; ignore
        if self._pwr_worker is not None and self._pwr_worker.isRunning():
            return  # a Power Mgt run is already in flight

        program_path = self.program_combo.currentData()
        if program_path is None:
            return

        if (program_path, self._firmware()) == FPGA.loaded:
            self.run_btn.setEnabled(True)
            self.run_btn.setToolTip("")
        else:
            self._run_pwr_mgt()

    def _run_pwr_mgt(self):
        program_path = self.program_combo.currentData()
        if not program_path or not os.path.isfile(program_path):
            self._log("ERROR: Program file not found.")
            return

        firmware = self._firmware()
        cwd, bitfile = resolve_pwr_mgt_cwd(firmware)
        if bitfile is None:
            self._log(
                f"ERROR: no {BITFILE_NAME} for {firmware}, and none in the "
                f"legacy folder either. Put one in "
                f"{os.path.join(cwd, 'bitfile')}."
            )
            return

        self.pwr_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.program_combo.setEnabled(False)
        self.firmware_combo.setEnabled(False)
        self.log_edit.clear()
        self._log(f"--- Power management initialisation ({firmware}) ---")
        if firmware_bitfile(firmware) is None:
            # The selection cannot be honoured, so say so rather than let the
            # log imply the requested firmware was loaded.
            self._log(
                f"  ! no bitstream at params/camera/{firmware}/bitfile/"
                f"{BITFILE_NAME} — falling back to the legacy one. The "
                "firmware in metadata.json is then your selection, not an "
                "observation."
            )
        self._log(f"  bitstream: {bitfile}")

        self._pwr_mgt_pending_state = (program_path, firmware)
        self._pwr_worker = PowerMgtWorker(self._exe_dir, program_path, cwd)
        self._pwr_worker.log.connect(self._log)
        self._pwr_worker.finished.connect(self._on_pwr_mgt_finished)
        self._pwr_worker.start()

    def _on_pwr_mgt_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        self.program_combo.setEnabled(True)
        self.firmware_combo.setEnabled(True)
        if success:
            FPGA.set_loaded(*self._pwr_mgt_pending_state)
            self._refresh_fpga_label()
            self._on_program_change(self.program_combo.currentIndex())
        self._log(("✓ " if success else "✗ ") + msg)
        self._log("-" * 60)

    def _run(self):
        program_path = self.program_combo.currentData()
        if not program_path or not os.path.isfile(program_path):
            self._log("ERROR: Program file not found.")
            return

        program_tag = os.path.splitext(os.path.basename(program_path))[
            0
        ].replace("program_", "")

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

        params = {
            "exe_dir": self._exe_dir,
            "chip_config": chip_config,
            "exposure_time": exposure_time,
            "nframes": self.nframes_combo.currentData(),
            "nacq": self.nacq_spin.value(),
            "folder": self.folder_edit.text(),
            "filename": self.filename_edit.text() or "data",
            "program_tag": program_tag,
            "start_index": self.start_num_spin.value(),
            "metadata": self._metadata_settings(program_path),
        }

        self.pwr_btn.setEnabled(False)
        self.program_combo.setEnabled(False)
        self.firmware_combo.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_edit.clear()
        meta = params["metadata"]
        self._log(
            f"Starting {params['nacq']} × {params['nframes']} frames"
            f"  |  chip_config={chip_config}"
            f"  |  shutter={exposure_time} clks ({self.exp_spin.value():.3f} µs)"
        )
        self._log(
            f"Firmware: {meta['firmware_version']}  |  "
            f"{self.frame_label.text().replace(chr(183), '|')}  |  bias="
            + (
                f"{meta['bias_voltage_v']:g} V"
                if meta["bias_voltage_v"] is not None
                else "not recorded"
            )
        )
        self._log(f"Output : {params['folder']}")
        self._log(
            f"Program: {os.path.basename(program_path)}  (tag={program_tag})"
        )
        self._log(
            f"Files  : {params['filename']}_{program_tag}{params['start_index']}"
            f".bin .. {params['filename']}_{program_tag}"
            f"{params['start_index'] + params['nacq'] - 1}.bin"
        )
        self._log("-" * 60)

        self._worker = AcquisitionWorker(params)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _metadata_settings(self, program_path: str) -> dict:
        """The half of the run's record only this tab knows.

        The worker fills in everything it passed to the exe, so nothing here
        can disagree with what was actually run. See 'functions.metadata'.
        """
        firmware = self._firmware()
        _, resolved_bit = resolve_pwr_mgt_cwd(firmware)
        bias = self.bias_spin.value()
        loaded = FPGA.loaded
        return {
            "program_file": program_path,
            "firmware_version": firmware,
            "firmware_bitfile": resolved_bit,
            "firmware_bitfile_source": (
                firmware
                if firmware_bitfile(firmware) is not None
                else "legacy fallback (params/camera/bitfile)"
            ),
            "firmware_programmed_this_session": bool(
                loaded is not None and loaded[1] == firmware
            ),
            "chip_config_bits": dict(self._chip_state),
            # 0 shows blank in the box and means "not recorded" -- better an
            # empty slot than a number nobody checked.
            "bias_voltage_v": bias if bias > 0 else None,
            "power_management": {
                "ran": loaded is not None,
                "program_file": (
                    os.path.basename(loaded[0]) if loaded is not None else None
                ),
                "firmware_version": loaded[1] if loaded is not None else None,
                "clk_shift": CLK_SHIFT,
                "nbits": NBITS,
            },
        }

    def _abort(self):
        if self._worker:
            self._worker.abort()
            self._log("Abort requested…")

    def _on_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        self.program_combo.setEnabled(True)
        self.firmware_combo.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.abort_btn.setEnabled(False)
        self._log("-" * 60)
        self._log(("✓ " if success else "✗ ") + msg)
        if success:
            self.progress_bar.setValue(100)

    def _log(self, msg: str):
        self.log_edit.append(msg)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())
