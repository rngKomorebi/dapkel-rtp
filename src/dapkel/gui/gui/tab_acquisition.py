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

from ._paths import bitfile_dir, functions_dir, params_camera_dir, programs_dir
from .worker import AcquisitionWorker, PowerMgtWorker

CLK_PERIOD = 5e-9  # 200 MHz clock → 5 ns


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
    ]

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
            int(c["debug_last_row"].isChecked()) << 6
            | int(c["memory_select1"].isChecked()) << 5
            | int(c["memory_select0"].isChecked()) << 4
            | int(c["single_shot_noise"].isChecked()) << 3
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
        }
        self._exe_dir = functions_dir()
        self._build_ui()
        self._populate_programs()

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
        self.nframes_spin = QSpinBox()
        self.nframes_spin.setRange(1, 1_100_000)
        self.nframes_spin.setValue(10_000)
        self.nframes_spin.setSingleStep(1000)
        self.nframes_spin.setFixedWidth(90)
        self.nframes_spin.setToolTip("Frames per .bin file (max ~1.1 M)")
        params.addWidget(self.nframes_spin)

        params.addWidget(QLabel("#Acq:"))
        self.nacq_spin = QSpinBox()
        self.nacq_spin.setRange(1, 100_000)
        self.nacq_spin.setValue(10)
        self.nacq_spin.setFixedWidth(70)
        params.addWidget(self.nacq_spin)

        params.addWidget(QLabel("Exp:"))
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
        params.addWidget(self.exp_spin)

        params.addWidget(QLabel("File:"))
        self.filename_edit = QLineEdit("data")
        self.filename_edit.setFixedWidth(90)
        self.filename_edit.setToolTip(
            "Output filename prefix (e.g. 'data' → data1.bin, data2.bin, …)"
        )
        params.addWidget(self.filename_edit)

        params.addStretch()

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setFixedWidth(120)
        settings_btn.clicked.connect(self._open_settings)
        params.addWidget(settings_btn)

        root.addLayout(params)

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

    def _run_pwr_mgt(self):
        program_path = self.program_combo.currentData()
        if not program_path or not os.path.isfile(program_path):
            self._log("ERROR: Program file not found.")
            return

        self.pwr_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.log_edit.clear()
        self._log("--- Power management initialisation ---")

        self._pwr_worker = PowerMgtWorker(self._exe_dir, program_path, params_camera_dir())
        self._pwr_worker.log.connect(self._log)
        self._pwr_worker.finished.connect(self._on_pwr_mgt_finished)
        self._pwr_worker.start()

    def _on_pwr_mgt_finished(self, success: bool, msg: str):
        self.pwr_btn.setEnabled(True)
        if success:
            self.run_btn.setEnabled(True)
            self.run_btn.setToolTip("")
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
            int(s["debug_last_row"]) << 6
            | int(s["memory_select1"]) << 5
            | int(s["memory_select0"]) << 4
            | int(s["single_shot_noise"]) << 3
            | int(s["chip_artif_rdout"]) << 2
            | int(s["chip_timing"]) << 1
            | int(s["chip_debug"])
        )

        exposure_time = round(self.exp_spin.value() * 1e-6 / CLK_PERIOD)

        params = {
            "exe_dir": self._exe_dir,
            "chip_config": chip_config,
            "exposure_time": exposure_time,
            "nframes": self.nframes_spin.value(),
            "nacq": self.nacq_spin.value(),
            "folder": self.folder_edit.text(),
            "filename": self.filename_edit.text() or "data",
            "program_tag": program_tag,
        }

        self.run_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_edit.clear()
        self._log(
            f"Starting {params['nacq']} × {params['nframes']} frames"
            f"  |  chip_config={chip_config}"
            f"  |  exp={exposure_time} clks ({self.exp_spin.value():.3f} µs)"
        )
        self._log(f"Output : {params['folder']}")
        self._log(
            f"Program: {os.path.basename(program_path)}  (tag={program_tag})"
        )
        self._log("-" * 60)

        self._worker = AcquisitionWorker(params)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _abort(self):
        if self._worker:
            self._worker.abort()
            self._log("Abort requested…")

    def _on_finished(self, success: bool, msg: str):
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
