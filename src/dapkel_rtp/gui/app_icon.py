"""The application icon, in every size Qt might ask for.

Qt scales whatever single image it is handed, so a title bar showing a
downscaled 256 px icon gets a blur where the sensor grid should be.
Handing it the whole rendered set instead lets it pick the size it
actually needs. See 'tools/make_icons.py' for where those come from.

"""

import sys
from importlib.resources import files

from PyQt5 import QtCore, QtGui

# Rendered by 'tools/make_icons.py'; keep in step with its 'PNG_SIZES'.
ICON_SIZES = (16, 32, 48, 64, 128, 256)

# Windows decides which icon a taskbar button shows, and which buttons
# group together, from the process's "application user model ID". A
# Python process inherits the interpreter's, so without a claim of our
# own the window shows this icon while the taskbar shows Python's, and
# the button groups with every other PyQt application running.
APP_USER_MODEL_ID = "cvut.fjfi.dapkel-rtp"


def icon_file(size):
    """Path to one rendered size, inside the installed package."""
    return files("dapkel_rtp.resources").joinpath(
        "dapkel-rtp-{}.png".format(size)
    )


def app_icon():
    """The icon, carrying every rendered size."""
    icon = QtGui.QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(icon_file(size)), QtCore.QSize(size, size))
    return icon


def claim_taskbar_identity(app_id=APP_USER_MODEL_ID):
    """Announce this process to Windows as an application of its own.

    Must run before the first window is created. A no-op everywhere
    else — the other desktops match a window to its launcher by its
    class name, which Qt sets already.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            app_id
        )
    except (AttributeError, OSError):
        # Nothing here is worth failing to start over: the windows
        # still carry the icon, only the taskbar button falls back to
        # the interpreter's.
        pass
