"""The Firmware box every hardware tab uses, and the dialog that adds one.

Single Acquisition, Chain Acquisition and Live View each have a Firmware box.
They used to build it themselves from the two shipped firmwares; now they all
use 'FirmwareCombo', which lists the shipped two, every firmware added to this
install (see 'firmware_store'), and at the bottom "Add custom firmware…",
"Remove custom firmware…" and "Open firmware folder…".

Adding or removing on one tab updates the boxes on the others, without changing
what they have selected -- a tab only reprograms the FPGA on a choice made on
that tab (see 'fpga_state' for why two tabs must never race to do it).

Tabs listen to 'firmwareChanged', not 'currentIndexChanged': the two action
entries are not firmware, and picking one must not look like a firmware change.
"""

from __future__ import annotations

import os
import weakref

from PyQt5.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from . import firmware_store as store
from ._paths import (
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    custom_firmware_dir,
    firmware_bitfile,
)

_ADD = "__add_custom_firmware__"
_REMOVE = "__remove_custom_firmware__"
_OPEN = "__open_firmware_folder__"
_ACTIONS = (_ADD, _REMOVE, _OPEN)

# How each shipped firmware reads in the box, long form and compact (Live View
# has less room in its row).
_SHIPPED_TEXT = {
    FIRMWARE_SHORT_EXPOSURE: ("short_exposure  (9 µs frame)", "short_exposure"),
    FIRMWARE_LONG_EXPOSURE: ("long_exposure  (shutter + 9 µs)", "long_exposure"),
}

TIMING_HELP = {
    FIRMWARE_SHORT_EXPOSURE: (
        "short_exposure timing: the frame is always 9 µs and the shutter opens "
        "for part of it."
    ),
    FIRMWARE_LONG_EXPOSURE: (
        "long_exposure timing: the frame is the shutter time plus 9 µs of "
        "readout."
    ),
}


class _FirmwareList(QObject):
    """Says the list of added firmware changed, so every box re-reads it."""

    changed = pyqtSignal()


FIRMWARE_LIST = _FirmwareList()

# Every live box, so removing a firmware can check none of them has it selected.
_COMBOS: "weakref.WeakSet[FirmwareCombo]" = weakref.WeakSet()


class AddFirmwareDialog(QDialog):
    """Name the added bitstream and say which timing model it follows."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add custom firmware")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)

        intro = QLabel(
            "The bitstream is copied into your own firmware folder, so it "
            "stays in the Firmware box after a restart, and with a newer exe, "
            "even if the original file is moved or deleted. The shipped "
            "short_exposure and long_exposure bitstreams are not changed.\n\n"
            f"Firmware folder: {custom_firmware_dir()}"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        file_label = QLabel(source)
        file_label.setWordWrap(True)
        form.addRow("File:", file_label)

        self._name_edit = QLineEdit(store.suggest_name(source))
        self._name_edit.setToolTip(
            "Shown in the Firmware box and written to metadata.json as\n"
            "firmware_name. Letters, digits, '.', '_' and '-' only."
        )
        self._name_edit.textChanged.connect(self._validate)
        form.addRow("Name:", self._name_edit)
        root.addLayout(form)

        timing_label = QLabel(
            "Which timing does this bitstream follow? This decides what the "
            "Shutter box means, the frame length shown beside it, the rate on "
            "the Live View map, and firmware_version in metadata.json. Ask the "
            "FPGA designers if unsure."
        )
        timing_label.setWordWrap(True)
        root.addWidget(timing_label)

        self._timing_group = QButtonGroup(self)
        for timing in (FIRMWARE_SHORT_EXPOSURE, FIRMWARE_LONG_EXPOSURE):
            radio = QRadioButton(TIMING_HELP[timing])
            radio.setProperty("timing", timing)
            self._timing_group.addButton(radio)
            root.addWidget(radio)
            if timing == FIRMWARE_SHORT_EXPOSURE:
                radio.setChecked(True)

        self._error = QLabel()
        self._error.setObjectName("mutedLabel")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._buttons.button(QDialogButtonBox.Ok).setText("Add")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)
        self._validate()

    def _validate(self):
        ok = store.valid_name(self.name())
        self._error.setText(
            ""
            if ok
            else "Use letters, digits, '.', '_' and '-', starting with a letter "
            "or digit (at most 64 characters), and not short_exposure or "
            "long_exposure."
        )
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def name(self) -> str:
        return self._name_edit.text().strip()

    def timing(self) -> str:
        checked = self._timing_group.checkedButton()
        return checked.property("timing") if checked else FIRMWARE_SHORT_EXPOSURE


class FirmwareCombo(QComboBox):
    """Shipped and added firmware, plus the entries that add and remove one."""

    firmwareChanged = pyqtSignal(str)  # the newly selected firmware key

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self._compact = compact
        self._key = FIRMWARE_SHORT_EXPOSURE
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.populate()
        self.currentIndexChanged.connect(self._on_index)
        FIRMWARE_LIST.changed.connect(self.populate)
        _COMBOS.add(self)

    # -- reading it ----------------------------------------------------

    def key(self) -> str:
        """The selected firmware key (see 'firmware_store')."""
        return self._key

    # -- filling it ----------------------------------------------------

    def populate(self):
        """Re-read the firmware list, keeping the selection where it can.

        Never emits 'firmwareChanged': a list change made on another tab is
        not a choice made on this one. If the selected firmware is gone (it
        cannot be removed while selected, but its folder can be deleted by
        hand), the box moves to short_exposure and does say so.
        """
        self.blockSignals(True)
        try:
            self.clear()
            for key in (FIRMWARE_SHORT_EXPOSURE, FIRMWARE_LONG_EXPOSURE):
                text = _SHIPPED_TEXT[key][1 if self._compact else 0]
                if firmware_bitfile(key) is None:
                    text += "   [bitstream missing]"
                self.addItem(text, userData=key)
            customs = store.list_custom()
            for fw in customs:
                self.addItem(f"{fw.name}  (custom, {fw.timing})", userData=fw.key)
                self.setItemData(
                    self.count() - 1,
                    f"Added from {fw.source_file or 'unknown file'}\n"
                    f"{TIMING_HELP[fw.timing]}\n"
                    f"Kept in {fw.folder}",
                    Qt.ToolTipRole,
                )
            self.insertSeparator(self.count())
            self.addItem("Add custom firmware…", userData=_ADD)
            if customs:
                self.addItem("Remove custom firmware…", userData=_REMOVE)
            self.addItem("Open firmware folder…", userData=_OPEN)
            self.setItemData(
                self.count() - 1, custom_firmware_dir(), Qt.ToolTipRole
            )
            # The list can be wider than the box; let the popup show it whole.
            self.view().setMinimumWidth(self.view().sizeHintForColumn(0) + 24)
        finally:
            self.blockSignals(False)

        if self.findData(self._key) < 0:
            self._key = FIRMWARE_SHORT_EXPOSURE
            self._select(self._key)
            self.firmwareChanged.emit(self._key)
        else:
            self._select(self._key)

    def _select(self, key: str):
        self.blockSignals(True)
        try:
            self.setCurrentIndex(max(0, self.findData(key)))
        finally:
            self.blockSignals(False)

    def select_key(self, key: str):
        """Select *key* as though the user had, emitting 'firmwareChanged'."""
        if self.findData(key) < 0 or key == self._key:
            return
        self._key = key
        self._select(key)
        self.firmwareChanged.emit(key)

    # -- the user picking an entry ----------------------------------------

    def _on_index(self, index: int):
        data = self.itemData(index)
        if data in _ACTIONS:
            # Not a firmware: put the box back, then act once the popup has
            # closed, so the dialog does not open on top of it.
            self._select(self._key)
            action = {_ADD: self._add, _REMOVE: self._remove, _OPEN: self._open}
            QTimer.singleShot(0, action[data])
            return
        if data and data != self._key:
            self._key = data
            self.firmwareChanged.emit(data)

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a firmware bitstream",
            os.path.expanduser("~"),
            "FPGA bitstream (*.bit);;All files (*)",
        )
        if not path:
            return
        if not store.looks_like_bitstream(path):
            answer = QMessageBox.warning(
                self,
                "Add custom firmware",
                f"{os.path.basename(path)} does not start like a Xilinx .bit "
                "file. Power Mgt will most likely fail to load it.\n\n"
                "Add it anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        dialog = AddFirmwareDialog(path, self)
        while dialog.exec_() == QDialog.Accepted:
            name, timing = dialog.name(), dialog.timing()
            replace = False
            if store.get_custom(store.CUSTOM_PREFIX + name) is not None:
                if self._in_use(store.CUSTOM_PREFIX + name):
                    QMessageBox.information(
                        self,
                        "Add custom firmware",
                        f"A firmware called {name} already exists and is "
                        "selected in a Firmware box. Choose another name, or "
                        "select a different firmware in every tab first.",
                    )
                    continue
                answer = QMessageBox.question(
                    self,
                    "Add custom firmware",
                    f"A firmware called {name} already exists. Replace it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    continue
                replace = True
            try:
                fw = store.add_custom(path, name, timing, replace=replace)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Add custom firmware", str(exc))
                return
            FIRMWARE_LIST.changed.emit()
            self.select_key(fw.key)
            return

    def _open(self):
        """Show the firmware folder in Explorer, creating it if need be."""
        folder = custom_firmware_dir()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Open firmware folder", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @staticmethod
    def _in_use(key: str) -> bool:
        return any(combo.key() == key for combo in list(_COMBOS))

    def _remove(self):
        customs = store.list_custom()
        if not customs:
            return
        names = [fw.name for fw in customs]
        name, ok = QInputDialog.getItem(
            self,
            "Remove custom firmware",
            "Firmware to remove from this install:",
            names,
            0,
            False,
        )
        if not ok:
            return
        fw = customs[names.index(name)]
        if self._in_use(fw.key):
            QMessageBox.information(
                self,
                "Remove custom firmware",
                f"{fw.name} is selected in a Firmware box. Select a different "
                "firmware there first (check every tab), then remove it.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Remove custom firmware",
            f"Remove {fw.name}?\n\nThis deletes the app's copy in\n{fw.folder}\n"
            "The file it was added from is not touched"
            + (f":\n{fw.source_file}" if fw.source_file else ".")
            + "\n\nRuns already recorded keep its name and SHA-256 in their "
            "metadata.json.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            store.remove_custom(fw.key)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Remove custom firmware", str(exc))
            return
        FIRMWARE_LIST.changed.emit()
