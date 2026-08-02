"""Deep Space visual theme for Kelpie v2 GUI.

Colour palette derived from the stitch_spad_vision_studio DESIGN.md.
Call ``apply_qss(app)`` once in main(), then ``MPL`` dict is available
for wiring into matplotlib Figure / rcParams.
"""

from __future__ import annotations

import matplotlib
from PyQt5.QtGui import QColor, QPalette

# ---------------------------------------------------------------------------
# Colour tokens (mirror DESIGN.md)
# ---------------------------------------------------------------------------
BG = "#131315"
BG_DEEP = "#0e0e10"
SURFACE_LOW = "#1b1b1d"
SURFACE = "#201f21"
SURFACE_MID = "#2a2a2c"
SURFACE_HI = "#353437"
OUTLINE = "#3a494b"
OUTLINE_VAR = "#849495"
TEXT = "#e5e1e4"
TEXT_DIM = "#b9cacb"
CYAN = "#00dbe7"
CYAN_DIM = "#004f54"
CYAN_HI = "#74f5ff"
AMBER = "#ffba20"
RED = "#ff3b30"

# ---------------------------------------------------------------------------
# Matplotlib colour map (apply to Figure / rcParams)
# ---------------------------------------------------------------------------
MPL: dict = {
    "figure.facecolor": BG,
    "axes.facecolor": SURFACE_LOW,
    "axes.edgecolor": OUTLINE,
    "axes.labelcolor": TEXT_DIM,
    "axes.titlecolor": TEXT_DIM,
    "axes.grid": True,
    "grid.color": SURFACE_MID,
    "grid.linewidth": 0.5,
    "xtick.color": TEXT_DIM,
    "ytick.color": TEXT_DIM,
    "text.color": TEXT_DIM,
    "legend.facecolor": SURFACE,
    "legend.edgecolor": OUTLINE,
    "legend.labelcolor": TEXT_DIM,
    "lines.color": CYAN,
    # Typography — mirrors daplis-rtp setplotparameters(fontsize=16)
    "font.size": 16,
    "axes.labelsize": 16,
    "axes.titlesize": 14,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
    "legend.fontsize": 12,
    "axes.linewidth": 2,
    "xtick.major.width": 2,
    "ytick.major.width": 2,
    "xtick.minor.width": 1,
    "ytick.minor.width": 1,
    "xtick.major.size": 7,
    "ytick.major.size": 7,
    "xtick.minor.size": 4,
    "ytick.minor.size": 4,
    "xtick.direction": "in",
    "ytick.direction": "in",
}


def apply_mpl_dark() -> None:
    """Push Deep Space colours into matplotlib's global rcParams."""
    matplotlib.rcParams.update(MPL)


# ---------------------------------------------------------------------------
# QSS stylesheet
# ---------------------------------------------------------------------------

def make_qss(base_fs: int = 15) -> str:
    """Return QSS with font sizes scaled to *base_fs* pixels."""
    _sm   = max(8, base_fs - 2)   # groupbox label / title
    _mono = max(9, base_fs - 1)   # monospaced widgets (logs, spinboxes, progress)
    return f"""
/* ── Global ─────────────────────────────────────────────────────────── */
* {{
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    font-size: {base_fs}px;
    color: {TEXT};
}}

QMainWindow, QDialog, QWidget {{
    background: {BG};
    color: {TEXT};
}}

/* ── Tab bar ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {OUTLINE};
    background: {BG};
}}

QTabBar {{
    background: {BG_DEEP};
}}

QTabBar::tab {{
    background: {BG_DEEP};
    color: {TEXT_DIM};
    padding: 8px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: {base_fs}px;
    letter-spacing: 0.03em;
}}

QTabBar::tab:selected {{
    color: {CYAN};
    background: {BG};
    border-bottom: 2px solid {CYAN};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT};
    background: {SURFACE_LOW};
}}

/* ── GroupBox ────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    margin-top: 16px;
    padding: 8px 6px 6px 6px;
    color: {OUTLINE_VAR};
    font-size: {_sm}px;
    letter-spacing: 0.07em;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    top: -1px;
    padding: 0 4px;
    color: {OUTLINE_VAR};
    font-size: {_sm}px;
    letter-spacing: 0.07em;
    font-weight: bold;
    background: {BG};
}}

/* ── Line edit ───────────────────────────────────────────────────────── */
QLineEdit {{
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    padding: 4px 8px;
    color: {TEXT};
    selection-background-color: {CYAN_DIM};
}}

QLineEdit:focus {{ border: 1px solid {CYAN}; }}
QLineEdit:hover {{ border: 1px solid {OUTLINE_VAR}; }}

/* ── Spin boxes ──────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    padding: 3px 4px;
    color: {TEXT};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    selection-background-color: {CYAN_DIM};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {CYAN}; }}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {SURFACE_MID};
    border: none;
    width: 16px;
    border-radius: 0px;
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {OUTLINE};
}}

/* ── Combo box ───────────────────────────────────────────────────────── */
QComboBox {{
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    padding: 3px 8px;
    color: {TEXT};
}}

QComboBox:focus {{ border: 1px solid {CYAN}; }}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background: {SURFACE_LOW};
    border: 1px solid {OUTLINE};
    selection-background-color: {CYAN_DIM};
    color: {TEXT};
}}

/* ── Buttons (default) ───────────────────────────────────────────────── */
QPushButton {{
    background: {SURFACE_MID};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    padding: 5px 14px;
    color: {TEXT};
}}

QPushButton:hover {{
    background: {SURFACE_HI};
    border-color: {OUTLINE_VAR};
}}

QPushButton:pressed {{
    background: {CYAN_DIM};
    border-color: {CYAN};
}}

QPushButton:disabled {{
    color: {OUTLINE_VAR};
    background: {SURFACE_LOW};
    border-color: {OUTLINE};
}}

/* Run button — primary action */
QPushButton#run_btn {{
    background: {CYAN_DIM};
    border: 1px solid {CYAN};
    color: {CYAN_HI};
    font-weight: bold;
    letter-spacing: 0.04em;
}}

QPushButton#run_btn:hover {{
    background: #006a71;
    border-color: {CYAN_HI};
}}

QPushButton#run_btn:disabled {{
    background: {SURFACE_LOW};
    border-color: {OUTLINE};
    color: {OUTLINE_VAR};
}}

/* Abort / secondary danger button */
QPushButton#abort_btn {{
    background: {SURFACE_MID};
    border: 1px solid {OUTLINE};
    color: {TEXT_DIM};
}}

QPushButton#abort_btn:enabled {{
    border-color: #693800;
    color: {AMBER};
}}

QPushButton#abort_btn:hover:enabled {{
    background: #412d00;
    border-color: {AMBER};
}}

/* Plot button */
QPushButton#plot_btn {{
    background: {CYAN_DIM};
    border: 1px solid {CYAN};
    color: {CYAN_HI};
    font-weight: bold;
}}

QPushButton#plot_btn:hover {{
    background: #006a71;
}}

QPushButton#plot_btn:disabled {{
    background: {SURFACE_LOW};
    border-color: {OUTLINE};
    color: {OUTLINE_VAR};
}}

/* ── Checkbox ────────────────────────────────────────────────────────── */
QCheckBox {{
    color: {TEXT_DIM};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
}}

QCheckBox::indicator:checked {{
    background: {CYAN_DIM};
    border-color: {CYAN};
}}

QCheckBox::indicator:hover {{
    border-color: {OUTLINE_VAR};
}}

/* ── Progress bar ────────────────────────────────────────────────────── */
QProgressBar {{
    background: {SURFACE};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    text-align: center;
    color: {TEXT_DIM};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
}}

QProgressBar::chunk {{
    background: {CYAN};
    border-radius: 1px;
}}

/* ── Text area (log) ─────────────────────────────────────────────────── */
QTextEdit {{
    background: {BG_DEEP};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    color: {TEXT_DIM};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    selection-background-color: {CYAN_DIM};
}}

/* ── List (file pickers) ─────────────────────────────────────────────── */
/* Monospaced so the column-aligned rows the Data Quality tab writes stay
   in columns. */
QListWidget {{
    background: {BG_DEEP};
    border: 1px solid {OUTLINE};
    border-radius: 2px;
    color: {TEXT_DIM};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    outline: none;
}}

QListWidget::item {{
    padding: 3px 6px;
    border: none;
}}

QListWidget::item:hover {{
    background: {SURFACE_LOW};
    color: {TEXT};
}}

QListWidget::item:selected {{
    background: {CYAN_DIM};
    color: {CYAN_HI};
}}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {SURFACE_LOW};
    border: none;
    width: 7px;
    height: 7px;
}}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {OUTLINE};
    border-radius: 3px;
    min-height: 20px;
    min-width: 20px;
}}

QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {OUTLINE_VAR};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}

/* ── Labels ──────────────────────────────────────────────────────────── */
QLabel {{
    color: {TEXT_DIM};
    background: transparent;
}}

/* ── Disabled inputs ─────────────────────────────────────────────────── */
/* Buttons already dim themselves; without this the other input widgets look
   live while ignoring every click (the Row/Col pixel spin boxes, greyed out
   whenever the whole array is being pooled). */
QLineEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {SURFACE_LOW};
    border-color: {OUTLINE};
    color: {OUTLINE_VAR};
}}

QLabel:disabled {{ color: {OUTLINE}; }}

/* ── Matplotlib navigation toolbar ──────────────────────────────────── */
QToolBar {{
    background: {SURFACE_LOW};
    border: none;
    border-bottom: 1px solid {OUTLINE};
    spacing: 2px;
    padding: 2px;
}}

QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 3px;
    color: {TEXT_DIM};
}}

QToolBar QToolButton:hover {{
    background: {SURFACE_MID};
    border-color: {OUTLINE};
}}

QToolBar QToolButton:pressed {{
    background: {CYAN_DIM};
    border-color: {CYAN};
}}

/* ── Dialog buttons ──────────────────────────────────────────────────── */
QDialogButtonBox QPushButton {{ min-width: 80px; }}

/* ── Tooltip ─────────────────────────────────────────────────────────── */
QToolTip {{
    background: {SURFACE_MID};
    border: 1px solid {OUTLINE};
    color: {TEXT};
    padding: 4px 6px;
    border-radius: 2px;
}}
"""


def apply_qss(app, base_fs: int = 15) -> None:
    """Apply the Deep Space stylesheet and fix palette so spinbox arrows are visible."""
    app.setStyleSheet(make_qss(base_fs))
    pal = app.palette()
    pal.setColor(QPalette.Active,   QPalette.ButtonText, QColor(TEXT_DIM))
    pal.setColor(QPalette.Inactive, QPalette.ButtonText, QColor(TEXT_DIM))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(OUTLINE_VAR))
    app.setPalette(pal)
