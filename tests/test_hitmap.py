import numpy as np
import pytest

from conftest import count_fields, encode_frames
from dapkel_rtp.functions.hitmap import (
    MODE_COUNT,
    MODE_TIMESTAMP,
    accumulate_hitmap,
    color_limits,
    frames_in_file,
    independent_frames,
    live_time_per_frame,
    mode_for_program,
    peak_occupancy,
    photon_rate,
    tail_is_replay,
    valid_frame_mask,
)
from dapkel_rtp.functions.timing import (
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
)
from dapkel_rtp.functions.unpack import unpack


@pytest.mark.parametrize(
    "program, mode",
    [
        ("program_ORC.txt", MODE_COUNT),
        ("program_S2C.txt", MODE_COUNT),
        (r"C:\programs\program_ORT.txt", MODE_TIMESTAMP),
        ("program_C3T.txt", MODE_TIMESTAMP),
        ("program_coincS0S1.txt", MODE_TIMESTAMP),
        ("", MODE_TIMESTAMP),
    ],
)
def test_mode_for_program(program, mode):
    assert mode_for_program(program) == mode


def test_frames_in_file_counts_whole_slots(make_bin, random_fields, dead_frame):
    path = make_bin(raw=encode_frames(random_fields(3)) + dead_frame[:100])
    assert frames_in_file(path) == 3


def test_valid_frame_mask_flags_dead_frames(make_bin, random_fields, dead_frame):
    # The chip's idle pattern: every word of the frame identical, non-zero.
    idle = bytes([0x0A, 0x0B, 0x0C, 0x0D]) * 512
    live = encode_frames(random_fields(2))
    raw = dead_frame + live[:2048] + idle + live[2048:]
    path = make_bin(raw=raw)

    mask = valid_frame_mask(path, 4)

    np.testing.assert_array_equal(mask, [False, True, False, True])


def test_count_hitmap_sums_counts_and_skips_dead(make_bin, rng, dead_frame):
    counts = rng.integers(0, 512, size=(4, 32, 32))
    path = make_bin(raw=encode_frames(count_fields(counts)) + dead_frame)

    hitmap, frames, read = accumulate_hitmap(path, 5, MODE_COUNT)

    np.testing.assert_array_equal(hitmap, counts.sum(axis=0))
    assert frames == 4
    assert read == 5


def test_timestamp_hitmap_counts_valid_frames_not_values(make_bin, random_fields):
    fields = random_fields(6)
    path = make_bin(fields)
    ts, counts = unpack(path, 6)

    hitmap, frames, _ = accumulate_hitmap(path, 6, MODE_TIMESTAMP)

    np.testing.assert_array_equal(hitmap, (ts > 0).sum(axis=2))
    assert hitmap.max() <= frames == 6
    # The trap the module warns about: summing 'photon_counts' is not this.
    assert not np.array_equal(hitmap, counts.sum(axis=2))


@pytest.mark.parametrize("mode", [MODE_COUNT, MODE_TIMESTAMP])
def test_chunk_size_never_changes_the_result(make_bin, random_fields, mode):
    path = make_bin(random_fields(7))
    whole = accumulate_hitmap(path, 7, mode, chunk_frames=7)
    for chunk in (1, 2, 3):
        hitmap, frames, read = accumulate_hitmap(path, 7, mode, chunk_frames=chunk)
        np.testing.assert_array_equal(hitmap, whole[0])
        assert (frames, read) == whole[1:]


def test_never_reads_past_nframes(make_bin, random_fields):
    path = make_bin(random_fields(5))
    first3, frames, read = accumulate_hitmap(path, 3, MODE_TIMESTAMP)
    ts, _ = unpack(path, 3)
    np.testing.assert_array_equal(first3, (ts > 0).sum(axis=2))
    assert frames == read == 3


def test_accumulate_rejects_bad_input(make_bin, random_fields):
    path = make_bin(random_fields(1))
    with pytest.raises(ValueError, match="mode"):
        accumulate_hitmap(path, 1, "photons")
    empty = make_bin(raw=b"\x00" * 100, name="empty.bin")
    with pytest.raises(ValueError, match="no whole"):
        accumulate_hitmap(empty, 1)


# --- the readout's block replay, on a 4-frame "block" to keep files tiny ---


def test_independent_frames_finds_replay_start(make_bin, random_fields):
    fields = random_fields(6)
    # 6 fresh frames, then slots 6..7 replay slots 2..3 (block of 4).
    path = make_bin(np.concatenate([fields, fields[2:4]]))

    assert independent_frames(path, block_frames=4) == 6
    assert tail_is_replay(path, 6, block_frames=4) is True
    assert tail_is_replay(path, 5, block_frames=4) is False


def test_independent_frames_without_replay(make_bin, random_fields):
    path = make_bin(random_fields(8))
    assert independent_frames(path, block_frames=4) == 8
    # A file no longer than one block cannot replay.
    assert independent_frames(path, block_frames=8) == 8


def test_tail_is_replay_none_when_uncheckable(make_bin, random_fields):
    path = make_bin(random_fields(6))
    assert tail_is_replay(path, 6, block_frames=4) is None  # no tail
    assert tail_is_replay(path, 3, block_frames=4) is None  # shorter than a block


# --- turning a hitmap into a rate ---


def test_live_time_per_frame():
    live, unit, _ = live_time_per_frame(MODE_COUNT, FIRMWARE_SHORT_EXPOSURE, 1e-6)
    assert (live, unit) == (1e-6, "cps")

    live, unit, _ = live_time_per_frame(MODE_TIMESTAMP, FIRMWARE_LONG_EXPOSURE, 1e-6)
    assert live == pytest.approx(10e-6)
    assert unit == "Hz"

    # Zero shutter under short_exposure: unknown, not invented.
    assert live_time_per_frame(MODE_COUNT, FIRMWARE_SHORT_EXPOSURE, 0)[0] is None
    assert live_time_per_frame(MODE_COUNT, "unknown", 1e-6)[0] is None


def test_photon_rate():
    hitmap = np.full((32, 32), 10.0)
    np.testing.assert_allclose(photon_rate(hitmap, 100, 1e-6), 1e5)
    assert photon_rate(hitmap, 100, None) is None
    assert photon_rate(hitmap, 0, 1e-6) is None

    # Per-pixel frame counts: a quadrant with no frames stays 0, not inf.
    frames = np.full((32, 32), 100)
    frames[:16, :16] = 0
    rate = photon_rate(hitmap, frames, 1e-6)
    assert np.all(rate[:16, :16] == 0)
    assert np.all(np.isfinite(rate))


def test_peak_occupancy():
    hitmap = np.zeros((32, 32))
    hitmap[5, 7] = 30
    hitmap[20, 1] = 10
    assert peak_occupancy(hitmap, 60) == (0.5, 5, 7)
    assert peak_occupancy(hitmap, 0) is None


def test_color_limits():
    assert color_limits(np.array([[1.0, 4.0], [2.0, 3.0]])) == (1.0, 4.0)
    # Flat map: widened so the scale is drawable.
    assert color_limits(np.zeros((2, 2))) == (0.0, 1.0)
    # Non-finite values are ignored, not propagated.
    assert color_limits(np.array([1.0, np.nan, 5.0, np.inf])) == (1.0, 5.0)
