"""The Help menu's windows: the user guide and the About box.

The guide is a window of its own, not modal, so it can sit beside the tab it
describes while you work. Its text lives in 'help_content'; this module only
lays it out, in the current theme's colours, and re-lays it out when the
theme changes.
"""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from dapkel_rtp import __version__

from .help_content import SECTIONS
from .theme import current_theme, theme_manager

REPO_URL = "https://github.com/rngKomorebi/dapkel-rtp"


def _guide_css() -> str:
    """CSS for the guide, in the current theme.

    QTextBrowser renders a subset of CSS and ignores the application
    stylesheet inside the document, so the colours are spelled out here.
    """
    t = current_theme()
    return f"""
body {{ color: {t.text}; }}
h2 {{ color: {t.accent}; margin-top: 18px; }}
h3 {{ color: {t.text}; margin-top: 12px; }}
a {{ color: {t.accent}; }}
code {{ font-family: "JetBrains Mono", Consolas, monospace; color: {t.text_dim}; }}
table {{ border-collapse: collapse; margin: 4px 0 8px 0; }}
th {{ background: {t.surface_mid}; color: {t.text}; text-align: left; }}
td, th {{ border: 1px solid {t.outline}; padding: 4px 8px; vertical-align: top; }}
p.note {{ color: {t.outline_var}; }}
"""


def _guide_html() -> str:
    parts = []
    for anchor, title, body in SECTIONS:
        parts.append(f'<a name="{anchor}"></a><h2>{title}</h2>{body}')
    return "<html><body>" + "<hr/>".join(parts) + "</body></html>"


class HelpWindow(QtWidgets.QWidget):
    """Contents on the left, the guide on the right, a find box on top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DAPKEL-RTP — User guide")
        # A window of its own, so it can be put beside the tab it explains.
        self.setWindowFlags(QtCore.Qt.Window)
        self.resize(980, 720)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        find_row = QtWidgets.QHBoxLayout()
        find_row.addWidget(QtWidgets.QLabel("Find:"))
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("Search the guide… (Enter for next)")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self._find_next)
        find_row.addWidget(self.find_edit, 1)
        self.find_status = QtWidgets.QLabel("")
        self.find_status.setObjectName("mutedLabel")
        find_row.addWidget(self.find_status)
        root.addLayout(find_row)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.contents = QtWidgets.QListWidget()
        self.contents.setObjectName("helpContents")
        for anchor, title, _body in SECTIONS:
            item = QtWidgets.QListWidgetItem(title)
            item.setData(QtCore.Qt.UserRole, anchor)
            self.contents.addItem(item)
        self.contents.currentItemChanged.connect(self._on_section)
        splitter.addWidget(self.contents)

        self.browser = QtWidgets.QTextBrowser()
        self.browser.setObjectName("helpBrowser")
        self.browser.setOpenLinks(True)
        # Only the guide's own '#anchor' links are internal; anything else
        # (the repository) belongs in the real browser.
        self.browser.setOpenExternalLinks(True)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([210, 760])
        root.addWidget(splitter, 1)

        self._render()
        theme_manager().changed.connect(self._render)

    def _render(self):
        """Lay the guide out in the current theme, keeping the reader's place."""
        bar = self.browser.verticalScrollBar()
        position = bar.value()
        self.browser.document().setDefaultStyleSheet(_guide_css())
        self.browser.setHtml(_guide_html())
        bar.setValue(position)

    def show_section(self, anchor: str | None = None):
        """Bring the window up, scrolled to *anchor* when one is given."""
        self.show()
        self.raise_()
        self.activateWindow()
        if anchor:
            for row in range(self.contents.count()):
                if self.contents.item(row).data(QtCore.Qt.UserRole) == anchor:
                    # Setting the row scrolls via _on_section; scroll
                    # explicitly too, for when the row was already current.
                    self.contents.setCurrentRow(row)
                    break
            self.browser.scrollToAnchor(anchor)

    def _on_section(self, item, _previous=None):
        if item is not None:
            self.browser.scrollToAnchor(item.data(QtCore.Qt.UserRole))

    def _find_next(self):
        text = self.find_edit.text().strip()
        if not text:
            self.find_status.setText("")
            return
        if self.browser.find(text):
            self.find_status.setText("")
            return
        # Not found below the cursor: wrap round to the top once.
        self.browser.moveCursor(QtGui.QTextCursor.Start)
        found = self.browser.find(text)
        self.find_status.setText("" if found else "not found")


def show_about(parent=None):
    QtWidgets.QMessageBox.about(
        parent,
        "About DAPKEL-RTP",
        f"<b>DAPKEL-RTP {__version__}</b>"
        "<p>Data acquisition and real-time plotting for the Kelpie v2 SPAD "
        "camera: 64&times;64 SPADs in 2&times;2 macropixels. The detector "
        "was developed at EPFL by Dr. Tommaso Milanese.</p>"
        "<p>Press <b>F1</b> for the user guide. Colours and font sizes are "
        "under <i>View &rarr; Preferences</i>.</p>"
        f'<p><a href="{REPO_URL}">{REPO_URL}</a><br/>MIT license</p>',
    )
