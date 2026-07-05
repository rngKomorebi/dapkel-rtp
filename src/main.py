"""Entry point for the Kelpie v2 GUI application.

Run directly:
    python main.py

Build a standalone executable with PyInstaller:
    pyinstaller --clean --onefile --noconsole main.py
"""

import os
import sys

# Ensure the src/ directory is on the path so `dapkel` is importable
# when running from the repo root or from a bundled exe.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Interactive / notebook context — use the current working directory
    _HERE = os.path.abspath(os.getcwd())
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt5.QtWidgets import QApplication

from dapkel.gui.gui.main_window import MainWindow
from dapkel.gui.gui.style import apply_mpl_dark, apply_qss


def main():
    # Apply matplotlib dark colours BEFORE any Figure is created
    apply_mpl_dark()

    app = QApplication(sys.argv)
    app.setApplicationName("DAPKEL-RTP")
    apply_qss(app)

    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    main()
