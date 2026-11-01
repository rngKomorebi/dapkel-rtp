"""Main application window: the tabs, a View menu for the theme, and Help."""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QActionGroup, QApplication, QMainWindow, QTabWidget

from .help import HelpWindow, show_about
from .help_content import TAB_ANCHORS
from .preferences import PreferencesDialog
from .style import DEFAULT_UI_FONT_PX, apply_mpl_theme, apply_qss
from .tab_acquisition import AcquisitionTab
from .tab_chain_acquisition import ChainAcquisitionTab
from .tab_data_quality import DataQualityTab
from .tab_live_view import LiveViewTab
from .theme import PRESETS, preset_names, theme_manager


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DAPKEL-RTP — Kelpie v2 SPAD Camera")
        self.resize(1200, 760)

        # The size the window last picked for itself, for when the font is on
        # auto; a size set in Preferences overrides it inside apply_qss.
        self._auto_fs = DEFAULT_UI_FONT_PX
        self._preferences = None
        self._help = None

        self._manager = theme_manager()
        # Connected before the tabs are built, so on a theme change this runs
        # first: the tabs redraw against rcParams already in the new theme.
        self._manager.changed.connect(self._theme_changed)

        tabs = QTabWidget()
        self._tabs = tabs
        tabs.setDocumentMode(True)
        self._acq_tab = AcquisitionTab()
        self._chain_tab = ChainAcquisitionTab()
        self._live_tab = LiveViewTab()
        self._dq_tab = DataQualityTab()
        tabs.addTab(self._acq_tab, "Single Acquisition")
        tabs.addTab(self._chain_tab, "Chain Acquisition")
        tabs.addTab(self._live_tab, "Live View")
        tabs.addTab(self._dq_tab, "Data Quality")
        self.setCentralWidget(tabs)

        self._build_menu()

        self._font_timer = QTimer(self)
        self._font_timer.setSingleShot(True)
        self._font_timer.timeout.connect(self._apply_scaled_font)

    # ------------------------------------------------------------------
    # Menu and theme
    # ------------------------------------------------------------------

    def _build_menu(self):
        view = self.menuBar().addMenu("&View")

        theme_menu = view.addMenu("&Theme")
        # One group, so exactly one preset is ticked at a time.
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        # Presets are defined dark first, then light; a rule where the base
        # changes saves reading the whole list to find the half that suits
        # the room.
        previous_base = None
        for key, name in preset_names():
            base = PRESETS[key].base
            if previous_base is not None and base != previous_base:
                theme_menu.addSeparator()
            previous_base = base
            action = theme_menu.addAction(name)
            action.setCheckable(True)
            action.setData(key)
            self._theme_group.addAction(action)
            self._theme_actions[key] = action
        self._theme_group.triggered.connect(self._preset_chosen)

        view.addSeparator()
        preferences = view.addAction("&Preferences…")
        preferences.setShortcut("Ctrl+,")
        preferences.triggered.connect(self.open_preferences)

        help_menu = self.menuBar().addMenu("&Help")
        guide = help_menu.addAction("&User guide")
        guide.setShortcut("F1")
        guide.triggered.connect(self.open_help)
        help_menu.addSeparator()
        about = help_menu.addAction("&About DAPKEL-RTP")
        about.triggered.connect(lambda: show_about(self))

        self._sync_theme_menu()

    def _preset_chosen(self, action):
        self._manager.set_preset(action.data())

    def _sync_theme_menu(self):
        action = self._theme_actions.get(self._manager.preset_key)
        if action is not None:
            action.setChecked(True)

    def open_preferences(self):
        # Built on first use: most sessions never open it.
        if self._preferences is None:
            self._preferences = PreferencesDialog(self)
        self._preferences.open_beside()

    def open_help(self):
        """The user guide, at the section for the tab in front."""
        # Built on first use, then kept, so it reopens where it was left.
        if self._help is None:
            self._help = HelpWindow(self)
        index = self._tabs.currentIndex()
        anchor = TAB_ANCHORS[index] if 0 <= index < len(TAB_ANCHORS) else None
        self._help.show_section(anchor)

    def _theme_changed(self):
        app = QApplication.instance()
        if app:
            apply_qss(app, self._auto_fs)
        apply_mpl_theme()
        self._sync_theme_menu()

    # ------------------------------------------------------------------
    # Font scaling
    # ------------------------------------------------------------------

    @staticmethod
    def _font_size_for_height(h: int) -> int:
        if h < 900:  return 15
        if h < 1050: return 16
        if h < 1200: return 17
        return 18

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._font_timer.start(120)

    def _apply_scaled_font(self):
        fs = self._font_size_for_height(self.height())
        # Nothing to restyle when the window settles on the size it already
        # had, or when Preferences pins the size and the auto one is unused.
        if fs == self._auto_fs:
            return
        self._auto_fs = fs
        app = QApplication.instance()
        if app and not self._manager.ui_font_size:
            apply_qss(app, fs)

    def closeEvent(self, event):
        # getattr, because not every tab owns both kinds of worker (the Data
        # Quality tab touches no hardware, so it has no power-management one).
        tabs = (self._acq_tab, self._chain_tab, self._live_tab, self._dq_tab)
        for tab in tabs:
            for attr in ("_pwr_worker", "_worker"):
                worker = getattr(tab, attr, None)
                if worker is not None and worker.isRunning():
                    worker.terminate()
                    worker.wait(2000)  # ms — give it up to 2 s then move on
        event.accept()
