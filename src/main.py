"""Entry point for the Kelpie v2 GUI application.

Run directly:
    python main.py

Run it in the VS Code interactive window (or any IPython kernel) as often as you
like: the session's QApplication is reused rather than replaced, so a second run
neither kills the kernel nor opens a window that never paints. The call returns
when the window is closed.

Build a standalone executable with PyInstaller (uses main.spec, which bundles
the program files/bitfile/helper exes that plain --onefile can't discover):
    pyinstaller --clean main.spec
"""

import os
import sys

# Ensure the src/ directory is on the path so `dapkel_rtp` is importable
# when running from the repo root or from a bundled exe.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Interactive / notebook context — use the current working directory
    _HERE = os.path.abspath(os.getcwd())
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt5.QtWidgets import QApplication

from dapkel_rtp.gui.app_icon import app_icon, claim_taskbar_identity
from dapkel_rtp.gui.gui.main_window import MainWindow
from dapkel_rtp.gui.gui.style import apply_mpl_dark, apply_qss


# The QApplication and the window live here, not in main()'s locals, and the
# reason is the crash you get otherwise. In an interpreter that outlives the call
# -- the VS Code interactive window, a notebook, any IPython kernel -- locals are
# dropped when main() returns, which destroys the QApplication and the window in
# an order Qt does not survive. The second run then dies inside Qt with an access
# violation: no traceback, no Python error, just "the kernel died". Module
# globals keep both alive until something replaces them.
_APP = None
_WINDOW = None


def _qt_loop_already_running() -> bool:
    """True only when something else is already spinning a Qt event loop.

    That is the one case where this module must not call ``exec_()``: doing so
    would block the caller's loop. An IPython/Jupyter kernel -- the VS Code
    interactive window, a notebook -- spins one only when Qt GUI integration has
    been switched on with ``%gui qt``, which is not the default. Without it
    nothing processes Qt events, so a window opened without ``exec_()`` never
    paints: it comes up blank and dead, which is exactly what a second run did
    when this decision was based on whether a QApplication already existed
    (after the first run one always does).
    """
    try:
        from IPython import get_ipython
    except ImportError:
        return False  # not an IPython session at all
    ip = get_ipython()
    if ip is None:
        return False  # IPython importable, but this is a plain interpreter
    # Set by %gui qt to 'qt' / 'qt5' / 'qt6'; empty or None when off.
    return str(getattr(ip, "active_eventloop", "") or "").startswith("qt")


def main():
    """Open the window, and run the Qt event loop unless something else is.

    Safe to call more than once in the same interpreter: the existing
    QApplication is reused (a second one in one process is fatal) and the
    previous window is closed properly rather than garbage-collected. The event
    loop is entered on every call, so the window works on the second run as it
    did on the first; the call returns when the window is closed, as it always
    has. Only a session already running a Qt loop is left to run its own.
    """
    global _APP, _WINDOW

    # Apply matplotlib dark colours BEFORE any Figure is created
    apply_mpl_dark()

    # Before the QApplication, and so before any window exists: this is
    # what tells Windows which taskbar button the process owns, and it is
    # only read once, when that button is first created.
    claim_taskbar_identity()

    existing = QApplication.instance()
    _APP = existing if existing is not None else QApplication(sys.argv)
    _APP.setApplicationName("DAPKEL-RTP")
    # Set on the application, not the window, so every window the app
    # opens inherits it -- the dialogs included.
    _APP.setWindowIcon(app_icon())
    apply_qss(_APP)

    if _WINDOW is not None:
        # Through closeEvent, so a run left over from the previous call stops
        # its worker threads instead of being torn down underneath them.
        _WINDOW.close()

    _WINDOW = MainWindow()
    _WINDOW.show()

    if not _qt_loop_already_running():
        _APP.exec_()

    return _WINDOW


if __name__ == "__main__":
    main()
