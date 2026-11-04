"""Smoke test: the whole window builds, headless, without touching hardware.

Catches what an import alone does not - a widget built against a PyQt5 or
matplotlib API that a newer release removed, a tab whose __init__ raises. It
does not click anything: every action past building the window starts
Kelpie_v2.exe.
"""

import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_main_window_builds(app):
    from dapkel_rtp.gui.gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()

    tabs = window.findChild(QtWidgets.QTabWidget)
    names = [tabs.tabText(i) for i in range(tabs.count())]
    assert names == [
        "Single Acquisition",
        "Chain Acquisition",
        "Live View",
        "Data Quality",
    ]

    window.close()
    app.processEvents()


# --- the self-test the release workflow runs on the built exe ---


def test_source_tree_carries_everything_the_exe_needs():
    from dapkel_rtp.gui.smoke import bundle_problems

    assert bundle_problems() == []


def test_bundle_problems_names_missing_helpers(monkeypatch, tmp_path):
    from dapkel_rtp.gui import smoke

    monkeypatch.setattr(smoke, "functions_dir", lambda: str(tmp_path))

    problems = smoke.bundle_problems()

    assert len(problems) == len(smoke.HELPER_FILES)
    assert all(p.startswith("missing helper") for p in problems)


def test_smoke_test_reports_a_failed_start(app, tmp_path):
    from dapkel_rtp.gui.smoke import run_smoke_test

    def start():
        raise ImportError("no module named 'something_pyinstaller_missed'")

    report = tmp_path / "smoke.txt"
    assert run_smoke_test(str(report), start) == 1
    assert "something_pyinstaller_missed" in report.read_text(encoding="utf-8")
