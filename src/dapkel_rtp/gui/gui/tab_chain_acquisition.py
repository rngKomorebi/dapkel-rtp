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

from ._paths import functions_dir, params_camera_dir, programs_dir
from .style import OUTLINE, SURFACE_LOW
from .tab_acquisition import SettingsDialog
from .worker import AcquisitionWorker, PowerMgtWorker

CLK_PERIOD = 5e-9

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
        self.nframes_spin = QSpinBox()
        self.nframes_spin.setRange(1, 1_100_000)
        self.nframes_spin.setValue(10_000)
        self.nframes_spin.setSingleStep(1000)
        self.nframes_spin.setFixedWidth(90)
        lay.addWidget(self.nframes_spin)

        lay.addWidget(QLabel("Exp:"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(0.0, 1_000_000.0)
        self.exp_spin.setDecimals(3)
        self.exp_spin.setValue(0.0)
        self.exp_spin.setSuffix(" µs")
        self.exp_spin.setFixedWidth(110)
        self.exp_spin.setToolTip(
            "Extra exposure beyond free-running base.\n"
            "0 µs → 9 µs frame period  |  10 µs → 19 µs frame period"
        )
        lay.addWidget(self.exp_spin)

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

        lay.addStretch()

        rm_btn = QPushButton("×")
        rm_btn.setFixedSize(26, 26)
        rm_btn.setToolTip("Remove this job")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(rm_btn)

    def set_number(self, n: int):
        self._num_label.setText(str(n))

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
            "nframes": self.nframes_spin.value(),
            "exp_time_us": self.exp_spin.value(),
            "nacq": self.nacq_spin.value(),
            "prefix": self.prefix_edit.text() or "data",
        }


# ---------------------------------------------------------------------------
# Chain Acquisition tab
# ---------------------------------------------------------------------------

class ChainAcquisitionTab(QWidget):
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
        self._add_btn.clicked.connect(self.add_job)
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

    # ------------------------------------------------------------------
    # Job block management
    # ------------------------------------------------------------------

    def _renumber_jobs(self):
        for i, b in enumerate(self._job_blocks, 1):
            b.set_number(i)

    def add_job(self) -> JobBlock:
        """Create and append a new job block; return it."""
        block = JobBlock(self._programs, self._jobs_container)
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

    def _run_pwr_mgt(self):
        if not self._job_blocks:
            self._log("ERROR: Add at least one job first.")
            return
        program_path = self._job_blocks[0].program_combo.currentData()
        if not program_path or not os.path.isfile(program_path):
            self._log("ERROR: Program file not found.")
            return

        self.pwr_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.log_edit.clear()
        self._log("--- Power management initialisation ---")

        self._pwr_worker = PowerMgtWorker(
            self._exe_dir, program_path, params_camera_dir()
        )
        self._pwr_worker.log.connect(self._log)
        self._pwr_worker.finished.connect(self._on_pwr_finished)
        self._pwr_worker.start()

    def _on_pwr_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        if success:
            self.run_btn.setEnabled(True)
            self.run_btn.setToolTip("")
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
        self.run_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self.log_edit.clear()
        self._log(f"Chain: {self._total_jobs} jobs  →  {folder}")
        self._log("=" * 60)
        self._start_next_job()

    def _chip_config_int(self) -> int:
        s = self._chip_state
        return (
            int(s["debug_last_row"]) << 6
            | int(s["memory_select1"]) << 5
            | int(s["memory_select0"]) << 4
            | int(s["single_shot_noise"]) << 3
            | int(s["chip_artif_rdout"]) << 2
            | int(s["chip_timing"]) << 1
            | int(s["chip_debug"])
        )

    def _start_next_job(self):
        if not self._pending_jobs:
            self._on_chain_done(True)
            return

        jp = self._pending_jobs.pop(0)
        job_num = self._completed_jobs + 1
        chip_config = self._chip_config_int()
        exposure_time = round(jp["exp_time_us"] * 1e-6 / CLK_PERIOD)

        self._log(
            f"\n[Job {job_num}/{self._total_jobs}]  {jp['program_tag']}"
            f"  —  {jp['nacq']} × {jp['nframes']} frames"
            f"  |  exp={jp['exp_time_us']:.3f} µs"
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
        self.run_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
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
