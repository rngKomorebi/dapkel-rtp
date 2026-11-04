"""Shared fixtures: synthetic Kelpie v2 '.bin' files with known pixel fields.

No hardware is needed anywhere in the suite. Every test that reads a '.bin'
builds one here, from 14-bit pixel fields it chose, so a decode can be checked
against what was written rather than against another decode.
"""

import os

# Before anything imports Qt: the GUI tests build real widgets, and CI runners
# (and a test run over SSH) have no display to put them on.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from dapkel_rtp.functions.hitmap import BYTES_PER_FRAME


def encode_frames(fields: np.ndarray) -> bytes:
    """Pack (nframes, 32, 32) 14-bit pixel fields into Kelpie v2 '.bin' bytes.

    The inverse of 'unpack'. Pixel (row, col) sits in channel ``col // 4`` as
    pixel ``p = row * 4 + col % 4`` of that channel's 128; word ``p // 2``
    carries it in bits 27..14 when ``p`` is even and bits 13..0 when odd. A
    frame is 64 rows of 32 bytes, row ``w`` holding word ``w`` of each of the
    8 channels as 4 big-endian bytes. Each 14-bit field is
    ``[9-bit count | 1 extra coarse bit | 4-bit fine]``.
    """
    fields = np.asarray(fields, dtype=np.uint32)
    nframes = fields.shape[0]
    # (frame, row, col) -> (frame, channel, pixel-in-channel)
    per_chan = (
        fields.reshape(nframes, 32, 8, 4)  # col = channel * 4 + local
        .transpose(0, 2, 1, 3)  # (frame, channel, row, local)
        .reshape(nframes, 8, 128)
    )
    words = (per_chan[:, :, 0::2] << 14) | per_chan[:, :, 1::2]  # (f, ch, 64)
    # (frame, word, channel) as big-endian bytes -> 64 rows of 8 x 4 bytes
    return words.transpose(0, 2, 1).astype(">u4").tobytes()


def count_fields(counts: np.ndarray) -> np.ndarray:
    """14-bit fields whose decoded photon count is ``counts`` (0..511)."""
    return np.asarray(counts, dtype=np.uint32) << 5


@pytest.fixture
def make_bin(tmp_path):
    """Factory: write fields (or raw bytes) to a '.bin' and return its path."""
    made = []

    def _make(fields=None, *, raw=None, name="data_ORT1.bin"):
        path = tmp_path / name
        data = raw if raw is not None else encode_frames(fields)
        path.write_bytes(data)
        made.append(path)
        return str(path)

    return _make


@pytest.fixture
def rng():
    return np.random.default_rng(20261104)


@pytest.fixture
def random_fields(rng):
    """Factory: (nframes, 32, 32) random 14-bit fields - never a dead frame."""

    def _fields(nframes):
        return rng.integers(0, 1 << 14, size=(nframes, 32, 32), dtype=np.uint32)

    return _fields


@pytest.fixture
def dead_frame():
    """One frame of all-zero bytes - a slot the run never wrote."""
    return bytes(BYTES_PER_FRAME)
