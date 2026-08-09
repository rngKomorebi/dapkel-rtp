"""Tab 4 - Data Quality (check an acquisition without leaving the app).

Point it at the folder being acquired into, pick one of the '.bin' files it
finds there, and press Run: the file is decoded and its TDC-code distribution
is shown, the same check ``dapkel.functions.data_quality`` runs offline. The
question it answers is the one worth answering while the camera is still set
up - did the TDC actually record timing? - because that failure is silent:
'unpack' returns plausible integers either way and every downstream analysis
still produces a shape.

What is shown is counted out of the file, never modelled:

* the histogram is the exact per-code distribution over every frame examined,
  rebinned only for drawing (see dapkel_rtp.functions.data_quality);
* frames that carry no data are dropped structurally, so the unwritten tail of
  the block-padded readout and the chip's idle pattern are not counted as
  frames that failed to record timing;
* the pixel map beside it is the number of valid timestamps each pixel
  produced - it comes free with the decode and shows at a glance whether the
  timing is array-wide or confined to a corner;
* the verdict is a three-way heuristic over the reported numbers, and those
  numbers are always printed next to it. For a ``*C`` (count) program no
  verdict is given at all: there the decoded "codes" are photon-count bits,
  not time.
"""

import os
import time

import numpy as np
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from dapkel_rtp.functions.data_quality import (
    MODE_AUTO,
    MODE_COUNT,
    MODE_TIMESTAMP,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SUSPECT,
    format_report,
    histogram_for_display,
    scan_bin_files,
)

from ._paths import functions_dir
from .style import AMBER, BG, CYAN, OUTLINE, RED, SURFACE_LOW, TEXT_DIM
from .widgets import make_nframes_combo
from .worker import DataQualityWorker

# Left border of the report block, by verdict. n/a and "no result yet" keep
# the neutral outline colour: an unjudged file must not read as a passed one.
_VERDICT_COLOR = {
    VERDICT_PASS: CYAN,
    VERDICT_SUSPECT: AMBER,
    VERDICT_FAIL: RED,
}

_FRAMES_TIP = (
    "Frames to examine, from the start of the file.\n"
    "One 8192-frame block is plenty to see whether the TDC is timing;\n"
    "more takes proportionally longer to decode.\n"
    "\n"
    "'all' does NOT mean every slot in the file. The readout is\n"
    "quantised to 16 MiB blocks, so a 10 000-frame run lands in a\n"
    "16 384-slot file whose last 6 384 slots replay slots 1808..8191\n"
    "byte for byte. 'all' measures where that replay starts and stops\n"
    "there, so no frame is histogrammed twice.\n"
    "Set the number the run was acquired with when you know it. The\n"
    "default 16 384 is what the acquisition tabs ask for, and it fills\n"
    "two blocks exactly, so such a file has nothing replayed."
)

_PIXEL_TIP = (
    "All pixels pools the codes of the whole 32x32 array - the fastest\n"
    "way to see whether the run recorded timing at all.\n"
    "A single pixel reproduces dapkel's data_quality histogram exactly,\n"
    "for when one pixel is suspect."
)

_PROGRAM_TIP = (
    "Which program wrote the file. The check only means something for a\n"
    "timestamp (*T) run: in a count (*C) run the bits decoded here are\n"
    "photon counts, not time, and they still make a plausible-looking\n"
    "distribution.\n"
    "Auto reads the tag out of the file name (e.g. data_ORT7.bin). When\n"
    "there is no tag no verdict is given -- say which it was here instead\n"
    "of having one assumed."
)


class DataQualityTab(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: DataQualityWorker | None = None
        self._files: list[dict] = []
        self._summary: dict | None = None  # last result, for a bins redraw
        self._t0 = 0.0
        self._build_ui()
        default_folder = os.path.join(functions_dir(), "data")
        # The acquisition tabs create this on their first run; make it exist for
        # a first scan too. The release bundle used to ship the folder (and the
        # stale acquisitions inside it), so without this the released app would
        # open on '⚠ Not a folder' instead of 'No .bin files in this folder'.
        try:
            os.makedirs(default_folder, exist_ok=True)
        except OSError:
            pass  # unwritable location: the scan reports it, nothing to fix here
        self.folder_edit.setText(default_folder)
        self._rescan()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- Data folder ----
        in_grp = QGroupBox("Data Folder")
        in_lay = QHBoxLayout(in_grp)
        in_lay.setContentsMargins(8, 6, 8, 8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(
            "Folder holding the .bin files to check…"
        )
        self.folder_edit.setMinimumHeight(32)
        self.folder_edit.editingFinished.connect(self._rescan)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.setFixedHeight(32)
        browse_btn.clicked.connect(self._browse_folder)
        rescan_btn = QPushButton("⟳  Rescan")
        rescan_btn.setFixedWidth(100)
        rescan_btn.setFixedHeight(32)
        rescan_btn.setToolTip("Re-read the folder, picking up new .bin files")
        rescan_btn.clicked.connect(self._rescan)
        in_lay.addWidget(self.folder_edit)
        in_lay.addWidget(browse_btn)
        in_lay.addWidget(rescan_btn)
        root.addWidget(in_grp)

        # ---- File list ----
        list_head = QHBoxLayout()
        self.count_label = QLabel("")
        list_head.addWidget(self.count_label)
        list_head.addStretch()
        self.newest_cb = QCheckBox("Newest first")
        self.newest_cb.setChecked(True)
        self.newest_cb.setToolTip(
            "Sort by modification time instead of by name — the file you\n"
            "just acquired ends up at the top."
        )
        self.newest_cb.toggled.connect(self._refill_list)
        list_head.addWidget(self.newest_cb)
        root.addLayout(list_head)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.setMinimumHeight(110)
        self.file_list.setMaximumHeight(170)
        self.file_list.itemDoubleClicked.connect(lambda _item: self._run())
        self.file_list.currentRowChanged.connect(self._on_selection_change)
        root.addWidget(self.file_list)

        # ---- Compact params row ----
        params = QHBoxLayout()
        params.setSpacing(8)

        params.addWidget(QLabel("Program:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Auto (from file name)", userData=MODE_AUTO)
        self.mode_combo.addItem("Timestamp (*T)", userData=MODE_TIMESTAMP)
        self.mode_combo.addItem("Count (*C)", userData=MODE_COUNT)
        self.mode_combo.setMinimumWidth(170)
        self.mode_combo.setToolTip(_PROGRAM_TIP)
        params.addWidget(self.mode_combo)

        params.addWidget(QLabel("Pixels:"))
        self.pixel_combo = QComboBox()
        self.pixel_combo.addItem("All pixels (pooled)", userData=False)
        self.pixel_combo.addItem("Single pixel", userData=True)
        self.pixel_combo.setMinimumWidth(160)
        self.pixel_combo.setToolTip(_PIXEL_TIP)
        self.pixel_combo.currentIndexChanged.connect(self._on_pixel_mode)
        params.addWidget(self.pixel_combo)

        self.row_label = QLabel("Row:")
        params.addWidget(self.row_label)
        self.row_spin = QSpinBox()
        self.row_spin.setRange(0, 31)
        self.row_spin.setValue(16)
        self.row_spin.setFixedWidth(70)
        params.addWidget(self.row_spin)

        self.col_label = QLabel("Col:")
        params.addWidget(self.col_label)
        self.col_spin = QSpinBox()
        self.col_spin.setRange(0, 31)
        self.col_spin.setValue(16)
        self.col_spin.setFixedWidth(70)
        params.addWidget(self.col_spin)

        params.addWidget(QLabel("Frames:"))
        self.nframes_combo = make_nframes_combo(all_option=True)
        self.nframes_combo.setToolTip(_FRAMES_TIP)
        params.addWidget(self.nframes_combo)

        params.addWidget(QLabel("Bins:"))
        self.bins_spin = QSpinBox()
        self.bins_spin.setRange(8, 4096)
        self.bins_spin.setValue(256)
        self.bins_spin.setSingleStep(64)
        self.bins_spin.setFixedWidth(80)
        self.bins_spin.setToolTip(
            "Histogram columns drawn. Only the plot is rebinned — every\n"
            "reported number comes from the full per-code histogram."
        )
        self.bins_spin.valueChanged.connect(self._on_bins_change)
        params.addWidget(self.bins_spin)

        params.addStretch()
        root.addLayout(params)

        self._on_pixel_mode(self.pixel_combo.currentIndex())

        # ---- Run / Abort ----
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶   Run Check")
        self.run_btn.setObjectName("run_btn")
        self.run_btn.setFixedHeight(46)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip("Select a .bin file from the list first")
        self.run_btn.clicked.connect(self._run)

        self.abort_btn = QPushButton("■   Abort")
        self.abort_btn.setObjectName("abort_btn")
        self.abort_btn.setFixedHeight(46)
        self.abort_btn.setFixedWidth(130)
        self.abort_btn.setEnabled(False)
        self.abort_btn.clicked.connect(self._abort)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.abort_btn)
        root.addLayout(btn_row)

        # ---- Progress ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(22)
        root.addWidget(self.progress_bar)

        # ---- Report ----
        self.report_label = QLabel("")
        self.report_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.report_label.setWordWrap(False)
        self._style_report(None)
        root.addWidget(self.report_label)

        # ---- Matplotlib toolbar + canvas ----
        self.figure = Figure(tight_layout=True, facecolor=BG)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setStyleSheet(f"background: {BG}; border: none;")
        # The list, the report block and the toolbar above it are all fixed
        # height, so without a floor the histogram is the only thing that
        # gives when the window is short -- and it is the point of the tab.
        self.canvas.setMinimumHeight(300)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas, stretch=1)

    def _style_report(self, verdict: str | None):
        self.report_label.setStyleSheet(
            "font-family: 'JetBrains Mono', Consolas, monospace;"
            f"color: {TEXT_DIM};"
            f"background: {SURFACE_LOW};"
            f"border: 1px solid {OUTLINE};"
            f"border-left: 3px solid {_VERDICT_COLOR.get(verdict, OUTLINE)};"
            "padding: 6px 10px;"
        )

    def _on_pixel_mode(self, idx: int):
        single = bool(self.pixel_combo.itemData(idx))
        for w in (
            self.row_label,
            self.row_spin,
            self.col_label,
            self.col_spin,
        ):
            w.setEnabled(single)

    # ------------------------------------------------------------------
    # Folder scanning
    # ------------------------------------------------------------------

    def _browse_folder(self):
        start = self.folder_edit.text() or functions_dir()
        d = QFileDialog.getExistingDirectory(self, "Select Data Folder", start)
        if d:
            self.folder_edit.setText(d)
            self._rescan()

    def _rescan(self):
        folder = self.folder_edit.text().strip()
        try:
            self._files = scan_bin_files(folder)
        except NotADirectoryError as exc:
            self._files = []
            self.file_list.clear()
            self.count_label.setText(f"⚠  {exc}")
            self._on_selection_change(-1)
            return
        self._refill_list()

    def _refill_list(self):
        """Redraw the list from the last scan, in the requested order.

        The selected file is kept selected across a re-sort or a rescan that
        still holds it, so toggling the order doesn't lose the file you were
        about to check.
        """
        keep = self._selected_path()
        files = list(self._files)
        if self.newest_cb.isChecked():
            files.sort(key=lambda e: e["mtime"], reverse=True)

        self.file_list.clear()
        for entry in files:
            item = QListWidgetItem(self._item_text(entry))
            item.setData(Qt.UserRole, entry["path"])
            self.file_list.addItem(item)
            if entry["path"] == keep:
                self.file_list.setCurrentItem(item)

        n = len(files)
        self.count_label.setText(
            f"{n} .bin file{'' if n == 1 else 's'} found"
            if n
            else "No .bin files in this folder"
        )
        if self.file_list.currentRow() < 0 and n:
            self.file_list.setCurrentRow(0)
        self._on_selection_change(self.file_list.currentRow())

    @staticmethod
    def _item_text(entry: dict) -> str:
        size_mb = entry["size"] / (1024 * 1024)
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(entry["mtime"]))
        tag = entry["tag"] or "?"
        # "slots", not "frames": the count is the file's size in frame-sized
        # slots, which the block-quantised readout pads past whatever the run
        # actually recorded (see _FRAMES_TIP).
        return (
            f"{entry['name']:<34}  {entry['frames']:>9,} slots  "
            f"{size_mb:>8.1f} MB   {tag:<9}  {stamp}"
        )

    def _selected_path(self) -> str | None:
        item = self.file_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _on_selection_change(self, _row: int):
        busy = self._worker is not None and self._worker.isRunning()
        has_file = self._selected_path() is not None
        self.run_btn.setEnabled(has_file and not busy)
        self.run_btn.setToolTip(
            "" if has_file else "Select a .bin file from the list first"
        )

    # ------------------------------------------------------------------
    # Running the check
    # ------------------------------------------------------------------

    def _run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        filepath = self._selected_path()
        if filepath is None:
            return
        if not os.path.isfile(filepath):
            self.report_label.setText(
                f"⚠  {os.path.basename(filepath)} is no longer there — rescan."
            )
            self._style_report(None)
            return

        nframes = self.nframes_combo.currentData()
        single = bool(self.pixel_combo.currentData())
        params = {
            "filepath": filepath,
            "nframes": nframes or None,  # 0 (shown as "all") = whole file
            "pixel": (
                (self.row_spin.value(), self.col_spin.value())
                if single
                else None
            ),
            "mode": self.mode_combo.currentData(),
        }

        self.run_btn.setEnabled(False)
        self.abort_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.report_label.setText(f"Checking {os.path.basename(filepath)}…")
        self._style_report(None)
        self._t0 = time.perf_counter()

        self._worker = DataQualityWorker(params)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _abort(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.abort()
            self.abort_btn.setEnabled(False)
            self.report_label.setText("Aborting…")

    def _on_error(self, msg: str):
        self.abort_btn.setEnabled(False)
        self._on_selection_change(self.file_list.currentRow())
        self.report_label.setText(f"⚠  {msg}")
        self._style_report(None)

    def _on_finished(self, summary: dict):
        self.abort_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self._on_selection_change(self.file_list.currentRow())

        self._summary = summary
        elapsed = time.perf_counter() - self._t0
        self.report_label.setText(
            format_report(summary) + f"\ntook     {elapsed:.1f} s"
        )
        self._style_report(summary["verdict"])
        self._draw(summary)

    # ------------------------------------------------------------------
    # Plot
    # ------------------------------------------------------------------

    def _on_bins_change(self, _value: int):
        """Redraw the last result at the new bin count — no re-decode, the
        exact histogram is already in hand."""
        if self._summary is not None:
            self._draw(self._summary)

    def _draw(self, summary: dict):
        """Histogram of the TDC codes, with the per-pixel valid-timestamp
        map beside it.

        The histogram is the data_quality plot: a working TDC spreads its
        codes over the full oscillator range, a dead one piles them onto a
        few values. The map answers the follow-up question the histogram
        cannot — whether that timing came from the whole array or from a
        handful of pixels — and costs nothing, since 'unpack' decodes all
        1024 pixels either way.
        """
        self.figure.clear()
        self.figure.set_tight_layout(True)
        ax, ax_map = self.figure.subplots(
            1, 2, gridspec_kw={"width_ratios": [2.4, 1]}
        )

        edges, values = histogram_for_display(
            summary["hist"], self.bins_spin.value()
        )
        if values.size:
            ax.stairs(values, edges, fill=True, color=CYAN, alpha=0.75)
        else:
            ax.text(
                0.5,
                0.5,
                "no valid timestamp in any frame",
                ha="center",
                va="center",
                color=RED,
                transform=ax.transAxes,
            )
        ax.set_xlabel("Timestamp  (TDC code)")
        ax.set_ylabel("Counts")

        pixel = summary["pixel"]
        where = (
            "all 32×32 pixels"
            if pixel is None
            else f"pixel ({pixel[0]},{pixel[1]})"
        )
        ax.set_title(
            f"{os.path.basename(summary['filepath'])} — {where}\n"
            f"n={summary['n_codes']:,},  {summary['unique']} unique,  "
            f"{summary['verdict']}",
            color=_VERDICT_COLOR.get(summary["verdict"], TEXT_DIM),
        )
        for spine in ax.spines.values():
            spine.set_edgecolor(OUTLINE)

        valid = summary["pixel_valid"].astype(np.float64)
        vmax = float(valid.max())
        im = ax_map.imshow(
            valid,
            cmap="gray",
            aspect="equal",
            origin="lower",
            vmin=0.0,
            vmax=vmax if vmax > 0 else 1.0,
        )
        cb = self.figure.colorbar(im, ax=ax_map, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=TEXT_DIM)
        cb.outline.set_edgecolor(OUTLINE)
        ax_map.set_title(
            f"Valid timestamps / pixel\n"
            f"{summary['pixels_live']}/{summary['pixels_total']} pixels",
            color=TEXT_DIM,
        )
        ax_map.set_xlabel("Column")
        ax_map.set_ylabel("Row")
        ax_map.grid(False)
        for spine in ax_map.spines.values():
            spine.set_edgecolor(OUTLINE)

        self.canvas.draw_idle()
