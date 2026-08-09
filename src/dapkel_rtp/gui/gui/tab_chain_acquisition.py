"""Tab — Chain Acquisition.

Runs a sequence of acquisition jobs into one shared output folder.
Each job picks a different SPAD program; files are named by program tag,
so all four SxC types coexist flat in the folder.

Typical use: DCR measurement — stack S0C / S1C / S2C / S3C blocks, hit Run.
"""

import glob
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from dapkel_rtp.functions.timing import CLK_PERIOD

from ._paths import (
    BITFILE_NAME,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    firmware_bitfile,
    functions_dir,
    programs_dir,
    resolve_pwr_mgt_cwd,
)
from .style import OUTLINE, SURFACE_LOW, TEXT_DIM
from .tab_acquisition import (
    BIAS_TIP,
    EXP_UI,
    FIRMWARE_TIP,
    FRAME_READOUT_US,
    SettingsDialog,
)
from .fpga_state import FPGA
from .widgets import FRAMES_TIP_BLOCK, make_nframes_combo
from .worker import CLK_SHIFT, NBITS, AcquisitionWorker, PowerMgtWorker


# Program categories — checked in order; first match wins
_PROG_CATEGORIES = [
    ("Counting",            lambda tag: tag.endswith("C") and "OR" not in tag),
    ("Timestamps",          lambda tag: tag.endswith("T") and "OR" not in tag),
    ("First photon / OR",   lambda tag: "OR" in tag),
    ("Coincidences",        lambda tag: "coinc" in tag.lower()),
    ("Other",               lambda tag: True),
]


def _prog_tag(filename: str) -> str:
    """Extract the tag from a program filename, e.g. 'program_S0C.txt' → 'S0C'."""
    return os.path.splitext(filename)[0].replace("program_", "")


def _populate_program_combo(combo: "QComboBox", programs: list) -> None:
    """Fill *combo* with programs grouped under non-selectable category headers."""
    # Bucket by category, preserving order
    buckets: dict[str, list] = {label: [] for label, _ in _PROG_CATEGORIES}
    for name, path in programs:
        tag = _prog_tag(name)
        for label, test in _PROG_CATEGORIES:
            if test(tag):
                buckets[label].append((name, path))
                break

    for label, _ in _PROG_CATEGORIES:
        items = buckets[label]
        if not items:
            continue
        # Non-selectable section header
        combo.addItem(f"  {label}")
        header_idx = combo.count() - 1
        combo.model().item(header_idx).setEnabled(False)
        for name, path in items:
            combo.addItem(f"    {name}", userData=path)


# ---------------------------------------------------------------------------
# Single job row widget
# ---------------------------------------------------------------------------

class JobBlock(QFrame):
    """One acquisition job row — program selector + per-job parameters."""

    remove_requested = pyqtSignal(object)  # emits self

    def __init__(self, programs: list, parent=None):
        super().__init__(parent)
        self._firmware = FIRMWARE_SHORT_EXPOSURE
        self.setStyleSheet(
            f"JobBlock {{ background: {SURFACE_LOW}; border: 1px solid {OUTLINE};"
            f" border-radius: 2px; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(8)

        self._num_label = QLabel("#")
        self._num_label.setFixedWidth(24)
        self._num_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._num_label.setStyleSheet(
            "color: #849495; font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )
        lay.addWidget(self._num_label)

        self.program_combo = QComboBox()
        self.program_combo.setMinimumWidth(170)
        _populate_program_combo(self.program_combo, programs)
        lay.addWidget(self.program_combo)

        lay.addWidget(QLabel("Frames:"))
        # 16 384 = 2 x REPLAY_BLOCK_FRAMES: fills the readout's 16 MiB quantum
        # exactly, so no slot in the file is a replay. Same default as the
        # Acquisition tab.
        self.nframes_combo = make_nframes_combo()
        self.nframes_combo.setToolTip(
            "Frames per .bin file for this job.\n" + FRAMES_TIP_BLOCK
        )
        lay.addWidget(self.nframes_combo)

        self.exp_label = QLabel("Shutter:")
        lay.addWidget(self.exp_label)
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.0, FRAME_READOUT_US)
        self.exp_spin.setDecimals(3)
        self.exp_spin.setValue(0.0)
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setFixedWidth(110)
        lay.addWidget(self.exp_spin)

        # Per job, because each job sets its own shutter time and under
        # long_exposure that changes how long the job takes.
        self.frame_label = QLabel()
        self.frame_label.setFixedWidth(150)
        self.frame_label.setStyleSheet(
            f"color: {TEXT_DIM}; font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        lay.addWidget(self.frame_label)

        lay.addWidget(QLabel("#Files:"))
        self.nacq_spin = QSpinBox()
        self.nacq_spin.setRange(1, 100_000)
        self.nacq_spin.setValue(10)
        self.nacq_spin.setFixedWidth(70)
        lay.addWidget(self.nacq_spin)

        lay.addWidget(QLabel("Prefix:"))
        self.prefix_edit = QLineEdit("data")
        self.prefix_edit.setFixedWidth(80)
        self.prefix_edit.setToolTip("Filename prefix for this job (e.g. 'data' → data_S0C1.bin)")
        lay.addWidget(self.prefix_edit)

        start_num_label = QLabel("Start#:")
        start_num_label.setMinimumWidth(start_num_label.sizeHint().width())
        lay.addWidget(start_num_label)
        self.start_num_spin = QSpinBox()
        self.start_num_spin.setRange(1, 1_000_000)
        self.start_num_spin.setValue(1)
        self.start_num_spin.setFixedWidth(70)
        self.start_num_spin.setToolTip(
            "Number to start this job's filename suffix from. Leave at 1\n"
            "for a fresh run, or set to one past your last file (e.g. 535\n"
            "if you stopped at data_S0C534.bin) to continue without\n"
            "overwriting existing files."
        )
        lay.addWidget(self.start_num_spin)

        lay.addStretch()

        rm_btn = QPushButton("×")
        rm_btn.setFixedSize(26, 26)
        rm_btn.setToolTip("Remove this job")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(rm_btn)

        for spin in (self.exp_spin, self.nacq_spin):
            spin.valueChanged.connect(self._refresh_frame_label)
        self.nframes_combo.currentIndexChanged.connect(self._refresh_frame_label)
        self.set_firmware(self._firmware)

    def set_number(self, n: int):
        self._num_label.setText(str(n))

    def set_firmware(self, firmware: str) -> float | None:
        """Apply a firmware's meaning to this job's shutter box.

        The register is the same in both firmwares but the frame it sits in is
        not, so the label, the tooltip and the cap all move with it. Returns the
        shutter value if it had to be clamped, else None, so the tab can say so
        rather than silently changing a number the operator typed.
        """
        self._firmware = firmware
        ui = EXP_UI[firmware]
        self.exp_label.setText(ui["label"])
        self.exp_spin.setToolTip(ui["tip"])
        before = self.exp_spin.value()
        self.exp_spin.setMaximum(ui["maximum"])
        after = self.exp_spin.value()
        self._refresh_frame_label()
        return after if after != before else None

    def frame_acq_time_us(self) -> float:
        """This job's frame length under the currently selected firmware."""
        if self._firmware == FIRMWARE_LONG_EXPOSURE:
            return self.exp_spin.value() + FRAME_READOUT_US
        return FRAME_READOUT_US

    def _refresh_frame_label(self):
        frame_us = self.frame_acq_time_us()
        total_s = (
            frame_us
            * 1e-6
            * self.nframes_combo.currentData()
            * self.nacq_spin.value()
        )
        self.frame_label.setText(f"{frame_us:.3f} µs/frm · {total_s:.4g} s")

    def copy_from(self, other: "JobBlock") -> None:
        """Take every parameter from *other*.

        Used when appending a job: a chain is nearly always the same
        measurement repeated with one thing varied, so the previous job is a
        far better starting point than the defaults. Copies the program too —
        changing that one combo is the usual single edit.
        """
        self.program_combo.setCurrentIndex(other.program_combo.currentIndex())
        self.nframes_combo.setCurrentIndex(other.nframes_combo.currentIndex())
        self.exp_spin.setValue(other.exp_spin.value())
        self.nacq_spin.setValue(other.nacq_spin.value())
        self.prefix_edit.setText(other.prefix_edit.text())
        self.start_num_spin.setValue(other.start_num_spin.value())
        self._refresh_frame_label()

    def select_program_by_tag(self, tag: str) -> bool:
        """Select the first selectable program whose filename contains *tag*."""
        model = self.program_combo.model()
        for i in range(self.program_combo.count()):
            if model.item(i).isEnabled() and tag in self.program_combo.itemText(i):
                self.program_combo.setCurrentIndex(i)
                return True
        return False

    def job_params(self) -> dict | None:
        path = self.program_combo.currentData()
        if not path or not os.path.isfile(path):
            return None
        tag = os.path.splitext(os.path.basename(path))[0].replace("program_", "")
        return {
            "program_path": path,
            "program_tag": tag,
            "nframes": self.nframes_combo.currentData(),
            "exp_time_us": self.exp_spin.value(),
            "nacq": self.nacq_spin.value(),
            "prefix": self.prefix_edit.text() or "data",
            "start_index": self.start_num_spin.value(),
        }


# ---------------------------------------------------------------------------
# Chain Acquisition tab
# ---------------------------------------------------------------------------

class ChainAcquisitionTab(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: AcquisitionWorker | None = None
        self._pwr_worker: PowerMgtWorker | None = None
        # What is loaded on the FPGA is shared state, not this tab's (see
        # fpga_state). Only the in-flight request is local.
        self._pwr_mgt_pending_state: tuple[str, str] | None = None
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
        self._programs: list = []          # [(display_name, full_path), …]
        self._job_blocks: list[JobBlock] = []
        self._pending_jobs: list[dict] = []
        self._total_jobs = 0
        self._completed_jobs = 0
        self._build_ui()
        self._load_programs()
        self._init_default_job()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

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
            "Folder for all job outputs — files named by program tag…"
        )
        self.folder_edit.setMinimumHeight(32)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.setFixedHeight(32)
        browse_btn.clicked.connect(self._browse_folder)
        out_lay.addWidget(self.folder_edit)
        out_lay.addWidget(browse_btn)
        root.addWidget(out_grp)

        # ---- Firmware / bias row ----
        # Both are rig state, not per-job: one bitstream is loaded at a time,
        # and the bias comes off a bench supply the app cannot switch between
        # jobs. Recording them per job would suggest otherwise.
        rig_row = QHBoxLayout()
        rig_row.setSpacing(8)

        rig_row.addWidget(QLabel("Firmware:"))
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
        rig_row.addWidget(self.firmware_combo)

        rig_row.addSpacing(16)
        rig_row.addWidget(QLabel("Bias:"))
        self.bias_spin = QDoubleSpinBox()
        self.bias_spin.setRange(0.0, 100.0)
        self.bias_spin.setDecimals(2)
        self.bias_spin.setValue(22.0)
        self.bias_spin.setSuffix(" V")
        self.bias_spin.setSpecialValueText("")  # 0 shows blank → null on record
        self.bias_spin.setFixedWidth(90)
        self.bias_spin.setToolTip(BIAS_TIP)
        rig_row.addWidget(self.bias_spin)

        rig_row.addStretch()

        self.fpga_label = QLabel()
        self.fpga_label.setStyleSheet(f"color: {TEXT_DIM};")
        rig_row.addWidget(self.fpga_label)
        root.addLayout(rig_row)

        # ---- Settings row ----
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Jobs  (run top to bottom):"))
        settings_row.addStretch()
        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedWidth(120)
        settings_btn.clicked.connect(self._open_settings)
        settings_row.addWidget(settings_btn)
        root.addLayout(settings_row)

        # ---- Scrollable job list ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(220)
        scroll.setFrameShape(QFrame.NoFrame)
        self._jobs_container = QWidget()
        self._jobs_layout = QVBoxLayout(self._jobs_container)
        self._jobs_layout.setSpacing(4)
        self._jobs_layout.setContentsMargins(0, 0, 4, 0)
        self._jobs_layout.addStretch()
        scroll.setWidget(self._jobs_container)
        root.addWidget(scroll)

        # ---- Add job button ----
        add_row = QHBoxLayout()
        self._add_btn = QPushButton("+  Add Job")
        self._add_btn.setFixedWidth(110)
        self._add_btn.setFixedHeight(30)
        self._add_btn.clicked.connect(self._on_add_job_clicked)
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        root.addLayout(add_row)

        # ---- Power Mgt / Run / Abort ----
        btn_row = QHBoxLayout()

        self.pwr_btn = QPushButton("⚡  Power Mgt")
        self.pwr_btn.setObjectName("pwr_btn")
        self.pwr_btn.setFixedHeight(46)
        self.pwr_btn.setFixedWidth(150)
        self.pwr_btn.setToolTip("Initialise FPGA via Kelpie_v2_pwr_mgt.exe")
        self.pwr_btn.clicked.connect(self._run_pwr_mgt)

        self.run_btn = QPushButton("▶   Run Chain")
        self.run_btn.setObjectName("run_btn")
        self.run_btn.setFixedHeight(46)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip("Run Power Mgt first to activate")
        self.run_btn.clicked.connect(self._run_chain)

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
        self.chain_bar = QProgressBar()
        self.chain_bar.setFixedHeight(18)
        self.chain_bar.setFormat("Ready")
        root.addWidget(self.chain_bar)

        # ---- Log ----
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        root.addWidget(self.log_edit, stretch=1)

    # ------------------------------------------------------------------
    # Program list and defaults
    # ------------------------------------------------------------------

    def _load_programs(self):
        prog_dir = programs_dir()
        if not os.path.isdir(prog_dir):
            return
        for fp in sorted(glob.glob(os.path.join(prog_dir, "program_*.txt"))):
            self._programs.append((os.path.basename(fp), fp))

    def _init_default_job(self):
        self.folder_edit.setText(os.path.join(functions_dir(), "data"))
        block = self.add_job()
        block.select_program_by_tag("S3C")
        self._refresh_fpga_label()
        # Connected only after the default selection settles, so app
        # startup doesn't auto-trigger a Power Mgt run before the user
        # does anything.
        block.program_combo.currentIndexChanged.connect(
            lambda _idx, b=block: self._on_job_program_change(b)
        )
        self.firmware_combo.currentIndexChanged.connect(self._on_firmware_change)
        FPGA.changed.connect(self._on_fpga_changed)

    def _on_add_job_clicked(self):
        previous = self._job_blocks[-1] if self._job_blocks else None
        block = self.add_job()
        if previous is not None:
            block.copy_from(previous)
        block.program_combo.currentIndexChanged.connect(
            lambda _idx, b=block: self._on_job_program_change(b)
        )

    # ------------------------------------------------------------------
    # Job block management
    # ------------------------------------------------------------------

    def _renumber_jobs(self):
        for i, b in enumerate(self._job_blocks, 1):
            b.set_number(i)

    def add_job(self) -> JobBlock:
        """Create and append a new job block; return it. Callers are
        responsible for wiring up program-change auto-triggering (see
        _init_default_job / _on_add_job_clicked) since only job #1 should
        gate Power Mgt / Run Chain."""
        block = JobBlock(self._programs, self._jobs_container)
        block.set_firmware(self._firmware())
        block.remove_requested.connect(self._remove_job)
        self._jobs_layout.insertWidget(
            max(0, self._jobs_layout.count() - 1), block
        )
        self._job_blocks.append(block)
        self._renumber_jobs()
        return block

    def _remove_job(self, block: JobBlock):
        self._jobs_layout.removeWidget(block)
        block.deleteLater()
        if block in self._job_blocks:
            self._job_blocks.remove(block)
        self._renumber_jobs()

    # ------------------------------------------------------------------
    # Dialogs / folder
    # ------------------------------------------------------------------

    def _browse_folder(self):
        start = self.folder_edit.text() or functions_dir()
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder", start)
        if d:
            self.folder_edit.setText(d)

    def _open_settings(self):
        dlg = SettingsDialog(self._chip_state, self._exe_dir, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._chip_state = dlg.chip_state()
            self._exe_dir = dlg.exe_dir()

    # ------------------------------------------------------------------
    # Power management
    # ------------------------------------------------------------------

    def _firmware(self) -> str:
        return self.firmware_combo.currentData() or FIRMWARE_SHORT_EXPOSURE

    def _on_fpga_changed(self):
        """Another tab reprogrammed the FPGA: stop claiming it is ready.

        Deliberately does not reprogram — see the same handler on the single
        acquisition tab.
        """
        self._refresh_fpga_label()
        busy = (self._worker is not None and self._worker.isRunning()) or (
            self._pwr_worker is not None and self._pwr_worker.isRunning()
        )
        if busy or not self._job_blocks:
            return
        ready = FPGA.loaded == (
            self._job_blocks[0].program_combo.currentData(),
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

    def _on_firmware_change(self, _idx: int = 0):
        """Re-label every job's shutter box, then reprogram the FPGA."""
        firmware = self._firmware()
        clamped = [
            (i, block.set_firmware(firmware))
            for i, block in enumerate(self._job_blocks, 1)
        ]
        if self._job_blocks:
            self._on_job_program_change(self._job_blocks[0])
        # Reported after the reprogram, not before: _run_pwr_mgt clears the log,
        # which would swallow these. Never silently -- the operator entered a
        # number and got another one.
        for i, value in clamped:
            if value is not None:
                self._log(
                    f"Job {i}: shutter capped at {value:.3f} µs by {firmware}."
                )

    def _on_job_program_change(self, block: JobBlock):
        """Auto-run Power Mgt whenever job #1's program or the firmware
        actually changes, since the FPGA must be reprogrammed for either. Only
        job #1 gates Power Mgt / Run Chain readiness; jobs 2+ are reprogrammed
        automatically as needed by the chain executor (see _start_next_job)."""
        if not self._job_blocks or self._job_blocks[0] is not block:
            return
        if self._worker is not None and self._worker.isRunning():
            return  # chain actively running; ignore
        if self._pwr_worker is not None and self._pwr_worker.isRunning():
            return  # a Power Mgt run is already in flight

        program_path = block.program_combo.currentData()
        if program_path is None:
            return  # category header, not a real selection

        if (program_path, self._firmware()) == FPGA.loaded:
            self.run_btn.setEnabled(True)
            self.run_btn.setToolTip("")
        else:
            self._run_pwr_mgt()

    def _run_pwr_mgt(self):
        if not self._job_blocks:
            self._log("ERROR: Add at least one job first.")
            return
        program_path = self._job_blocks[0].program_combo.currentData()
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
        self._jobs_container.setEnabled(False)
        self._add_btn.setEnabled(False)
        self.firmware_combo.setEnabled(False)
        self.log_edit.clear()
        self._log(f"--- Power management initialisation ({firmware}) ---")
        if firmware_bitfile(firmware) is None:
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
        self._pwr_worker.finished.connect(self._on_pwr_finished)
        self._pwr_worker.start()

    def _on_pwr_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        self._jobs_container.setEnabled(True)
        self._add_btn.setEnabled(True)
        self.firmware_combo.setEnabled(True)
        if success:
            FPGA.set_loaded(*self._pwr_mgt_pending_state)
            self._refresh_fpga_label()
            if self._job_blocks:
                self._on_job_program_change(self._job_blocks[0])
        self._log(("✓ " if success else "✗ ") + msg)
        self._log("-" * 60)

    # ------------------------------------------------------------------
    # Chain execution
    # ------------------------------------------------------------------

    def _run_chain(self):
        folder = self.folder_edit.text()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            self._log(f"ERROR: Cannot create folder: {exc}")
            return

        job_params = []
        for i, block in enumerate(self._job_blocks):
            p = block.job_params()
            if p is None:
                self._log(f"ERROR: Job {i + 1} has an invalid program file.")
                return
            job_params.append(p)

        if not job_params:
            self._log("ERROR: No jobs configured.")
            return

        self._pending_jobs = job_params
        self._total_jobs = len(job_params)
        self._completed_jobs = 0

        self.chain_bar.setRange(0, self._total_jobs * 100)
        self.chain_bar.setValue(0)
        self.chain_bar.setFormat("Starting…")
        self.pwr_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._jobs_container.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self.log_edit.clear()
        self._log(f"Chain: {self._total_jobs} jobs  →  {folder}")
        self._log("=" * 60)
        self._start_next_job()

    def _metadata_settings(self, program_path: str) -> dict:
        """The half of a job's record only this tab knows.

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

    def _chip_config_int(self) -> int:
        s = self._chip_state
        return (
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

    def _start_next_job(self):
        """Peek at the next queued job; reprogram the FPGA first if it
        needs a different program than what's currently loaded (which
        happens whenever consecutive jobs use different SPAD programs --
        the FPGA has to be reprogrammed every time the program changes,
        not just once at the start of the chain)."""
        if not self._pending_jobs:
            self._on_chain_done(True)
            return

        jp = self._pending_jobs[0]
        firmware = self._firmware()
        if (jp["program_path"], firmware) != FPGA.loaded:
            cwd, bitfile = resolve_pwr_mgt_cwd(firmware)
            if bitfile is None:
                self._log(
                    f"ERROR: no {BITFILE_NAME} for {firmware}, and none in the "
                    "legacy folder either."
                )
                self._on_chain_done(False)
                return
            self._log(
                f"\nProgramming FPGA for {jp['program_tag']} ({firmware})…"
            )
            self._pwr_mgt_pending_state = (jp["program_path"], firmware)
            self._pwr_worker = PowerMgtWorker(
                self._exe_dir, jp["program_path"], cwd
            )
            self._pwr_worker.log.connect(self._log)
            self._pwr_worker.finished.connect(self._on_chain_pwr_mgt_finished)
            self._pwr_worker.start()
            return

        self._run_current_job()

    def _on_chain_pwr_mgt_finished(self, success: bool, msg: str):
        self._log(("✓ " if success else "✗ ") + msg)
        if not self._pending_jobs:
            return  # aborted while this reprogram was in flight
        if not success:
            self._on_chain_done(False)
            return
        FPGA.set_loaded(*self._pwr_mgt_pending_state)
        self._refresh_fpga_label()
        self._run_current_job()

    def _run_current_job(self):
        jp = self._pending_jobs.pop(0)
        job_num = self._completed_jobs + 1
        chip_config = self._chip_config_int()
        exposure_time = round(jp["exp_time_us"] * 1e-6 / CLK_PERIOD)

        last_index = jp["start_index"] + jp["nacq"] - 1
        firmware = self._firmware()
        frame_us = (
            jp["exp_time_us"] + FRAME_READOUT_US
            if firmware == FIRMWARE_LONG_EXPOSURE
            else FRAME_READOUT_US
        )
        self._log(
            f"\n[Job {job_num}/{self._total_jobs}]  {jp['program_tag']}"
            f"  —  {jp['nacq']} × {jp['nframes']} frames"
            f"  |  shutter={jp['exp_time_us']:.3f} µs"
            f"  |  {frame_us:.3f} µs/frame ({firmware})"
        )
        self._log(
            f"  Files: {jp['prefix']}_{jp['program_tag']}{jp['start_index']}.bin"
            f" .. {jp['prefix']}_{jp['program_tag']}{last_index}.bin"
        )

        params = {
            "exe_dir": self._exe_dir,
            "chip_config": chip_config,
            "exposure_time": exposure_time,
            "nframes": jp["nframes"],
            "nacq": jp["nacq"],
            "folder": self.folder_edit.text(),
            "filename": jp["prefix"],
            "program_tag": jp["program_tag"],
            "start_index": jp["start_index"],
            # One record per job, not per chain: each job has its own program,
            # frame count and shutter time, so one record for the whole chain
            # could not describe any of them.
            "metadata": self._metadata_settings(jp["program_path"]),
        }

        tag = jp["program_tag"]
        self._worker = AcquisitionWorker(params)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(
            lambda pct, jn=job_num, t=tag: self._on_job_progress(pct, jn, t)
        )
        self._worker.finished.connect(self._on_job_finished)
        self._worker.start()

    def _on_job_progress(self, pct: int, job_num: int, tag: str):
        self.chain_bar.setValue(self._completed_jobs * 100 + pct)
        self.chain_bar.setFormat(f"Job {job_num}/{self._total_jobs}  {tag}  {pct}%")

    def _on_job_finished(self, success: bool, msg: str):
        self._log(("✓ " if success else "✗ ") + msg)
        if not success:
            self._on_chain_done(False)
            return
        self._completed_jobs += 1
        self.chain_bar.setValue(self._completed_jobs * 100)
        self._start_next_job()

    def _on_chain_done(self, success: bool):
        self.pwr_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._jobs_container.setEnabled(True)
        self.abort_btn.setEnabled(False)
        self._log("=" * 60)
        if success:
            self.chain_bar.setValue(self._total_jobs * 100)
            self.chain_bar.setFormat(f"Done — {self._total_jobs} jobs")
            self._log(f"✓ Chain complete — {self._total_jobs} jobs.")
        else:
            self._log(
                f"✗ Chain aborted after {self._completed_jobs}/{self._total_jobs} jobs."
            )

    def _abort(self):
        self._pending_jobs.clear()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
        self._log("Abort requested…")

    def _log(self, msg: str):
        self.log_edit.append(msg)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())
