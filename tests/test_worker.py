"""The workers' handling of a helper exe that cannot run, without running one.

'subprocess.run' is replaced, so nothing is executed: the tests check what
the worker does with the result - and that it never starts the exe at all
when an argument cannot reach it intact.
"""

import functools
import subprocess

import pytest

pytest.importorskip("PyQt5.QtCore")

from dapkel_rtp.functions import system_check  # noqa: E402
from dapkel_rtp.gui.gui import worker  # noqa: E402

DLL_NOT_FOUND = 0xC0000135


@pytest.fixture
def exe_dir(tmp_path):
    # The workers only check that the exe exists; it is never started.
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "Kelpie_v2.exe").write_bytes(b"")
    (helpers / "Kelpie_v2_pwr_mgt.exe").write_bytes(b"")
    return str(helpers)


@pytest.fixture
def fake_run(monkeypatch):
    """Replace subprocess.run in the worker; record every command it gets."""
    calls = []

    def install(returncode):
        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode, "", "")

        monkeypatch.setattr(worker.subprocess, "run", run)
        return calls

    return install


@pytest.fixture
def western_code_page(monkeypatch):
    """Check arguments against cp1252 on every OS, not only on Windows."""
    monkeypatch.setattr(
        worker,
        "unpassable_argument",
        functools.partial(system_check.unpassable_argument, encoding="cp1252"),
    )


def acquisition(exe_dir, folder):
    return worker.AcquisitionWorker(
        {
            "exe_dir": exe_dir,
            "folder": folder,
            "filename": "data",
            "program_tag": "ORT",
            "nacq": 3,
            "start_index": 1,
            "chip_config": 0,
            "exposure_time": 200,
            "nframes": 1000,
        }
    )


def live_view(exe_dir, folder):
    return worker.LiveViewWorker(
        {
            "exe_dir": exe_dir,
            "folder": folder,
            "filename": "live",
            "mode_64": False,
            "hitmap_mode": "count",
            "nframes": 100,
            "exposure_time": 200,
            "chip_config": 0,
            "firmware_version": "short_exposure",
        }
    )


def finished_with(w):
    got = []
    w.finished.connect(lambda ok, msg: got.append((ok, msg)))
    w.run()  # synchronously, on this thread
    return got


def test_acquisition_explains_missing_runtime(exe_dir, tmp_path, fake_run):
    calls = fake_run(DLL_NOT_FOUND)

    got = finished_with(acquisition(exe_dir, str(tmp_path / "out")))

    assert len(calls) == 1  # stopped at the first failure
    ok, msg = got[0]
    assert not ok
    assert "could not start" in msg


def test_acquisition_refuses_unpassable_folder(
    exe_dir, tmp_path, fake_run, western_code_page
):
    calls = fake_run(0)

    got = finished_with(acquisition(exe_dir, str(tmp_path / "Сергей")))

    assert calls == []  # the exe was never started
    ok, msg = got[0]
    assert not ok
    assert "ANSI code page" in msg


def test_live_view_stops_instead_of_retrying_forever(exe_dir, tmp_path, fake_run):
    calls = fake_run(DLL_NOT_FOUND)
    w = live_view(exe_dir, str(tmp_path / "live"))
    errors = []
    w.error.connect(errors.append)

    w.run()  # would never return if the failure were retried

    assert len(calls) == 1
    assert "could not start" in errors[-1]


def test_live_view_refuses_unpassable_folder(
    exe_dir, tmp_path, fake_run, western_code_page
):
    calls = fake_run(0)
    w = live_view(exe_dir, str(tmp_path / "Сергей"))
    errors = []
    w.error.connect(errors.append)

    w.run()

    assert calls == []
    assert "ANSI code page" in errors[-1]
