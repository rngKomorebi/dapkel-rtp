"""The Live View's hot-pixel mask, in a window of its own.

Ported from daplis-rtp's pixel mask, which masks a pixel on a Ctrl+click on
the plot or from a window that can stay open beside it while the stream runs.
daplis-rtp's sensor is a line of 256 pixels, so its window is one check box
per pixel. This one is a 32x32 or 64x64 map, 1024 or 4096 boxes, so the window
lists the masked pixels instead and takes new ones typed as ``row,col``.

The window holds one mask per map shape. Pixel (5, 12) of the 32x32 map and
pixel (5, 12) of the 64x64 composite are different SPADs, so masking one must
not mask the other; switching the mode switches the mask shown.

A mask can be saved for one daughterboard/motherboard pair and loaded again,
as daplis-rtp's preset masks are. One JSON file per pair, ``D0_M0.json``,
holds a mask per map shape::

    {
      "daughterboard": "D0",
      "motherboard": "M0",
      "saved": "2026-11-04T10:15:00",
      "masks": {
        "32x32": [[3, 7], [5, 12]],
        "64x64": [[40, 2]]
      }
    }

JSON rather than daplis-rtp's comma-separated .txt of pixel numbers, because
a pixel here is a (row, col) pair and the file has to say which map each
mask belongs to; it stays readable and editable by hand.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


def _parse_part(text: str, n: int) -> range:
    """One row or column: '12', or an inclusive range '0-3' / '0:3'."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:[-:]\s*(\d+)\s*)?", text)
    if not m:
        raise ValueError(f"'{text.strip()}' is not a number or a range")
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    lo, hi = min(lo, hi), max(lo, hi)
    if hi >= n:
        raise ValueError(f"{hi} is outside 0-{n - 1}")
    return range(lo, hi + 1)


def parse_pixel_list(text: str, rows: int, cols: int) -> list[tuple[int, int]]:
    """Pixels typed as ``row,col`` entries separated by semicolons.

    Either half may be a range, so ``5,12; 30,0-3`` is pixel (5, 12) plus
    the first four columns of row 30. Raises ValueError on anything else.
    """
    pixels = []
    for entry in re.split(r"[;\n]", text):
        if not entry.strip():
            continue
        parts = entry.split(",")
        if len(parts) != 2:
            raise ValueError(f"'{entry.strip()}' is not row,col")
        rs = _parse_part(parts[0], rows)
        cs = _parse_part(parts[1], cols)
        pixels.extend((r, c) for r in rs for c in cs)
    return pixels


# ---------------------------------------------------------------------------
# Saved masks
# ---------------------------------------------------------------------------


def mask_key(rows: int, cols: int) -> str:
    """The key a map shape's mask is stored under: '32x32'."""
    return f"{rows}x{cols}"


def board_name(text: str, prefix: str) -> str | None:
    """'D0' as typed, or '0' with the prefix added; None if unusable.

    Upper-cased so that 'd0' and 'D0' name the same file, and limited to
    letters, digits and '-' because the name goes into a file name, where
    '_' already separates the two boards.
    """
    text = text.strip().upper()
    if text.isdigit():
        text = prefix + text
    return text if re.fullmatch(r"[A-Z0-9-]+", text) else None


def mask_file_name(daughterboard: str, motherboard: str) -> str:
    return f"{daughterboard}_{motherboard}.json"


def read_mask_file(path: str) -> dict:
    """The saved file as a dict. Raises OSError or ValueError if unreadable."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("masks"), dict):
        raise ValueError("not a saved pixel mask")
    return data


def write_mask_file(
    path: str,
    daughterboard: str,
    motherboard: str,
    shape: tuple[int, int],
    pixels,
    existing: dict | None = None,
):
    """Write one shape's mask, keeping the other shapes already in the file."""
    masks = dict(existing["masks"]) if existing else {}
    masks[mask_key(*shape)] = [[int(r), int(c)] for r, c in sorted(pixels)]
    data = {
        "daughterboard": daughterboard,
        "motherboard": motherboard,
        "saved": datetime.now().isoformat(timespec="seconds"),
        "masks": masks,
    }
    text = json.dumps(data, indent=2)
    # One pixel per line, '[3, 7]', rather than json's row and col on lines of
    # their own: the file is meant to be read and edited by hand.
    text = re.sub(r"\[\s+(\d+),\s+(\d+)\s+\]", r"[\1, \2]", text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def saved_pixels(data: dict, rows: int, cols: int) -> list[tuple[int, int]] | None:
    """The pixels saved for a rows x cols map, or None if there are none.

    Raises ValueError on an entry that is not a pixel of that map, so a file
    edited by hand cannot mask something that is not there.
    """
    entries = data["masks"].get(mask_key(rows, cols))
    if entries is None:
        return None
    pixels = []
    for entry in entries:
        try:
            r, c = (int(v) for v in entry)
        except (TypeError, ValueError):
            raise ValueError(f"{entry!r} is not a [row, col] pair") from None
        if not (0 <= r < rows and 0 <= c < cols):
            raise ValueError(f"[{r}, {c}] is outside the {rows}×{cols} map")
        pixels.append((r, c))
    return pixels


class SaveMaskDialog(QDialog):
    """Ask which daughterboard and motherboard the mask belongs to."""

    def __init__(
        self,
        parent,
        folder: str,
        n_pixels: int,
        shape: tuple[int, int],
        daughterboard: str = "",
        motherboard: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Save pixel mask")
        self._folder = folder

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{n_pixels} masked pixel(s) of the {shape[0]}×{shape[1]} map."
            )
        )
        form = QFormLayout()
        self.db_edit = QLineEdit(daughterboard)
        self.db_edit.setPlaceholderText("D0")
        self.mb_edit = QLineEdit(motherboard)
        self.mb_edit.setPlaceholderText("M0")
        form.addRow("Daughterboard:", self.db_edit)
        form.addRow("Motherboard:", self.mb_edit)
        layout.addLayout(form)

        # Not word-wrapped: a wrapped label is sized before it wraps, which
        # cut off the last line of a long path. The folder and the file name
        # go on lines of their own instead, and the dialog grows to fit.
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        layout.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self._save_btn = buttons.button(QDialogButtonBox.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.db_edit.textChanged.connect(self._update)
        self.mb_edit.textChanged.connect(self._update)
        self._update()
        self.setMinimumWidth(420)

    def names(self) -> tuple[str | None, str | None]:
        return board_name(self.db_edit.text(), "D"), board_name(
            self.mb_edit.text(), "M"
        )

    def path(self) -> str:
        return os.path.join(self._folder, mask_file_name(*self.names()))

    def _update(self):
        """Show the file it will write, and allow Save only once it can."""
        db, mb = self.names()
        ok = db is not None and mb is not None
        self._save_btn.setEnabled(ok)
        self.path_label.setText(
            f"Saves to the folder\n{self._folder}\nas {os.path.basename(self.path())}"
            if ok
            else "Type both, e.g. D0 and M0: letters, digits and '-'.\n"
            "A plain number gets the D or M added."
        )


class PixelMaskWindow(QDialog):
    """Non-modal window listing the masked pixels of the map in view."""

    # Any pixel masked or unmasked, from here or through toggle().
    changed = pyqtSignal()

    def __init__(self, parent=None, title="Pixel mask — Live View"):
        super().__init__(parent)
        # A plain QDialog sits on top of the tab it came from; 'Qt.Window'
        # gives it a title bar of its own, so it can be put beside the map
        # and left there while the preview runs.
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle(title)
        self.setModal(False)

        self._masks: dict[tuple[int, int], set[tuple[int, int]]] = {}
        self._shape = (32, 32)

        outer = QVBoxLayout(self)

        entry_row = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("5,12; 30,0-3")
        self.entry.setToolTip(
            "Pixels to mask or unmask in one go, as row,col entries separated\n"
            "by semicolons. Either half may be a range: 30,0-3 is the first\n"
            "four columns of row 30. Enter means Mask."
        )
        self.entry.returnPressed.connect(lambda: self._apply_entry(True))
        mask_btn = QPushButton("Mask")
        mask_btn.clicked.connect(lambda: self._apply_entry(True))
        unmask_btn = QPushButton("Unmask")
        unmask_btn.clicked.connect(lambda: self._apply_entry(False))
        entry_row.addWidget(self.entry)
        entry_row.addWidget(mask_btn)
        entry_row.addWidget(unmask_btn)
        outer.addLayout(entry_row)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setToolTip("Double-click a pixel to unmask it.")
        self.list.itemDoubleClicked.connect(
            lambda item: self._set(item.data(Qt.UserRole), False)
        )
        outer.addWidget(self.list)

        self.count_label = QLabel()
        outer.addWidget(self.count_label)

        buttons = QHBoxLayout()
        unmask_sel_btn = QPushButton("Unmask selected")
        unmask_sel_btn.clicked.connect(self._unmask_selected)
        clear_btn = QPushButton("Clear all")
        clear_btn.setToolTip("Unmask every pixel of the map in view.")
        clear_btn.clicked.connect(self.clear)
        close_btn = QPushButton("Close")
        close_btn.setToolTip("Hide the window; the mask stays.")
        close_btn.clicked.connect(self.hide)
        buttons.addWidget(unmask_sel_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        outer.addLayout(buttons)

        self.resize(380, 440)
        self._refresh()

    # ------------------------------------------------------------------
    # What the tab asks
    # ------------------------------------------------------------------

    @property
    def shape(self) -> tuple[int, int]:
        """The map whose mask is shown and edited."""
        return self._shape

    def pixels(self) -> list[tuple[int, int]]:
        """The masked pixels of the map in view, sorted."""
        return sorted(self._current())

    def replace(self, pixels):
        """Make the mask of the map in view exactly these pixels."""
        self._current().clear()
        self._current().update(tuple(p) for p in pixels)
        self._refresh()
        self.changed.emit()

    def set_shape(self, rows: int, cols: int):
        """Show (and edit) the mask of a rows x cols map."""
        if (rows, cols) == self._shape:
            return
        self._shape = (rows, cols)
        self._refresh()

    def mask_for(self, rows: int, cols: int) -> np.ndarray:
        """Boolean map of the given shape, True where a pixel is masked."""
        mask = np.zeros((rows, cols), dtype=bool)
        for r, c in self._masks.get((rows, cols), ()):
            mask[r, c] = True
        return mask

    def summary(self) -> str:
        return f"{len(self._current())} masked"

    def toggle(self, row: int, col: int):
        """Ctrl+click on the map: mask this pixel, or unmask it."""
        self._set((row, col), (row, col) not in self._current())

    def clear(self):
        """Unmask every pixel of the map in view."""
        if self._current():
            self._current().clear()
            self._refresh()
            self.changed.emit()

    def open_beside(self):
        """Show the window, raising it if it is already open."""
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    # Behaviour
    # ------------------------------------------------------------------

    def _current(self) -> set[tuple[int, int]]:
        return self._masks.setdefault(self._shape, set())

    def _set(self, pixel, masked: bool):
        pixel = tuple(pixel)
        if masked:
            self._current().add(pixel)
        else:
            self._current().discard(pixel)
        self._refresh()
        self.changed.emit()

    def _apply_entry(self, masked: bool):
        """Mask or unmask the pixels typed in the quick entry, with one signal."""
        try:
            pixels = parse_pixel_list(self.entry.text(), *self._shape)
        except ValueError as err:
            QMessageBox.warning(self, "Pixel mask", f"{err}.")
            return
        if not pixels:
            return
        if masked:
            self._current().update(pixels)
        else:
            self._current().difference_update(pixels)
        self.entry.clear()
        self._refresh()
        self.changed.emit()

    def _unmask_selected(self):
        selected = [item.data(Qt.UserRole) for item in self.list.selectedItems()]
        if not selected:
            return
        self._current().difference_update(tuple(p) for p in selected)
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        """Rebuild the list and the count for the map in view."""
        rows, cols = self._shape
        self.list.clear()
        for r, c in sorted(self._current()):
            item = QListWidgetItem(f"row {r}, col {c}")
            item.setData(Qt.UserRole, (r, c))
            self.list.addItem(item)
        self.count_label.setText(
            f"{len(self._current())} of {rows * cols} pixels masked "
            f"({rows}×{cols} map)"
        )
