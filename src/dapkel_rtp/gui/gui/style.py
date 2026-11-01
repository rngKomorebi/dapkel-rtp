"""Stylesheet and matplotlib settings, built from the current theme.

Nothing here chooses a colour: every value comes from
'theme.current_theme()', so the same rules draw Deep Space (the look the
application shipped with) or any other preset. MainWindow re-applies both on
every theme change; ``apply_qss(app)`` and ``apply_mpl_theme()`` are also
called once in main.py, before the first window exists.
"""

from __future__ import annotations

import matplotlib
from PyQt5.QtGui import QColor, QPalette

from .theme import Theme, current_theme, theme_manager

# The window picks this when the interface font is on "auto" and nothing has
# measured the window yet (main.py styles the application before it opens).
DEFAULT_UI_FONT_PX = 15


# ---------------------------------------------------------------------------
# Matplotlib
# ---------------------------------------------------------------------------

# Line and tick geometry: a matter of the plots' proportions, not of colour,
# so it is the same in every theme. Mirrors daplis-rtp setplotparameters().
_MPL_GEOMETRY: dict = {
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


def mpl_rc(theme: Theme | None = None, fontsize: int | None = None) -> dict:
    """The theme as matplotlib rcParams."""
    t = theme or current_theme()
    size = theme_manager().plot_font_size if fontsize is None else fontsize
    return {
        "figure.facecolor": t.figure_bg,
        "axes.facecolor": t.axes_bg,
        "axes.edgecolor": t.axes_edge,
        "axes.labelcolor": t.axes_fg,
        "axes.titlecolor": t.axes_fg,
        "axes.grid": t.grid_on,
        "grid.color": t.grid,
        "grid.linewidth": 0.5,
        "xtick.color": t.axes_fg,
        "ytick.color": t.axes_fg,
        "text.color": t.axes_fg,
        "legend.facecolor": t.surface,
        "legend.edgecolor": t.outline,
        "legend.labelcolor": t.axes_fg,
        "lines.color": t.trace,
        "image.cmap": t.colormap,
        "font.size": size,
        "axes.labelsize": size,
        "axes.titlesize": size - 2,
        "xtick.labelsize": size - 2,
        "ytick.labelsize": size - 2,
        "legend.fontsize": size - 4,
        **_MPL_GEOMETRY,
    }


def apply_mpl_theme() -> None:
    """Push the current theme into matplotlib's global rcParams.

    Global is right here, unlike in daplis-rtp: there is one theme for every
    plot, so whichever canvas draws next should draw in it. Artists already on
    a figure keep their colours -- 'restyle_figure' is for those.
    """
    matplotlib.rcParams.update(mpl_rc())


def restyle_figure(figure, theme: Theme | None = None) -> None:
    """Recolour what is already drawn on *figure*, in place.

    For a plot that cannot simply be redrawn from stored data (the live view
    only has its last frame on screen). Covers what the tabs draw: axes, their
    text and frame, colourbars, and the colormap of every image.
    """
    t = theme or current_theme()
    size = theme_manager().plot_font_size
    figure.set_facecolor(t.figure_bg)
    for ax in figure.axes:
        ax.set_facecolor(t.axes_bg)
        for spine in ax.spines.values():
            spine.set_edgecolor(t.axes_edge)
        ax.tick_params(which="both", colors=t.axes_fg, labelsize=size - 2)
        for label in (ax.xaxis.label, ax.yaxis.label):
            label.set_color(t.axes_fg)
            label.set_fontsize(size)
        ax.title.set_color(t.axes_fg)
        ax.title.set_fontsize(size - 2)
        for image in ax.images:
            image.set_cmap(t.colormap)


# ---------------------------------------------------------------------------
# QSS stylesheet
# ---------------------------------------------------------------------------

def make_qss(base_fs: int = DEFAULT_UI_FONT_PX, theme: Theme | None = None) -> str:
    """Return QSS in *theme*'s colours with font sizes scaled to *base_fs* px."""
    t = theme or current_theme()
    _sm   = max(8, base_fs - 2)   # groupbox label / title
    _mono = max(9, base_fs - 1)   # monospaced widgets (logs, spinboxes)
    # The progress bar runs three points above the other monospaced widgets. It
    # is the one readout watched from across the room during a run that takes
    # minutes, and it is a single line with a whole bar to itself, so there is
    # room for it. TimedProgressBar._MIN_HEIGHT keeps the groove tall enough
    # for this size.
    _bar  = _mono + 3
    return f"""
/* ── Global ─────────────────────────────────────────────────────────── */
* {{
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    font-size: {base_fs}px;
    color: {t.text};
}}

QMainWindow, QDialog, QWidget {{
    background: {t.window};
    color: {t.text};
}}

/* ── Tab bar ─────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t.outline};
    background: {t.window};
}}

QTabBar {{
    background: {t.window_deep};
}}

QTabBar::tab {{
    background: {t.window_deep};
    color: {t.text_dim};
    padding: 8px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: {base_fs}px;
    letter-spacing: 0.03em;
}}

QTabBar::tab:selected {{
    color: {t.accent};
    background: {t.window};
    border-bottom: 2px solid {t.accent};
}}

QTabBar::tab:hover:!selected {{
    color: {t.text};
    background: {t.surface_low};
}}

/* ── GroupBox ────────────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {t.outline};
    border-radius: 2px;
    margin-top: 16px;
    padding: 8px 6px 6px 6px;
    color: {t.outline_var};
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
    color: {t.outline_var};
    font-size: {_sm}px;
    letter-spacing: 0.07em;
    font-weight: bold;
    background: {t.window};
}}

/* ── Line edit ───────────────────────────────────────────────────────── */
QLineEdit {{
    background: {t.surface};
    border: 1px solid {t.outline};
    border-radius: 2px;
    padding: 4px 8px;
    color: {t.text};
    selection-background-color: {t.accent_dim};
}}

QLineEdit:focus {{ border: 1px solid {t.accent}; }}
QLineEdit:hover {{ border: 1px solid {t.outline_var}; }}

/* ── Spin boxes ──────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {t.surface};
    border: 1px solid {t.outline};
    border-radius: 2px;
    padding: 3px 4px;
    color: {t.text};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    selection-background-color: {t.accent_dim};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {t.accent}; }}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {t.surface_mid};
    border: none;
    width: 16px;
    border-radius: 0px;
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t.outline};
}}

/* ── Combo box ───────────────────────────────────────────────────────── */
QComboBox {{
    background: {t.surface};
    border: 1px solid {t.outline};
    border-radius: 2px;
    padding: 3px 8px;
    color: {t.text};
}}

QComboBox:focus {{ border: 1px solid {t.accent}; }}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background: {t.surface_low};
    border: 1px solid {t.outline};
    selection-background-color: {t.accent_dim};
    color: {t.text};
}}

/* ── Buttons (default) ───────────────────────────────────────────────── */
QPushButton {{
    background: {t.surface_mid};
    border: 1px solid {t.outline};
    border-radius: 2px;
    padding: 5px 14px;
    color: {t.text};
}}

QPushButton:hover {{
    background: {t.surface_hi};
    border-color: {t.outline_var};
}}

QPushButton:pressed {{
    background: {t.accent_dim};
    border-color: {t.accent};
}}

QPushButton:disabled {{
    color: {t.outline_var};
    background: {t.surface_low};
    border-color: {t.outline};
}}

/* Run button — primary action */
QPushButton#run_btn {{
    background: {t.accent_dim};
    border: 1px solid {t.accent};
    color: {t.accent_hi};
    font-weight: bold;
    letter-spacing: 0.04em;
}}

QPushButton#run_btn:hover {{
    background: {t.accent_hover};
    border-color: {t.accent_hi};
}}

QPushButton#run_btn:disabled {{
    background: {t.surface_low};
    border-color: {t.outline};
    color: {t.outline_var};
}}

/* Abort / secondary danger button */
QPushButton#abort_btn {{
    background: {t.surface_mid};
    border: 1px solid {t.outline};
    color: {t.text_dim};
}}

QPushButton#abort_btn:enabled {{
    border-color: {t.warn_dim};
    color: {t.warn};
}}

QPushButton#abort_btn:hover:enabled {{
    background: {t.warn_bg};
    border-color: {t.warn};
}}

/* Plot button */
QPushButton#plot_btn {{
    background: {t.accent_dim};
    border: 1px solid {t.accent};
    color: {t.accent_hi};
    font-weight: bold;
}}

QPushButton#plot_btn:hover {{
    background: {t.accent_hover};
}}

QPushButton#plot_btn:disabled {{
    background: {t.surface_low};
    border-color: {t.outline};
    color: {t.outline_var};
}}

/* ── Checkbox ────────────────────────────────────────────────────────── */
QCheckBox {{
    color: {t.text_dim};
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    background: {t.surface};
    border: 1px solid {t.outline};
    border-radius: 2px;
}}

QCheckBox::indicator:checked {{
    background: {t.accent_dim};
    border-color: {t.accent};
}}

QCheckBox::indicator:hover {{
    border-color: {t.outline_var};
}}

/* ── Progress bar ────────────────────────────────────────────────────── */
/* The text is not painted from here: one colour cannot be read over both the
   cyan chunk and the empty groove, so widgets.TimedProgressBar paints it
   itself, dark over the fill and light over the rest. Only the font set here
   reaches it (Qt polishes the widget font from this rule). */
QProgressBar {{
    background: {t.surface};
    border: 1px solid {t.outline};
    border-radius: 2px;
    text-align: center;
    color: {t.text};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_bar}px;
}}

QProgressBar::chunk {{
    background: {t.accent};
    border-radius: 1px;
}}

/* ── Text area (log) ─────────────────────────────────────────────────── */
QTextEdit {{
    background: {t.window_deep};
    border: 1px solid {t.outline};
    border-radius: 2px;
    color: {t.text_dim};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    selection-background-color: {t.accent_dim};
}}

/* ── List (file pickers) ─────────────────────────────────────────────── */
/* Monospaced so the column-aligned rows the Data Quality tab writes stay
   in columns. */
QListWidget {{
    background: {t.window_deep};
    border: 1px solid {t.outline};
    border-radius: 2px;
    color: {t.text_dim};
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: {_mono}px;
    outline: none;
}}

QListWidget::item {{
    padding: 3px 6px;
    border: none;
}}

QListWidget::item:hover {{
    background: {t.surface_low};
    color: {t.text};
}}

QListWidget::item:selected {{
    background: {t.accent_dim};
    color: {t.accent_hi};
}}

/* ── Scrollbars ──────────────────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {t.surface_low};
    border: none;
    width: 7px;
    height: 7px;
}}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {t.outline};
    border-radius: 3px;
    min-height: 20px;
    min-width: 20px;
}}

QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {t.outline_var};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}

/* ── Labels ──────────────────────────────────────────────────────────── */
QLabel {{
    color: {t.text_dim};
    background: transparent;
}}

/* ── Disabled inputs ─────────────────────────────────────────────────── */
/* Buttons already dim themselves; without this the other input widgets look
   live while ignoring every click (the Row/Col pixel spin boxes, greyed out
   whenever the whole array is being pooled). */
QLineEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {t.surface_low};
    border-color: {t.outline};
    color: {t.outline_var};
}}

QLabel:disabled {{ color: {t.outline}; }}

/* ── Matplotlib navigation toolbar ──────────────────────────────────── */
QToolBar {{
    background: {t.surface_low};
    border: none;
    border-bottom: 1px solid {t.outline};
    spacing: 2px;
    padding: 2px;
}}

QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 3px;
    color: {t.text_dim};
}}

QToolBar QToolButton:hover {{
    background: {t.surface_mid};
    border-color: {t.outline};
}}

QToolBar QToolButton:pressed {{
    background: {t.accent_dim};
    border-color: {t.accent};
}}

/* ── Dialog buttons ──────────────────────────────────────────────────── */
QDialogButtonBox QPushButton {{ min-width: 80px; }}

/* ── Tooltip ─────────────────────────────────────────────────────────── */
QToolTip {{
    background: {t.surface_mid};
    border: 1px solid {t.outline};
    color: {t.text};
    padding: 4px 6px;
    border-radius: 2px;
}}

/* ── Named labels ────────────────────────────────────────────────────── */
/* Labels that differ from their neighbours carry an object name and get
   their look here, so a theme change reaches them (an inline stylesheet
   would keep the colour it was built with). */
QLabel#mutedLabel {{ color: {t.outline_var}; }}

QLabel#monoLabel, QLabel#mutedMono {{
    font-family: "JetBrains Mono", "Consolas", monospace;
}}

QLabel#mutedMono {{ color: {t.outline_var}; }}

/* ── User guide (Help) ───────────────────────────────────────────────── */
/* The guide is a QTextEdit and its contents a QListWidget, which the log
   and file-list rules above set in monospace; prose reads better in the
   interface font. */
QTextBrowser#helpBrowser, QListWidget#helpContents {{
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    font-size: {base_fs}px;
    color: {t.text};
}}

/* ── Chain acquisition job rows ──────────────────────────────────────── */
JobBlock {{
    background: {t.surface_low};
    border: 1px solid {t.outline};
    border-radius: 2px;
}}

/* ── Menus ───────────────────────────────────────────────────────────── */
QMenuBar {{
    background: {t.window_deep};
    border-bottom: 1px solid {t.outline};
}}

QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
}}

QMenuBar::item:selected, QMenu::item:selected {{
    background: {t.accent_dim};
    color: {t.accent_hi};
}}

QMenu {{
    background: {t.surface_low};
    border: 1px solid {t.outline};
    padding: 4px 0;
}}

QMenu::item {{
    padding: 4px 24px 4px 24px;
}}

QMenu::separator {{
    height: 1px;
    background: {t.outline};
    margin: 4px 8px;
}}
"""


def ui_font_px(auto_px: int = DEFAULT_UI_FONT_PX) -> int:
    """The interface font: the user's size, or *auto_px* when it is on auto."""
    return theme_manager().ui_font_size or auto_px


def apply_qss(app, base_fs: int = DEFAULT_UI_FONT_PX) -> None:
    """Apply the stylesheet in the current theme, and fix the palette so
    spin-box arrows are visible.

    *base_fs* is the size the window would pick for itself; a size set in
    Preferences overrides it.
    """
    t = current_theme()
    app.setStyleSheet(make_qss(ui_font_px(base_fs), t))
    pal = app.palette()
    pal.setColor(QPalette.Active,   QPalette.ButtonText, QColor(t.text_dim))
    pal.setColor(QPalette.Inactive, QPalette.ButtonText, QColor(t.text_dim))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t.outline_var))
    app.setPalette(pal)
