import numpy as np
import pytest

from dapkel_rtp.functions.unpack import unpack, unpack_kelpie_binary_data


def expected_from_fields(fields):
    """What 'unpack' must return for known 14-bit fields, as (32, 32, n)."""
    f = fields.astype(np.int64)
    counts = f >> 5
    coarse = f >> 4
    fine = f & 0xF
    coarse = coarse - (fine < 4)
    ts = (coarse - 1) * 8 + (8 - fine)
    return ts.transpose(1, 2, 0), counts.transpose(1, 2, 0)


def test_decodes_known_fields(make_bin, random_fields):
    fields = random_fields(3)
    path = make_bin(fields)
    ts_exp, counts_exp = expected_from_fields(fields)

    ts, counts = unpack(path, 3)

    assert counts.shape == (32, 32, 3)
    np.testing.assert_array_equal(counts, counts_exp)
    np.testing.assert_array_equal(ts, ts_exp)


def test_single_pixel_lands_where_written(make_bin):
    # One lit pixel per frame, at positions that exercise every channel edge.
    for row, col in [(0, 0), (0, 3), (0, 4), (31, 31), (17, 22)]:
        fields = np.zeros((1, 32, 32), dtype=np.uint32)
        fields[0, row, col] = 100 << 5
        _, counts = unpack(make_bin(fields), 1)
        assert counts[row, col, 0] == 100
        assert counts.sum() == 100


def test_matches_reference_decoder_on_raw_bytes(make_bin, rng):
    # Random bytes, including the unused top 4 bits of every word: the fast
    # decoder is documented as bit-for-bit identical to the reference one.
    raw = rng.integers(0, 256, size=5 * 2048, dtype=np.uint8).tobytes()
    path = make_bin(raw=raw)

    ts_fast, counts_fast = unpack(path, 5)
    ts_ref, counts_ref = unpack_kelpie_binary_data(path, 5)

    np.testing.assert_array_equal(counts_fast, counts_ref)
    np.testing.assert_array_equal(ts_fast, ts_ref)


def test_start_frame_reads_a_chunk(make_bin, random_fields):
    path = make_bin(random_fields(6))
    ts_all, counts_all = unpack(path, 6)

    ts_mid, counts_mid = unpack(path, 2, start_frame=3)

    np.testing.assert_array_equal(counts_mid, counts_all[:, :, 3:5])
    np.testing.assert_array_equal(ts_mid, ts_all[:, :, 3:5])


def test_counts_only_skips_time_series(make_bin, random_fields):
    path = make_bin(random_fields(2))
    _, counts_all = unpack(path, 2)

    ts, counts = unpack(path, 2, compute_time_series=False)

    assert ts is None
    np.testing.assert_array_equal(counts, counts_all)


def test_short_file_raises(make_bin, random_fields):
    path = make_bin(random_fields(2))
    with pytest.raises(ValueError, match="fewer than"):
        unpack(path, 3)
    with pytest.raises(ValueError, match="fewer than"):
        unpack(path, 1, start_frame=2)
