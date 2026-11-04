import numpy as np
import pytest

from conftest import encode_frames
from dapkel_rtp.functions.data_quality import (
    MODE_COUNT,
    MODE_TIMESTAMP,
    VERDICT_FAIL,
    VERDICT_NA,
    VERDICT_PASS,
    check_file,
    collect_time_codes,
    detect_tag,
    mode_for_bin,
    scan_bin_files,
)


@pytest.mark.parametrize(
    "name, tag",
    [
        ("data_ORT12.bin", "ORT"),
        ("data_ort3.bin", "ORT"),
        (r"D:\run\SPDC_ORC1.bin", "ORC"),
        ("x_ORS0S1_3.bin", "ORS0S1"),
        ("run_coincs0s2_7.bin", "coincS0S2"),
        ("SORTED.bin", None),  # 'ORT' inside a word is not a tag
        ("random.bin", None),
        ("", None),
    ],
)
def test_detect_tag(name, tag):
    assert detect_tag(name) == tag


def test_mode_for_bin():
    assert mode_for_bin("a_S1C2.bin") == (MODE_COUNT, "S1C")
    assert mode_for_bin("a_C3T2.bin") == (MODE_TIMESTAMP, "C3T")
    assert mode_for_bin("nothing.bin") == (None, None)


def test_scan_bin_files_sorts_naturally(tmp_path):
    for name in ("d_ORT10.bin", "d_ORT2.bin", "d_ORT1.bin", "notes.txt"):
        (tmp_path / name).write_bytes(bytes(2048 * 3))

    entries = scan_bin_files(str(tmp_path))

    assert [e["name"] for e in entries] == ["d_ORT1.bin", "d_ORT2.bin", "d_ORT10.bin"]
    assert entries[0]["frames"] == 3
    assert entries[0]["mode"] == MODE_TIMESTAMP


def test_scan_bin_files_rejects_missing_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        scan_bin_files(str(tmp_path / "nope"))


def stuck_fields(nframes):
    """Even rows on one valid code, odd rows empty - a TDC that is not timing.

    The empty rows keep the frame's words from all being identical, which
    would make it a dead frame rather than a stuck one.
    """
    fields = np.zeros((nframes, 32, 32), dtype=np.uint32)
    fields[:, 0::2, :] = (300 << 4) | 9  # coarse 300, fine 9 -> code 2391
    return fields


def test_healthy_timestamp_file_passes(make_bin, random_fields):
    path = make_bin(random_fields(4), name="run_ORT1.bin")

    summary = check_file(path)

    assert summary["verdict"] == VERDICT_PASS
    assert summary["mode"] == MODE_TIMESTAMP
    assert summary["mode_source"] == "name"
    assert summary["frames_with_data"] == 4


def test_stuck_tdc_fails(make_bin):
    path = make_bin(stuck_fields(4), name="run_ORT1.bin")

    summary = check_file(path)

    assert summary["verdict"] == VERDICT_FAIL
    assert summary["unique"] == 1
    assert summary["top_code"] == 2391


def test_count_file_gets_no_verdict(make_bin, random_fields):
    path = make_bin(random_fields(2), name="run_ORC1.bin")
    assert check_file(path)["verdict"] == VERDICT_NA


def test_unknown_program_gets_no_verdict_unless_stated(make_bin, random_fields):
    path = make_bin(random_fields(2), name="untagged.bin")
    assert check_file(path)["verdict"] == VERDICT_NA

    stated = check_file(path, mode=MODE_TIMESTAMP)
    assert stated["verdict"] == VERDICT_PASS
    assert stated["mode_source"] == "stated"


def test_empty_file_fails(make_bin, dead_frame):
    path = make_bin(raw=dead_frame * 3, name="run_ORT1.bin")
    summary = check_file(path)
    assert summary["verdict"] == VERDICT_FAIL
    assert summary["frames_with_data"] == 0


def test_single_pixel_histogram(make_bin, random_fields):
    fields = random_fields(3)
    path = make_bin(fields)

    pooled = collect_time_codes(path)
    one = collect_time_codes(path, pixel=(4, 9))

    assert one["hist"].sum() == pooled["pixel_valid"][4, 9]
    with pytest.raises(ValueError, match="32x32"):
        collect_time_codes(path, pixel=(32, 0))


def test_abort_stops_between_chunks(make_bin, random_fields):
    path = make_bin(random_fields(4))
    calls = []

    result = collect_time_codes(
        path,
        chunk_frames=1,
        progress=lambda done, total: calls.append((done, total)),
        should_abort=lambda: len(calls) >= 2,
    )

    assert result["aborted"]
    assert result["frames_read"] == 2
    assert calls == [(1, 4), (2, 4)]


def test_encoder_roundtrip_guard():
    # If the encoder in conftest drifted, every test above would be checking
    # the encoder against itself. Pin one byte layout by hand: pixel (0, 0)
    # is the high field of channel 0's word 0, i.e. bytes 0..3 of the file.
    fields = np.zeros((1, 32, 32), dtype=np.uint32)
    fields[0, 0, 0] = 0x3FFF
    raw = encode_frames(fields)
    assert raw[:4] == bytes([0x0F, 0xFF, 0xC0, 0x00])
    assert raw[4:] == bytes(len(raw) - 4)
