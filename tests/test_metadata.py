import json
import re

import pytest

from conftest import encode_frames
from dapkel_rtp import __version__
from dapkel_rtp.functions.metadata import (
    FALLBACK_FILENAME,
    METADATA_FILENAME,
    build_run_record,
    file_names_for_run,
    new_run_id,
    probe_readout,
    read_runs,
    run_for_file,
    upsert_run,
)

SETTINGS = {
    "folder": "D:/data/run",
    "filename_prefix": "SPDC",
    "program_tag": "ORT",
    "mode": "timestamp",
    "start_index": 3,
    "nacq_requested": 5,
    "nframes": 1000,
    "open_shutter_clks": 200,  # 1 us
    "firmware_version": "long_exposure",
}


def record(run_id="r1", n_files=2, **kwargs):
    return build_run_record(
        SETTINGS,
        run_id=run_id,
        status="completed",
        started=1_790_000_000.0,
        finished=1_790_000_012.5,
        n_files_written=n_files,
        per_file_elapsed_s=[6.0, 6.5],
        **kwargs,
    )


def test_new_run_id_is_reproducible_and_folder_specific():
    a = new_run_id(1_790_000_000.0, "D:/a", "SPDC")
    assert a == new_run_id(1_790_000_000.0, "D:/a", "SPDC")
    assert a != new_run_id(1_790_000_000.0, "D:/b", "SPDC")
    assert re.fullmatch(r".+-[0-9a-f]{8}", a)


def test_build_run_record_derives_timing_and_files():
    rec = record()

    assert rec["open_shutter_time_s"] == pytest.approx(1e-6)
    assert rec["frame_acq_time_s"] == pytest.approx(10e-6)
    assert rec["total_frames"] == 2000
    assert rec["wallclock_time_s"] == pytest.approx(2000 * 10e-6)
    assert rec["wallclock_time_measured_s"] == 12.5
    assert rec["file_index_range"] == [3, 4]
    assert rec["per_file_elapsed_s"] == {"min": 6.0, "median": 6.25, "max": 6.5}
    assert rec["app_version"] == __version__
    assert file_names_for_run(rec) == ["SPDC_ORT3.bin", "SPDC_ORT4.bin"]


def test_build_run_record_survives_missing_settings():
    rec = build_run_record({}, run_id="r", status="running", started=0.0)
    assert rec["nframes"] == 0
    assert rec["file_index_range"] is None
    assert file_names_for_run(rec) == []


def test_upsert_appends_then_replaces(tmp_path):
    folder = str(tmp_path)
    upsert_run(folder, record("r1"))
    upsert_run(folder, record("r2"))
    upsert_run(folder, {**record("r1"), "status": "aborted"})

    runs = read_runs(folder)
    assert [r["run_id"] for r in runs] == ["r1", "r2"]
    assert runs[0]["status"] == "aborted"
    assert not list(tmp_path.glob("*.tmp"))


def test_upsert_never_overwrites_a_foreign_metadata_json(tmp_path):
    foreign = tmp_path / METADATA_FILENAME
    foreign.write_text('{"operator": "not ours"}', encoding="utf-8")

    written = upsert_run(str(tmp_path), record())

    assert written.endswith(FALLBACK_FILENAME)
    assert json.loads(foreign.read_text(encoding="utf-8")) == {"operator": "not ours"}
    assert [r["run_id"] for r in read_runs(str(tmp_path))] == ["r1"]


def test_run_for_file(tmp_path):
    upsert_run(str(tmp_path), record("r1"))
    assert run_for_file(str(tmp_path / "SPDC_ORT4.bin"))["run_id"] == "r1"
    assert run_for_file(str(tmp_path / "SPDC_ORT5.bin")) is None


def test_probe_readout_short_run(make_bin, random_fields, dead_frame):
    # 3 frames asked for, 2 surplus slots: under one block, so a dead tail.
    path = make_bin(raw=encode_frames(random_fields(3)) + dead_frame * 2)

    probe = probe_readout(path, 3)

    assert probe["frame_slots_in_file"] == 5
    assert probe["duplicate_tail_frames"] == 2
    assert probe["independent_frames"] == 3
    assert probe["verified"] is None
    assert "never wrote" in probe["note"]


def test_probe_readout_no_tail(make_bin, random_fields):
    path = make_bin(random_fields(3))
    probe = probe_readout(path, 3)
    assert probe["duplicate_tail_frames"] == 0
    assert "no slots past nframes" in probe["note"]
