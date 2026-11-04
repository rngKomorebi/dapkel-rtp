"""A dark Windows title bar on every window, whatever the theme.

The title bar is drawn by Windows, not Qt, so no stylesheet reaches it: left
alone it follows the system's light/dark setting and sits as a white strip
over a dark window. Windows 10 (build 18985 on) and 11 take a per-window
"immersive dark mode" flag through DwmSetWindowAttribute; this module sets it
on each titled window as it is shown.

"""

import sys

from PyQt5 import QtCore

# DWMWA_USE_IMMERSIVE_DARK_MODE. Builds before 20H1 used 19 for the same
# thing, undocumented; it is tried when 20 is refused.
_DWMWA_DARK = 20
_DWMWA_DARK_LEGACY = 19

# Found by name rather than by class, so a re-run in the interactive window
# -- which may bring a fresh copy of this module -- still sees the filter the
# previous run installed and does not add a second one.
_FILTER_NAME = "darkTitleBars"


def dark_title_bar(widget):
    """Ask Windows to draw *widget*'s title bar dark. A no-op elsewhere."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    try:
        dwm = ctypes.windll.dwmapi
    except (AttributeError, OSError):
        return
    # WinIdChange also fires while a handle is being torn down or replaced
    # (setWindowFlags does that). There is nothing to darken then, and winId()
    # either comes back as None or, with no native window, would create one.
    if not widget.testAttribute(QtCore.Qt.WA_WState_Created):
        return
    wid = widget.winId()
    if wid is None or not int(wid):
        return
    hwnd = wintypes.HWND(int(wid))
    on = ctypes.c_int(1)
    for attribute in (_DWMWA_DARK, _DWMWA_DARK_LEGACY):
        result = dwm.DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(on), ctypes.sizeof(on)
        )
        if result == 0:  # S_OK
            return
    # Neither accepted: a Windows too old for dark title bars. The light
    # one is cosmetic, not worth a message.


class _DarkTitleBars(QtCore.QObject):
    """Application-wide filter: darkens each titled window as it appears.

    Set before the window is first painted, so it comes up dark rather than
    flashing light and repainting.
    """

    _TITLED = (QtCore.Qt.Window, QtCore.Qt.Dialog)

    def eventFilter(self, obj, event):
        if (
            event.type() in (QtCore.QEvent.Show, QtCore.QEvent.WinIdChange)
            and obj.isWidgetType()
            and obj.isWindow()
            # Menus, tooltips and combo pop-ups are windows too, but have no
            # title bar to darken.
            and obj.windowType() in self._TITLED
        ):
            dark_title_bar(obj)
        return False


def install_dark_title_bars(app):
    """Darken the title bar of every window *app* opens from now on."""
    if sys.platform != "win32":
        return
    if app.findChild(QtCore.QObject, _FILTER_NAME) is not None:
        return
    title_filter = _DarkTitleBars(app)
    title_filter.setObjectName(_FILTER_NAME)
    app.installEventFilter(title_filter)
