"""Hitmap reduction for the live view: count what is in the raw data.

A *hitmap* is the per-pixel occupancy of the sensor — how often each pixel
registered a photon over the acquisition. Everything here is counted out of
the decoded '.bin', never modelled: the map is the raw per-pixel fields
reduced over the frames of the acquisition, and the only division applied is
by a time the hardware either was told to use or measured itself.

Which quantity measures occupancy depends on the Kelpie program that wrote
the data, so there are two modes, exactly as in
``dapkel.functions.hitmap_analysis``:

    * ``MODE_COUNT`` (``ORC`` / ``S*C`` — the ``*C`` programs): the data holds
      per-pixel photon counts. The hitmap sums those counts over every frame,
      and the rate is counts per second.

    * ``MODE_TIMESTAMP`` (``ORT`` / ``S*T`` / ``C*T`` — everything else): no
      photon count is recorded. Each macropixel reports the timestamp of the
      *first* photon it saw in the frame, and — this is the trap — 'unpack's
      ``photon_counts`` output is then **not a count at all**: those bits are
      the low bits of the coarse timestamp. Summing them weights a single
      firing by a uniform random 1..~90 instead of by 1, so the map stops
      being what the camera saw and its peak wanders between refreshes. The
      hitmap must instead count, per pixel, the frames carrying a valid
      timestamp (``time_series > 0``) — an occupancy whose ceiling is one
      firing per live window, so the rate is in Hz and saturates there.

Every frame is counted
----------------------
There is no sampling and no cap: 'accumulate_hitmap' reduces over every frame
the acquisition wrote, decoding the file in chunks so that a million-frame
acquisition costs bounded memory rather than none at all.

The only frames left out are the ones that hold no data, and they are
identified structurally, not by threshold. The '.bin' holds more frame slots
than the run asked for — the readout is quantised to 16 MiB blocks (see
REPLAY_BLOCK_FRAMES) — so it contains both slots the run never wrote (all zero)
and frames the chip filled with its idle pattern before data started flowing
(every 32-bit word identical, e.g. ``0x00038007``; observed at 152 of 800
frames on one acquisition). A real frame, dark ones included, never looks like
that — its per-pixel fields vary — so nothing measured is discarded. Counting
dead frames in the normalisation would divide the rate by however many of them
a pass happened to begin with, dimming and brightening the whole map between
refreshes.

Photon rate
-----------
The raw map is counts (or occupancy); a *rate* is that divided by the *live*
time — the seconds the pixel could actually see a photon — and both modes
divide by the same thing, as in ``dapkel.functions.hitmap_analysis``:

    ``rate = hitmap / (frames * live_per_frame)``

``live_per_frame`` is what ``dapkel`` calls ``acq_window``, resolved by mode as
'dapkel.core.timing.resolve_live_time' does:

    * ``short_exposure`` (dapkel's ``short_window``): the **open shutter time**.
      Only the shutter window inside each fixed 9 µs frame is photon-sensitive;
      the rest is readout, and normalising by it would dilute the rate by the
      dead time — a 200 ns shutter reads 45x low.

    * ``long_exposure`` (dapkel's ``full_window``): the whole
      ``shutter + 9 µs`` frame, which is live throughout.

``MODE_COUNT`` reads as cps and ``MODE_TIMESTAMP`` as Hz — the latter cannot
exceed ``1 / live_per_frame``, since at most one firing per frame is recorded,
e.g. 5 MHz at a 200 ns shutter.

An earlier version divided by ``frame_acq_time`` (a flat 9 µs under
``short_exposure``) on the belief that this matched ``dapkel``. It does not:
``dapkel`` divides by ``nframes * n_files * acq_window``, so the live view read
``shutter / 9 µs`` of the number the same data gives offline.

One difference from ``dapkel`` remains, and it is deliberate: ``frames`` here
is the number of frames that *carried data*, not the number requested. See
"Every frame is counted" above — a pass that begins with idle frames would
otherwise dim the whole map. ``dapkel`` divides by the requested ``nframes``,
so on a pass with idle frames its rate is the lower of the two by that
fraction.

Nothing here reads ``frame_rate_cnt.txt``. That counter was the timestamp
mode's normalisation and it is not a frame period; see 'functions.timing' for
why, in numbers.

This file can also be imported as a module and contains the following
functions:

    * mode_for_program - pick the reduction from a program file name.

    * frames_in_file - frame slots in a '.bin', from its size.

    * independent_frames - leading frames of a '.bin' that are not a replay of
    earlier ones (see REPLAY_BLOCK_FRAMES).

    * tail_is_replay - whether everything past a known frame count replays
    earlier frames.

    * valid_frame_mask - per-frame flags marking the frames that carry data.

    * accumulate_hitmap - decode a '.bin' in chunks and reduce every frame it
    holds to a (32, 32) hitmap, using either mode.

    * live_time_per_frame - live (photon-sensitive) seconds per frame for the
    rate, and its unit.

    * photon_rate - turn an accumulated hitmap into a rate map.

    * color_limits - the map's full (vmin, vmax), so every pixel including
    the hottest is shown as measured.
"""

from __future__ import annotations

import os

import numpy as np

from dapkel_rtp.functions.timing import (
    FIRMWARE_SHORT_EXPOSURE,
    FRAME_READOUT_S,
    resolve_frame_acq_time,
)
from dapkel_rtp.functions.unpack import unpack

# Bytes per frame in a Kelpie v2 '.bin' file: 4 * 64 * 8 (see unpack()).
BYTES_PER_FRAME = 4 * 64 * 8

# 32-bit words per frame — the granularity the idle pattern repeats at.
WORDS_PER_FRAME = BYTES_PER_FRAME // 4

# The two reductions, named as in dapkel.functions.hitmap_analysis.
MODE_COUNT = "count"
MODE_TIMESTAMP = "timestamp"

# Frames decoded per chunk. Every frame of the acquisition is counted; this
# only bounds how many are held in memory at once (a chunk costs roughly
# 16 MB of decoded output), so an acquisition of any length is affordable.
CHUNK_FRAMES = 2000

# The exe's DDR3 readout is quantised to 16 MiB blocks, so a '.bin' holds
# 8192 * ceil(nframes / 8192) frame slots -- always at least as many as the
# acquisition asked for, usually more. What sits in those extra slots is NOT
# extra data: measured over every dataset on the group's drive (2026-06-29
# through 2026-08-03, count and timestamp programs, internal and external
# trigger), slots at or past 'nframes' are a *byte-exact replay* of the slots
# 8192 earlier. A 10 000-frame run yields 16 384 slots whose last 6 384 are
# slots 1808..8191 repeated verbatim; 'SPDC_ORT1.bin' holds 10 000 distinct
# frames and 6 384 copies. Reading past 'nframes' therefore accumulates the
# same frames twice -- it does not recover anything the run left behind.
#
# Calibrated on files of one and two blocks (8192 and 16 384 slots). A run
# needing three or more blocks has never been taken, so whether the replay
# offset stays at 8192 there is untested; 'independent_frames' measures the
# boundary rather than assuming it, so it degrades to "no replay found"
# instead of guessing.
REPLAY_BLOCK_FRAMES = 16 * 1024 * 1024 // BYTES_PER_FRAME  # 8192


def mode_for_program(program: str) -> str:
    """Return the reduction mode a Kelpie program file calls for.

    The program tag names the readout: the ``*C`` programs (``ORC``,
    ``S0C``..``S3C``) record photon counts, everything else (``ORT``,
    ``S*T``, ``C*T``, the OR/coincidence programs) records first-photon
    timestamps, where ``photon_counts`` holds coarse-timestamp bits rather
    than counts and must not be summed (see the module docstring).

    Parameters
    ----------
    program : str
        Program file name or path, e.g. ``'program_ORC.txt'``.

    Returns
    -------
    str
        'MODE_COUNT' for a ``*C`` program, 'MODE_TIMESTAMP' otherwise.
    """
    tag = os.path.basename(program or "")
    tag = tag.removesuffix(".txt").removeprefix("program_")
    return MODE_COUNT if tag.upper().endswith("C") else MODE_TIMESTAMP


def frames_in_file(filepath: str) -> int:
    """Return the number of whole frame slots a '.bin' file has room for.

    NOTE: this is the size of the DDR3 dump, not the number of frames the
    acquisition recorded — the readout is quantised to 16 MiB blocks, and the
    slots past the requested frame count are a replay of earlier ones (see
    REPLAY_BLOCK_FRAMES). Never infer a frame count from this: use the
    'nframes' the run was asked for, 'independent_frames' to measure where the
    replay starts, or 'valid_frame_mask' for the frames carrying data.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file written by Kelpie_v2.exe.

    Returns
    -------
    int
        Number of frame slots, ``filesize // (4 * 64 * 8)``.
    """
    return os.path.getsize(filepath) // BYTES_PER_FRAME


def _read_frames(filepath: str, start: int, count: int) -> np.ndarray:
    """Read ``count`` frames from ``start`` as a (count, BYTES_PER_FRAME) view."""
    raw = np.fromfile(
        filepath,
        dtype=np.uint8,
        count=count * BYTES_PER_FRAME,
        offset=start * BYTES_PER_FRAME,
    )
    return raw.reshape(-1, BYTES_PER_FRAME)


def independent_frames(
    filepath: str,
    block_frames: int = REPLAY_BLOCK_FRAMES,
    chunk_frames: int = CHUNK_FRAMES,
) -> int:
    """Return the number of leading frames that are not a replay of earlier ones.

    Measures where the readout's block-quantisation replay starts (see
    REPLAY_BLOCK_FRAMES) rather than assuming it: a frame is a replay when it
    is byte-identical to the frame ``block_frames`` before it, and the answer
    is one past the *last* frame that is not. Scanning to the last mismatch
    rather than stopping at the first match matters for dark count-mode data,
    where unrelated frames are often identical by chance and an early match
    would cut the file short.

    Costs one pass over the file with flat memory, no decoding. Returns the
    slot count unchanged when the file is one block or shorter, since a replay
    cannot arise there — such a file's untouched tail is dead rather than
    duplicated, which 'valid_frame_mask' handles.

    This is a lower bound, not an exact frame count, and it can fall a few
    frames short: in dark count-mode data whole frames repeat by chance, so if
    the run's last frames happen to equal their counterparts one block back
    they are indistinguishable from replay. Measured at 9 996 on a 10 000-frame
    ``DCR_19V_S0C1.bin`` against an exact 10 000 on the timestamp files. It
    never over-reads, which is the direction that matters — use 'tail_is_replay'
    when the requested 'nframes' is known and an exact answer is wanted.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file.
    block_frames : int, optional
        Replay offset in frames. The default is 'REPLAY_BLOCK_FRAMES'.
    chunk_frames : int, optional
        Frames compared at a time; affects memory only. The default is
        'CHUNK_FRAMES'.

    Returns
    -------
    int
        Frames before the replay begins — the frame count the acquisition
        actually delivered, when the run's own 'nframes' is not recorded.
    """
    slots = frames_in_file(filepath)
    block = int(block_frames)
    if slots <= block or block < 1:
        return slots

    # Nothing past the first block has been shown fresh yet, so the floor is
    # the block itself: a wholly-replayed tail means the run wrote 'block'
    # frames and the readout repeated them.
    last_fresh = block - 1
    step = max(1, int(chunk_frames))
    for start in range(block, slots, step):
        stop = min(start + step, slots)
        here = _read_frames(filepath, start, stop - start)
        before = _read_frames(filepath, start - block, stop - start)
        fresh = np.flatnonzero(~(here == before).all(axis=1))
        if fresh.size:
            last_fresh = start + int(fresh[-1])
    return last_fresh + 1


def tail_is_replay(
    filepath: str,
    nframes: int,
    block_frames: int = REPLAY_BLOCK_FRAMES,
    chunk_frames: int = CHUNK_FRAMES,
) -> bool | None:
    """Check that everything past frame ``nframes`` replays earlier frames.

    The exact form of the check 'independent_frames' can only approximate,
    for when the frame count the run was asked for is known: are slots
    ``nframes..`` byte-identical to the slots ``block_frames`` before them?
    True confirms the file holds ``nframes`` frames of data and nothing more;
    False means the tail is something else and should be looked at before it
    is trusted or discarded.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file.
    nframes : int
        Frames the acquisition was asked for.
    block_frames : int, optional
        Replay offset in frames. The default is 'REPLAY_BLOCK_FRAMES'.
    chunk_frames : int, optional
        Frames compared at a time; affects memory only. The default is
        'CHUNK_FRAMES'.

    Returns
    -------
    bool | None
        Whether the tail is a replay, or None when there is no tail to check
        (the file holds no more than ``nframes`` frames) or it starts before
        one full block, where the offset would read off the front of the file.
    """
    slots = frames_in_file(filepath)
    block = int(block_frames)
    n = int(nframes)
    if slots <= n or n < block or block < 1:
        return None

    step = max(1, int(chunk_frames))
    for start in range(n, slots, step):
        stop = min(start + step, slots)
        here = _read_frames(filepath, start, stop - start)
        before = _read_frames(filepath, start - block, stop - start)
        if not np.array_equal(here, before):
            return False
    return True


def valid_frame_mask(
    filepath: str, nframes: int, start_frame: int = 0
) -> np.ndarray:
    """Flag the frames of a '.bin' that carry data.

    A frame is *dead* when all of its 512 words are identical: that covers
    both the all-zero slots the run never wrote and the constant
    idle pattern the chip emits before data starts flowing. Real frames,
    dark ones included, always vary word to word, so nothing measured is
    thrown away.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file.
    nframes : int
        Number of frames to examine.
    start_frame : int, optional
        First frame to examine. The default is 0.

    Returns
    -------
    np.ndarray
        Boolean array of length ``nframes``, True where the frame has data.

    Raises
    ------
    ValueError
        Raised when the file is shorter than the requested range.
    """
    n_bytes = nframes * BYTES_PER_FRAME
    raw = np.fromfile(
        filepath,
        dtype=np.uint8,
        count=n_bytes,
        offset=start_frame * BYTES_PER_FRAME,
    )
    if raw.size < n_bytes:
        raise ValueError(
            f"{os.path.basename(filepath)} holds {raw.size} bytes from frame "
            f"{start_frame}, fewer than the {n_bytes} needed for "
            f"{nframes} frame(s)."
        )
    # (frame, word, byte-in-word): compare every word of a frame with its
    # first one. Byte-level compare, so no word assembly is needed here.
    words = raw.reshape(nframes, WORDS_PER_FRAME, 4)
    dead = (words == words[:, :1, :]).all(axis=(1, 2))
    return ~dead


def accumulate_hitmap(
    filepath: str,
    nframes: int,
    mode: str = MODE_COUNT,
    chunk_frames: int = CHUNK_FRAMES,
) -> tuple[np.ndarray, int, int]:
    """Reduce every frame of a '.bin' to a (32, 32) hitmap.

    The live-view counterpart of 'hitmap_analysis._accumulate_hitmap': sums
    photon counts (``MODE_COUNT``) or counts frames with a valid first-photon
    timestamp (``MODE_TIMESTAMP``) over all frames the acquisition wrote,
    skipping only the dead frames found by 'valid_frame_mask'. The file is
    walked in chunks of ``chunk_frames`` so memory stays flat however long the
    acquisition was.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file to decode.
    nframes : int
        Number of frames the acquisition was asked for. Never read past this,
        so a dump still holding a previous pass's data cannot leak in.
    mode : str, optional
        'MODE_COUNT' or 'MODE_TIMESTAMP'. The default is 'MODE_COUNT'.
    chunk_frames : int, optional
        Frames decoded at a time. Affects memory only, never the result. The
        default is 'CHUNK_FRAMES'.

    Returns
    -------
    tuple[np.ndarray, int, int]
        The (32, 32) hitmap, the number of frames that carried data and went
        into it, and the number of frames read.

    Raises
    ------
    ValueError
        Raised when ``mode`` is unknown or the file holds no whole frame.
    """
    if mode not in (MODE_COUNT, MODE_TIMESTAMP):
        raise ValueError(
            f"mode must be {MODE_COUNT!r} or {MODE_TIMESTAMP!r}, got {mode!r}"
        )

    read = min(int(nframes), frames_in_file(filepath))
    if read < 1:
        raise ValueError(
            f"{os.path.basename(filepath)} holds no whole "
            f"{BYTES_PER_FRAME}-byte frame."
        )

    need_ts = mode == MODE_TIMESTAMP
    hitmap = np.zeros((32, 32), dtype=np.float64)
    frames = 0
    for start in range(0, read, max(1, int(chunk_frames))):
        n = min(int(chunk_frames), read - start)
        valid = valid_frame_mask(filepath, n, start_frame=start)
        if not valid.any():
            continue
        frames += int(valid.sum())
        time_series, photon_counts = unpack(
            filepath, n, compute_time_series=need_ts, start_frame=start
        )
        if need_ts:
            # Occupancy: frames with a valid first-photon timestamp. Do NOT
            # use photon_counts here -- in a timestamp program those bits are
            # the low bits of the coarse timestamp, not a count.
            hitmap += (time_series[:, :, valid] > 0).sum(axis=2)
        else:
            hitmap += photon_counts[:, :, valid].sum(axis=2)
    return hitmap, frames, read


def live_time_per_frame(
    mode: str, firmware_version: str, open_shutter_time_s: float
) -> tuple[float | None, str, str]:
    """Return (live seconds per frame, rate unit, source) for a mode.

    The *live* time is the part of a frame a pixel can see a photon in, which
    is what ``dapkel`` divides by (``acq_window``, see
    'dapkel.core.timing.resolve_live_time'): the open shutter under
    ``short_exposure``, where the rest of the fixed 9 µs frame is readout, and
    the whole ``shutter + 9 µs`` frame under ``long_exposure``.

    Both modes divide by the same thing, so the two are comparable with each
    other and with ``dapkel``. Only the unit differs: ``MODE_COUNT`` sums
    photons so its rate reads as cps, ``MODE_TIMESTAMP`` records at most one
    firing per frame so its rate is a firing rate in Hz, saturating at
    ``1 / live_per_frame``.

    Parameters
    ----------
    mode : str
        'MODE_COUNT' or 'MODE_TIMESTAMP'.
    firmware_version : str
        'short_exposure' or 'long_exposure'.
    open_shutter_time_s : float
        Shutter-open seconds within one frame — the exposure register times the
        clock tick.

    Returns
    -------
    tuple[float | None, str, str]
        Live seconds per frame, the rate unit, and a short human-readable
        source. The seconds are None when there is nothing trustworthy to
        divide by — an unknown firmware version, or a zero shutter under
        ``short_exposure`` — and the caller then shows the counted map instead
        of a rate.
    """
    unit = "cps" if mode == MODE_COUNT else "Hz"
    shutter = float(open_shutter_time_s)
    if firmware_version == FIRMWARE_SHORT_EXPOSURE:
        if shutter <= 0:
            # Register 0 still returns counts (see 'functions.timing'), so the
            # true window is not zero -- but it is unknown, and inventing a
            # default would put a wrong number on the screen.
            return (
                None,
                unit,
                "short_exposure: shutter is 0, live time unknown",
            )
        return (
            shutter,
            unit,
            f"short_exposure: {shutter * 1e9:.0f} ns shutter open in a fixed "
            f"{FRAME_READOUT_S * 1e6:.0f} µs frame",
        )
    try:
        frame_s, source = resolve_frame_acq_time(firmware_version, shutter)
    except ValueError as exc:
        return None, "", str(exc)
    # long_exposure: the whole frame is live, so its length is the live time.
    return frame_s, unit, source


def photon_rate(
    hitmap: np.ndarray,
    frames: np.ndarray | int,
    live_per_frame: float | None,
) -> np.ndarray | None:
    """Convert an accumulated hitmap into a rate map.

    Parameters
    ----------
    hitmap : np.ndarray
        Accumulated counts or occupancy, from 'accumulate_hitmap'.
    frames : np.ndarray | int
        Number of frames that went into ``hitmap``, either one number or a
        per-pixel array — the 64x64 mode acquires its four quadrants
        separately, so each has its own frame count and is normalised by it
        rather than by a common rescaling.
    live_per_frame : float | None
        Live seconds per frame, from 'live_time_per_frame'.

    Returns
    -------
    np.ndarray | None
        The rate map, or None when the live time is unknown or no frame
        carried data, in which case the caller should show the raw map.
    """
    if not live_per_frame:
        return None
    live_time = np.asarray(frames, dtype=np.float64) * live_per_frame
    if not np.any(live_time > 0):
        return None
    # Pixels whose quadrant delivered nothing stay at 0 instead of dividing
    # by zero; they are reported separately, not silently blended in.
    return np.divide(
        hitmap, live_time, out=np.zeros_like(hitmap), where=live_time > 0
    )


def color_limits(data: np.ndarray) -> tuple[float, float]:
    """Return the map's full ``(vmin, vmax)``.

    The colour scale spans the measured range — every pixel is shown as it
    was counted, hot pixels included. (An earlier version clipped the top
    percentile the way hitmap_analysis does; that hides exactly what a live
    view is watched for.)

    Parameters
    ----------
    data : np.ndarray
        Map being displayed (counts, occupancy or rate).

    Returns
    -------
    tuple[float, float]
        ``(min, max)``, widened only if the map is completely flat (e.g. all
        zero), where a zero-width scale would be undrawable.
    """
    vmin = float(np.min(data))
    vmax = float(np.max(data))
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        finite = data[np.isfinite(data)]
        vmin = float(finite.min()) if finite.size else 0.0
        vmax = float(finite.max()) if finite.size else 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    return vmin, vmax
