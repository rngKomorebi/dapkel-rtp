"""The Preferences window: pick a theme, or build one.

Ported from daplis-rtp. Deliberately not modal: every change is applied the
moment it is made, to the window and to every plot already drawn, so the way to
choose a colour is to put this window beside the plot and watch the plot
change. A modal dialog with an "Apply" button would mean choosing colours from
memory.

Nothing here computes a look. It reads and writes
:class:`~dapkel_rtp.gui.gui.theme.ThemeManager`, which is what everything else
reads too.
"""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from .theme import (
    COLORMAPS,
    PLOT_FONT_RANGE,
    UI_FONT_AUTO,
    UI_FONT_RANGE,
    preset_names,
    theme_manager,
)

MARGIN = 12
SPACING = 8

# Width of the colour buttons and of the fields beside them, so the left edge
# of every field in the window lines up with the one above it.
FIELD_WIDTH = 110

# The theme fields offered as colour pickers, as (field, caption, tip).
INTERFACE_COLOURS = (
    (
        "window",
        "Window background",
        "The window, the tab pages and the selected tab.\n"
        "The hover shade of the tab bar and lists follows it.",
    ),
    (
        "window_deep",
        "Panels",
        "The tab bar, the log and the file lists.",
    ),
    (
        "surface",
        "Input fields",
        "Line edits, spin boxes, drop-down boxes, check boxes\nand the progress bar.",
    ),
    (
        "surface_mid",
        "Buttons",
        "Buttons, spin-box arrows and tooltips.\nThe hover shade follows it.",
    ),
    ("outline", "Borders", "Every thin border: fields, buttons, group boxes, tables."),
    (
        "text",
        "Text",
        "The main text: values in the fields, button captions\n"
        "and tooltips.",
    ),
    (
        "text_dim",
        "Secondary text",
        "Field labels, unselected tabs, check boxes, the log\n"
        "and the file lists.",
    ),
    (
        "outline_var",
        "Muted text",
        "Group-box titles, disabled controls, notes,\nand borders under the mouse.",
    ),
    (
        "accent",
        "Accent",
        "The selected tab, the focus ring, the progress fill and the Run\n"
        "buttons. Their fill and text shades are worked out from it.",
    ),
)

STATUS_COLOURS = (
    ("ok", "OK", "A PASS verdict on the Data Quality tab."),
    (
        "warn",
        "Warning",
        "Abort and Stop while they can be pressed, and a SUSPECT\n"
        "verdict. Their border and hover shades follow it.",
    ),
    (
        "error",
        "Error",
        "A FAIL verdict, and the \"no valid timestamp\" note\n"
        "on the Data Quality histogram.",
    ),
)

PLOT_COLOURS = (
    ("figure_bg", "Figure background", "Behind the axes, and the margin."),
    (
        "axes_bg",
        "Plot background",
        "Inside the axes. Setting it apart from the figure background\n"
        "frames the data; setting it the same keeps the plot flat.",
    ),
    ("axes_fg", "Ticks and labels", "Everything on the axes read as text."),
    (
        "axes_edge",
        "Axes frame",
        "The box round the data, and the colourbar outline.",
    ),
    ("grid", "Grid", "The grid lines, when the grid is switched on."),
    (
        "trace",
        "Histogram",
        "The timestamp histogram on the Data Quality tab.",
    ),
)


def _readable_on(colour: str) -> str:
    """Black or white, whichever can be read on *colour*.

    The picker buttons carry their own hex code as a label, and a light grey
    code on a light grey button is no label at all.
    """
    shade = QtGui.QColor(colour)
    if not shade.isValid():
        return "#000000"
    # Rec. 601 luma: the eye weights green far above blue, so a plain mean of
    # the channels calls yellow dark and blue light.
    luma = 0.299 * shade.red() + 0.587 * shade.green() + 0.114 * shade.blue()
    return "#000000" if luma > 140 else "#ffffff"


class ColourButton(QtWidgets.QPushButton):
    """A button that is the colour it stands for, and opens a picker."""

    picked = QtCore.pyqtSignal(str)

    def __init__(self, colour: str, parent=None, title: str = "Choose a colour"):
        super().__init__(parent)
        self._title = title
        self._colour = colour
        self.setFixedWidth(FIELD_WIDTH)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.set_colour(colour)
        self.clicked.connect(self._choose)

    def set_colour(self, colour: str):
        self._colour = colour
        self.setText(colour)
        # An instance stylesheet beats the application one for this widget,
        # which is what keeps the theme's button rule from painting over it.
        self.setStyleSheet(
            "QPushButton {{"
            " background: {}; color: {};"
            " border: 1px solid #7a7a7a; padding: 3px;"
            "}}".format(colour, _readable_on(colour))
        )

    def colour(self) -> str:
        return self._colour

    def _choose(self):
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._colour), self, self._title
        )
        if chosen.isValid():
            self.set_colour(chosen.name())
            self.picked.emit(chosen.name())


class PreferencesDialog(QtWidgets.QDialog):
    """Theme, colours, colormap and font sizes, applied as chosen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        # A window of its own rather than a sheet over the tab, so it can be
        # put beside the plot it is being used to colour.
        self.setWindowFlags(QtCore.Qt.Window)
        self.setModal(False)

        self._manager = theme_manager()
        self._colour_buttons: dict[str, ColourButton] = {}
        # Set while the widgets are being written to from the theme, so that
        # doing so does not read back as the user changing them.
        self._loading = False

        self._build_ui()
        self.reload()
        self._manager.changed.connect(self.reload)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.setSpacing(SPACING)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Theme", self))
        self.preset_combo = QtWidgets.QComboBox(self)
        for key, name in preset_names():
            self.preset_combo.addItem(name, key)
        self.preset_combo.setToolTip(
            "A starting point. Any colour below can be changed\n"
            "afterwards; picking a preset again clears those changes."
        )
        self.preset_combo.activated.connect(self._preset_chosen)
        preset_row.addWidget(self.preset_combo, 1)
        outer.addLayout(preset_row)

        # Two columns: one long list of colours would run off a laptop screen.
        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(SPACING)
        left = QtWidgets.QVBoxLayout()
        interface, status = self._interface_box(), self._status_box()
        left.addWidget(interface)
        left.addWidget(status)
        left.addStretch(1)
        self._aligned_forms = (interface.layout(), status.layout())
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self._plot_box())
        right.addStretch(1)
        columns.addLayout(left)
        columns.addLayout(right)
        outer.addLayout(columns, 1)

        buttons = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton("Reset to defaults", self)
        reset.setToolTip(
            "Back to Deep Space and the shipped font sizes,\n"
            "throwing away every change made here."
        )
        reset.clicked.connect(self._manager.reset)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.hide)
        buttons.addWidget(close)
        outer.addLayout(buttons)

    def _interface_box(self):
        box = QtWidgets.QGroupBox("Interface", self)
        form = QtWidgets.QFormLayout(box)
        form.setSpacing(SPACING)

        for field, caption, tip in INTERFACE_COLOURS:
            form.addRow(caption, self._colour_button(field, caption, tip, box))

        # A combo, not a spin box: "auto" is not a size, and a spin box can
        # only offer it by giving up the bottom of its range.
        self.ui_font_combo = QtWidgets.QComboBox(box)
        self.ui_font_combo.addItem("Auto", UI_FONT_AUTO)
        for px in range(UI_FONT_RANGE[0], UI_FONT_RANGE[1] + 1):
            self.ui_font_combo.addItem(f"{px} px", px)
        self.ui_font_combo.setFixedWidth(FIELD_WIDTH)
        self.ui_font_combo.setToolTip(
            "Size of the text in the window.\n"
            "Auto follows the window height: 15 px, rising to 18 px\n"
            "on a tall window."
        )
        self.ui_font_combo.activated.connect(self._ui_font_chosen)
        form.addRow("Font size", self.ui_font_combo)
        return box

    def _status_box(self):
        box = QtWidgets.QGroupBox("Status", self)
        form = QtWidgets.QFormLayout(box)
        form.setSpacing(SPACING)
        for field, caption, tip in STATUS_COLOURS:
            form.addRow(caption, self._colour_button(field, caption, tip, box))
        return box

    def _plot_box(self):
        box = QtWidgets.QGroupBox("Plots", self)
        form = QtWidgets.QFormLayout(box)
        form.setSpacing(SPACING)

        for field, caption, tip in PLOT_COLOURS:
            form.addRow(caption, self._colour_button(field, caption, tip, box))

        self.colormap_combo = QtWidgets.QComboBox(box)
        for name in COLORMAPS:
            self.colormap_combo.addItem(name, name)
        self.colormap_combo.setFixedWidth(FIELD_WIDTH)
        self.colormap_combo.setToolTip(
            "Colormap of the hitmaps on the Live View and Data Quality tabs."
        )
        self.colormap_combo.activated.connect(self._colormap_chosen)
        form.addRow("Hitmap colormap", self.colormap_combo)

        self.plot_font_spin = QtWidgets.QSpinBox(box)
        self.plot_font_spin.setRange(*PLOT_FONT_RANGE)
        self.plot_font_spin.setSuffix(" pt")
        self.plot_font_spin.setFixedWidth(FIELD_WIDTH)
        self.plot_font_spin.setToolTip(
            "Size of the axis labels. Titles and tick labels run two\n"
            "points smaller."
        )
        self.plot_font_spin.valueChanged.connect(self._plot_font_changed)
        form.addRow("Font size", self.plot_font_spin)

        self.grid_check = QtWidgets.QCheckBox("Grid", box)
        self.grid_check.setToolTip(
            "Grid lines behind the histogram, in the grid colour above.\n"
            "Never over a hitmap: there it would cross the pixels."
        )
        self.grid_check.toggled.connect(self._grid_toggled)
        form.addRow("", self.grid_check)
        return box

    def _align_labels(self):
        """One label width for the forms stacked in the left column, so their
        fields start at the same x rather than each form's own.

        Redone on every theme change: the width follows the font size.
        """
        labels = [
            form.itemAt(row, QtWidgets.QFormLayout.LabelRole).widget()
            for form in self._aligned_forms
            for row in range(form.rowCount())
            if form.itemAt(row, QtWidgets.QFormLayout.LabelRole) is not None
        ]
        for label in labels:
            label.ensurePolished()  # the stylesheet's font, not the default
        width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(width)

    def _colour_button(self, field, caption, tip, parent):
        button = ColourButton("#000000", parent, f"{caption} colour")
        button.setToolTip(tip)
        button.picked.connect(lambda colour, name=field: self._override(name, colour))
        self._colour_buttons[field] = button
        return button

    # ------------------------------------------------------------------
    # Reading the theme back into the widgets
    # ------------------------------------------------------------------

    def reload(self):
        """Show what the theme currently says.

        Connected to the theme as well as called at build time, so that a
        reset -- or a preset picked from the View menu while this window is
        open -- moves the controls rather than leaving them on the old values.
        """
        self._loading = True
        try:
            theme = self._manager.theme
            for combo, value in (
                (self.preset_combo, self._manager.preset_key),
                (self.ui_font_combo, self._manager.ui_font_size),
                (self.colormap_combo, theme.colormap),
            ):
                index = combo.findData(value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            for field, button in self._colour_buttons.items():
                button.set_colour(getattr(theme, field))
            self.plot_font_spin.setValue(self._manager.plot_font_size)
            self.grid_check.setChecked(theme.grid_on)
            self._align_labels()
        finally:
            self._loading = False

    # ------------------------------------------------------------------
    # Writing the widgets back into the theme
    # ------------------------------------------------------------------

    def _preset_chosen(self, index: int):
        if not self._loading:
            self._manager.set_preset(self.preset_combo.itemData(index))

    def _override(self, field: str, value):
        if not self._loading:
            self._manager.set_override(field, value)

    def _ui_font_chosen(self, index: int):
        if not self._loading:
            self._manager.set_ui_font_size(self.ui_font_combo.itemData(index))

    def _colormap_chosen(self, index: int):
        if not self._loading:
            self._manager.set_override("colormap", self.colormap_combo.itemData(index))

    def _plot_font_changed(self, value: int):
        if not self._loading:
            self._manager.set_plot_font_size(value)

    def _grid_toggled(self, on: bool):
        if not self._loading:
            self._manager.set_override("grid_on", on)

    def open_beside(self):
        self.show()
        self.raise_()
        self.activateWindow()
