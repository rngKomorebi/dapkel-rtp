"""Main application window with tabbed interface."""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget

from .style import apply_qss
from .tab_acquisition import AcquisitionTab
from .tab_chain_acquisition import ChainAcquisitionTab
from .tab_live_view import LiveViewTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DAPKEL-RTP — Kelpie v2 SPAD Camera")
        self.resize(1200, 760)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        self._acq_tab = AcquisitionTab()
        self._chain_tab = ChainAcquisitionTab()
        self._live_tab = LiveViewTab()
        tabs.addTab(self._acq_tab, "Single Acquisition")
        tabs.addTab(self._chain_tab, "Chain Acquisition")
        tabs.addTab(self._live_tab, "Live View")
        self.setCentralWidget(tabs)

        self._font_timer = QTimer(self)
        self._font_timer.setSingleShot(True)
        self._font_timer.timeout.connect(self._apply_scaled_font)

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
        app = QApplication.instance()
        if app:
            apply_qss(app, fs)

    def closeEvent(self, event):
        for worker in (
            self._acq_tab._pwr_worker,
            self._acq_tab._worker,
            self._chain_tab._pwr_worker,
            self._chain_tab._worker,
            self._live_tab._pwr_worker,
            self._live_tab._worker,
        ):
            if worker is not None and worker.isRunning():
                worker.terminate()
                worker.wait(2000)  # ms — give it up to 2 s then move on
        event.accept()
