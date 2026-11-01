"""Where every colour and font size in the application comes from.

One object holds the lot -- the window palette, the accent, the plot colours,
the colormap the hitmaps are drawn in, the two font sizes -- and one signal
says it has changed. Ported from daplis-rtp, which went through the same
exercise: there the colours had been chosen in a dozen places, here they were
module constants in 'style' imported into every tab, and either way a user who
wanted a lighter window, or a colormap they could read a hitmap in, had nowhere
to say so.

Two rules keep it that way:

* **Widgets do not hard-code a colour.** A widget that needs to look different
  from its neighbours gets an object name and a rule in the stylesheet
  ('style.make_qss'), which is rebuilt from the theme on every change.
* **Plots ask for their colours when they draw.** They hold no copies, so a
  theme change is a redraw, not a rebuild of the tab.

Settings are stored per user through ``QSettings`` -- on Windows in the
registry under ``HKCU\\Software\\DAPKEL\\dapkel-rtp`` -- so two people sharing
the lab PC keep their own.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace

from PyQt5 import QtCore

# 'QSettings' is built with these rather than from the application's own
# names: main.py names the application "DAPKEL-RTP" for the window, and the
# registry key should not move if that label ever does.
ORGANISATION = "DAPKEL"
APPLICATION = "dapkel-rtp"

# Interface font, in pixels -- the unit the stylesheet has always used. 0 means
# "auto": the window picks 15-18 px from its own height, as it did before
# there was a setting (MainWindow._font_size_for_height).
UI_FONT_AUTO = 0
UI_FONT_RANGE = (11, 24)
DEFAULT_UI_FONT_SIZE = UI_FONT_AUTO

# Axis labels, in points. Titles and tick labels run two points under it and
# legends four, the proportions the plots were tuned with at 16.
PLOT_FONT_RANGE = (8, 32)
DEFAULT_PLOT_FONT_SIZE = 16

# Offered in the Preferences window for the hitmaps. Perceptually uniform maps
# first, since a hitmap is read as numbers; the two greys last, 'gray' being
# the one the application shipped with.
COLORMAPS = (
    "gray",
    "gray_r",
    "viridis",
    "cividis",
    "inferno",
    "magma",
    "plasma",
    "hot",
    "bone",
)


@dataclass(frozen=True)
class Theme:
    """A complete look: window, controls and plots together.

    Frozen because a theme is a value, not a thing that is edited. The user's
    changes are kept separately, as overrides, and laid over the preset with
    ``dataclasses.replace`` -- so "reset" is throwing the overrides away.
    """

    key: str
    name: str
    # 'dark' or 'light'. Only used to group the presets in the menu.
    base: str

    # --- interface -------------------------------------------------
    window: str  # the window, tab pages, group-box title backing
    window_deep: str  # tab bar, log and file lists, progress text over the fill
    surface_low: str  # job rows, hover, scrollbar groove, disabled inputs
    surface: str  # inputs: line edits, spin and combo boxes
    surface_mid: str  # buttons, spin-box arrows, tooltips
    surface_hi: str  # button hover
    outline: str  # every 1px border
    outline_var: str  # group-box titles, disabled text, muted labels
    text: str
    text_dim: str  # labels, check boxes, logs

    accent: str  # selected tab, focus ring, progress fill, primary buttons
    accent_dim: str  # primary-button fill, selection background
    accent_hi: str  # text on the primary buttons and on selected list rows
    accent_hover: str  # primary-button fill under the mouse

    ok: str  # a passed data-quality verdict
    warn: str  # Abort/Stop, a suspect verdict
    warn_dim: str  # Abort/Stop border while it can be pressed
    warn_bg: str  # Abort/Stop fill under the mouse
    error: str  # a failed verdict, "no valid timestamp"

    # --- plots -----------------------------------------------------
    figure_bg: str
    axes_bg: str
    axes_fg: str  # ticks, axis labels, titles -- everything read as text
    axes_edge: str  # the box round the data, and the colourbar outline
    grid: str
    grid_on: bool
    trace: str  # the timestamp histogram
    colormap: str  # the hitmaps


PRESETS: dict[str, Theme] = {}


def _preset(theme: Theme) -> Theme:
    PRESETS[theme.key] = theme
    return theme


# ---------------------------------------------------------------------------
# Colour arithmetic
# ---------------------------------------------------------------------------


def _rgb(colour: str) -> tuple[int, int, int]:
    h = colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """The colour *t* of the way from *a* to *b* (0 -> a, 1 -> b)."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#{:02x}{:02x}{:02x}".format(
        round(ra + (rb - ra) * t),
        round(ga + (gb - ga) * t),
        round(ba + (bb - ba) * t),
    )


def accent_shades(window: str, accent: str, text: str) -> dict[str, str]:
    """The three shades the primary buttons need, worked out from the accent.

    Used for every preset but Deep Space, whose shades were picked by hand. A
    user's own accent gets the same mixes, from '_DERIVED'.
    """
    return {
        "accent_dim": mix(window, accent, 0.30),
        "accent_hi": mix(accent, text, 0.45),
        "accent_hover": mix(window, accent, 0.45),
    }


def _ported(
    *,
    key,
    name,
    base,
    window,
    surface,
    text,
    muted,
    accent,
    ok,
    warn,
    error,
    figure_bg,
    axes_bg,
    axes_fg,
    axes_edge,
    grid,
    trace,
    grid_on=True,
    colormap="gray",
) -> Theme:
    """A theme from daplis-rtp's handful of colours.

    daplis-rtp hands most of the chrome to qdarkstyle and so names eight
    interface colours; this application styles every widget itself and needs
    the in-between shades too. They are mixed from the eight -- the steps were
    measured off Deep Space, where window-to-text at 4 %, 10 % and 16 % lands
    on the hand-picked surface tones within a shade.
    """
    deep_target = "#000000" if base == "dark" else text
    return Theme(
        key=key,
        name=name,
        base=base,
        window=window,
        window_deep=mix(window, deep_target, 0.30 if base == "dark" else 0.05),
        surface_low=mix(window, text, 0.04),
        surface=surface,
        surface_mid=mix(window, text, 0.10),
        surface_hi=mix(window, text, 0.16),
        outline=mix(window, muted, 0.35),
        outline_var=muted,
        text=text,
        text_dim=mix(muted, text, 0.50),
        accent=accent,
        **accent_shades(window, accent, text),
        ok=ok,
        warn=warn,
        warn_dim=mix(window, warn, 0.40),
        warn_bg=mix(window, warn, 0.20),
        error=error,
        figure_bg=figure_bg,
        axes_bg=axes_bg,
        axes_fg=axes_fg,
        axes_edge=axes_edge,
        grid=grid,
        grid_on=grid_on,
        trace=trace,
        colormap=colormap,
    )


# ---------------------------------------------------------------------------
# Presets -- dark first, then light: the menu draws a rule where the base
# changes, and a list that alternated would need one between every pair.
# ---------------------------------------------------------------------------

# The look the application shipped with (stitch_spad_vision_studio
# DESIGN.md), every value exactly as it was in 'style'. The default, so an
# existing user opens the new version to the application they know.
_preset(
    Theme(
        key="deep_space",
        name="Deep Space",
        base="dark",
        window="#131315",
        window_deep="#0e0e10",
        surface_low="#1b1b1d",
        surface="#201f21",
        surface_mid="#2a2a2c",
        surface_hi="#353437",
        outline="#3a494b",
        outline_var="#849495",
        text="#e5e1e4",
        text_dim="#b9cacb",
        accent="#00dbe7",
        accent_dim="#004f54",
        accent_hi="#74f5ff",
        accent_hover="#006a71",
        ok="#00dbe7",
        warn="#ffba20",
        warn_dim="#693800",
        warn_bg="#412d00",
        error="#ff3b30",
        figure_bg="#131315",
        axes_bg="#1b1b1d",
        axes_fg="#b9cacb",
        axes_edge="#3a494b",
        grid="#2a2a2c",
        grid_on=True,
        trace="#00dbe7",
        colormap="gray",
    )
)

# The ten below are daplis-rtp's presets, plot colours and all. Six of them are
# in turn ports of the matplotlib styles in komorebi_mpl
# (github.com/rngKomorebi/komorebi_mpl).

# daplis-rtp's own default: near-black, coral traces, neon accent.
_preset(
    _ported(
        key="cyberpunk",
        name="Cyberpunk",
        base="dark",
        window="#14181f",
        surface="#1b212b",
        text="#e3e9f2",
        muted="#8c97a8",
        accent="#08f7fe",
        ok="#00e676",
        warn="#ffc400",
        error="#ff5370",
        figure_bg="#0d0f14",
        axes_bg="#0d0f14",
        axes_fg="#c7d0dd",
        axes_edge="#c7d0dd",
        grid="#2a3140",
        trace="#f48383",
        grid_on=False,
    )
)

_preset(
    _ported(
        key="midnight",
        name="Midnight",
        base="dark",
        window="#19232d",
        surface="#222b35",
        text="#dfe4ec",
        muted="#8a94a3",
        accent="#4d9de0",
        ok="#7fd18b",
        warn="#e7c26b",
        error="#e06c75",
        figure_bg="#19232d",
        axes_bg="#19232d",
        axes_fg="#d8dee9",
        axes_edge="#d8dee9",
        grid="#36404e",
        trace="#61afef",
    )
)

# komorebi_mpl's 'night_wave': synthwave neon on a violet ground.
_preset(
    _ported(
        key="night_wave",
        name="Night wave",
        base="dark",
        window="#221d2f",
        surface="#382c47",
        text="#ffffff",
        muted="#9a8fb0",
        accent="#eb67f5",
        ok="#44d492",
        warn="#f5eb67",
        error="#fa233e",
        figure_bg="#221d2f",
        axes_bg="#221d2f",
        axes_fg="#f2f2f2",
        axes_edge="#bfbfbf",
        grid="#aac7df",
        trace="#eb67f5",
        colormap="magma",
    )
)

# komorebi_mpl's 'blueprint': white and ice-blue on deep navy, the frame a
# dimmer blue than the labels.
_preset(
    _ported(
        key="blueprint",
        name="Blueprint",
        base="dark",
        window="#0d1f3c",
        surface="#142848",
        text="#e8f1fa",
        muted="#b8d4ea",
        accent="#7ec8e3",
        ok="#7ec8e3",
        warn="#f0a030",
        error="#ff6b6b",
        figure_bg="#0d1f3c",
        axes_bg="#0d1f3c",
        axes_fg="#e8f1fa",
        axes_edge="#3a6186",
        grid="#3a6186",
        trace="#7ec8e3",
        colormap="bone",
    )
)

# Maximum separation between the data and everything else.
_preset(
    _ported(
        key="contrast",
        name="High contrast",
        base="dark",
        window="#000000",
        surface="#121212",
        text="#ffffff",
        muted="#b0b0b0",
        accent="#ffd400",
        ok="#00e676",
        warn="#ffd400",
        error="#ff5252",
        figure_bg="#000000",
        axes_bg="#000000",
        axes_fg="#ffffff",
        axes_edge="#ffffff",
        grid="#555555",
        trace="#ffd400",
    )
)

# For a bright room, and for a plot going into a document as it is.
_preset(
    _ported(
        key="daylight",
        name="Daylight",
        base="light",
        window="#f0f2f5",
        surface="#ffffff",
        text="#1c2430",
        muted="#5b6675",
        accent="#1565c0",
        ok="#2e7d32",
        warn="#ef6c00",
        error="#c62828",
        figure_bg="#ffffff",
        axes_bg="#ffffff",
        axes_fg="#1c2430",
        axes_edge="#1c2430",
        grid="#d4d9e0",
        trace="#1565c0",
        colormap="gray_r",
    )
)

# komorebi_mpl's own: deep gold, forest green and sky blue on parchment.
_preset(
    _ported(
        key="komorebi",
        name="Komorebi",
        base="light",
        window="#f0ede2",
        surface="#faf8f0",
        text="#2c2416",
        muted="#6b6252",
        accent="#c8860a",
        ok="#2d6a4f",
        warn="#c8860a",
        error="#9b2335",
        figure_bg="#faf8f0",
        axes_bg="#faf8f0",
        axes_fg="#2c2416",
        axes_edge="#5a5040",
        grid="#c8b898",
        trace="#2d6a4f",
        colormap="cividis",
    )
)

# komorebi_mpl's 'earth': terracotta, rust, olive and sage on aged paper.
_preset(
    _ported(
        key="earth",
        name="Earth",
        base="light",
        window="#ede4ce",
        surface="#f5ecd7",
        text="#2c1810",
        muted="#6b5540",
        accent="#9b2335",
        ok="#5e7a28",
        warn="#d4622a",
        error="#9b2335",
        figure_bg="#f5ecd7",
        axes_bg="#ede0c8",
        axes_fg="#2c1810",
        axes_edge="#a08060",
        grid="#c8b898",
        trace="#d4622a",
        colormap="gray_r",
    )
)

# Solarized, by way of komorebi_mpl. The low contrast is the point of it.
_preset(
    _ported(
        key="solarized",
        name="Solarized",
        base="light",
        window="#eee8d5",
        surface="#fdf6e3",
        text="#586e75",
        muted="#93a1a1",
        accent="#268bd2",
        ok="#859900",
        warn="#b58900",
        error="#dc322f",
        figure_bg="#fdf6e3",
        axes_bg="#eee8d5",
        axes_fg="#657b83",
        axes_edge="#93a1a1",
        grid="#d3ccb8",
        trace="#268bd2",
        colormap="cividis",
    )
)

# komorebi_mpl's 'daplis' house palette, legible for the common forms of
# colour blindness. The one to export a figure in.
_preset(
    _ported(
        key="publication",
        name="Publication",
        base="light",
        window="#f2f2f2",
        surface="#ffffff",
        text="#1a1a1a",
        muted="#5a5a5a",
        accent="#663399",
        ok="#008080",
        warn="#ff8c00",
        error="#8b0000",
        figure_bg="#ffffff",
        axes_bg="#ffffff",
        axes_fg="#000000",
        axes_edge="#000000",
        grid="#bfbfbf",
        trace="#663399",
        colormap="viridis",
    )
)

DEFAULT_PRESET = "deep_space"

# These identify the preset rather than describe it; a stored override for one
# would survive a preset change and make the dialog disagree with the screen.
UNOVERRIDABLE = ("key", "name", "base")

_BOOL_FIELDS = ("grid_on",)

# The shades Preferences does not offer, as (field, the fields it is worked out
# from, how). When the user overrides one of the sources, the shade is worked
# out again from the result -- a new window colour under the old hover fill, or
# a new accent on the old button fill, would look broken rather than chosen.
# Left alone otherwise, so an untouched preset keeps its hand-picked shades.
# Applied in order: a later rule sees what the earlier ones made.
_DERIVED = (
    ("surface_low", ("window", "text"), lambda t: mix(t.window, t.text, 0.04)),
    # 0.07 of the rest of the way to the text is where the ported presets'
    # hover shade sits relative to their button shade.
    ("surface_hi", ("surface_mid", "text"), lambda t: mix(t.surface_mid, t.text, 0.07)),
    ("accent_dim", ("window", "accent"), lambda t: mix(t.window, t.accent, 0.30)),
    ("accent_hi", ("accent", "text"), lambda t: mix(t.accent, t.text, 0.45)),
    ("accent_hover", ("window", "accent"), lambda t: mix(t.window, t.accent, 0.45)),
    ("warn_dim", ("window", "warn"), lambda t: mix(t.window, t.warn, 0.40)),
    ("warn_bg", ("window", "warn"), lambda t: mix(t.window, t.warn, 0.20)),
)


def preset_names() -> list[tuple[str, str]]:
    """``(key, display name)`` for every preset, in the order defined."""
    return [(key, theme.name) for key, theme in PRESETS.items()]


def _clamp(value, bounds) -> int:
    low, high = bounds
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def _ui_font(value) -> int:
    """Auto, or a size inside the range -- never a size outside it."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return UI_FONT_AUTO
    return UI_FONT_AUTO if value == UI_FONT_AUTO else _clamp(value, UI_FONT_RANGE)


class ThemeManager(QtCore.QObject):
    """The live theme, the user's changes to it, and who to tell.

    One per process -- see :func:`theme_manager`. A ``QObject`` so it can emit
    :attr:`changed`, which the window and the plotting tabs connect to; that is
    what makes a colour picked in Preferences show up while the window is
    still open beside the plot.
    """

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preset_key = DEFAULT_PRESET
        # Only what the user actually changed, by field name. Kept apart from
        # the preset so a preset can be swapped under it and 'reset' is a
        # clear().
        self._overrides: dict[str, object] = {}
        self._ui_font_size = DEFAULT_UI_FONT_SIZE
        self._plot_font_size = DEFAULT_PLOT_FONT_SIZE
        self._settings = QtCore.QSettings(ORGANISATION, APPLICATION)
        self.load()

    # -- the effective theme ------------------------------------------

    @property
    def preset_key(self) -> str:
        return self._preset_key

    @property
    def theme(self) -> Theme:
        """The preset with the user's overrides laid over it."""
        base = PRESETS.get(self._preset_key, PRESETS[DEFAULT_PRESET])
        if not self._overrides:
            return base
        theme = replace(base, **self._overrides)
        for name, sources, rule in _DERIVED:
            if name in self._overrides:
                continue  # picked by the user: theirs, not worked out
            if any(source in self._overrides for source in sources):
                theme = replace(theme, **{name: rule(theme)})
        return theme

    @property
    def ui_font_size(self) -> int:
        """Pixels, or ``UI_FONT_AUTO`` to follow the window height."""
        return self._ui_font_size

    @property
    def plot_font_size(self) -> int:
        return self._plot_font_size

    def overrides(self) -> dict:
        """A copy, so a caller editing it cannot change the theme."""
        return copy.deepcopy(self._overrides)

    def is_overridden(self, name: str) -> bool:
        return name in self._overrides

    # -- changing it ---------------------------------------------------

    def set_preset(self, key: str, keep_overrides: bool = False):
        """Switch preset, dropping the overrides unless told otherwise.

        Picking a new preset and getting the last one's accent back is the
        surprising behaviour, not the helpful one.
        """
        if key not in PRESETS:
            return
        self._preset_key = key
        if not keep_overrides:
            self._overrides.clear()
        self._emit()

    def set_override(self, name: str, value):
        """Override one field of the preset, or clear it with ``None``."""
        if name in UNOVERRIDABLE or name not in Theme.__dataclass_fields__:
            return
        if value is None:
            self._overrides.pop(name, None)
        else:
            self._overrides[name] = value
        self._emit()

    def set_ui_font_size(self, pixels: int):
        self._ui_font_size = _ui_font(pixels)
        self._emit()

    def set_plot_font_size(self, points: int):
        self._plot_font_size = _clamp(points, PLOT_FONT_RANGE)
        self._emit()

    def reset(self):
        """Back to the shipped defaults, overrides and fonts included."""
        self._preset_key = DEFAULT_PRESET
        self._overrides.clear()
        self._ui_font_size = DEFAULT_UI_FONT_SIZE
        self._plot_font_size = DEFAULT_PLOT_FONT_SIZE
        self._emit()

    def _emit(self):
        self.save()
        self.changed.emit()

    # -- persistence ---------------------------------------------------

    def load(self):
        """Read the stored settings, skipping anything unrecognised.

        A preset that was renamed, a field written by a newer version: ignored
        rather than raised. A registry entry is not something the user can
        easily repair, so it must never stop the application opening.
        """
        s = self._settings
        s.beginGroup("theme")
        key = s.value("preset", DEFAULT_PRESET, type=str)
        self._preset_key = key if key in PRESETS else DEFAULT_PRESET
        self._ui_font_size = _ui_font(
            s.value("ui_font_size", DEFAULT_UI_FONT_SIZE, type=int)
        )
        self._plot_font_size = _clamp(
            s.value("plot_font_size", DEFAULT_PLOT_FONT_SIZE, type=int),
            PLOT_FONT_RANGE,
        )

        self._overrides.clear()
        fields = set(Theme.__dataclass_fields__)
        s.beginGroup("overrides")
        for name in s.childKeys():
            if name not in fields or name in UNOVERRIDABLE:
                continue
            if name in _BOOL_FIELDS:
                self._overrides[name] = s.value(name, type=bool)
            else:
                self._overrides[name] = s.value(name, type=str)
        s.endGroup()
        s.endGroup()

    def save(self):
        s = self._settings
        s.beginGroup("theme")
        s.setValue("preset", self._preset_key)
        s.setValue("ui_font_size", self._ui_font_size)
        s.setValue("plot_font_size", self._plot_font_size)
        # Cleared rather than merged: an override just removed has to leave
        # the stored settings too, or it comes back on the next start.
        s.remove("overrides")
        s.beginGroup("overrides")
        for name, value in self._overrides.items():
            s.setValue(name, value)
        s.endGroup()
        s.endGroup()
        s.sync()


_MANAGER: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    """The process-wide theme.

    Built on first use rather than at import, so importing this module touches
    no Qt state. A module global, so a second run of main.py in the same
    interpreter keeps the manager -- and every setting -- it already had.
    """
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ThemeManager()
    return _MANAGER


def current_theme() -> Theme:
    """Shorthand for ``theme_manager().theme``."""
    return theme_manager().theme
