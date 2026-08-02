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
      firing per frame period, so the rate is in Hz.

Every frame is counted
----------------------
There is no sampling and no cap: 'accumulate_hitmap' reduces over every frame
the acquisition wrote, decoding the file in chunks so that a million-frame
acquisition costs bounded memory rather than none at all.

The only frames left out are the ones that hold no data, and they are
identified structurally, not by threshold. The '.bin' is a fixed-size DDR3
dump, so it contains both slots the acquisition never wrote (all bytes zero)
and frames the chip filled with its idle pattern before data started flowing
(every 32-bit word identical, e.g. ``0x00038007``; observed at 152 of 800
frames on one acquisition). A real frame, dark ones included, never looks like
that — its per-pixel fields vary — so nothing measured is discarded. Counting
dead frames in the normalisation would divide the rate by however many of them
a pass happened to begin with, dimming and brightening the whole map between
refreshes.

Photon rate
-----------
The raw map is counts (or occupancy); a *rate* is that divided by the live
time, and which time depends on the mode — mirroring hitmap_analysis:

    * ``MODE_COUNT`` — photons accumulate while the pixel is exposed, and
      under this firmware the exposure is what the GUI set (readout takes the
      rest of the frame period). So ``rate = counts / (frames * exposure)`` in
      cps, off a number the hardware was commanded with.

    * ``MODE_TIMESTAMP`` — at most one firing per frame is recorded, so the
      normalisation is the wall-clock frame period, taken from the tick count
      the exe *measured* into ``frame_rate_cnt.txt``: ``rate = occupancy /
      (frames * frame_period)`` in Hz, which cannot exceed
      ``1 / frame_period``.

When the measured frame period is unavailable or fails its consistency check,
this module reports no rate rather than inventing one, and the caller shows
the counted map (frames fired) with its own units. Nothing displayed is ever
an estimate.

This file can also be imported as a module and contains the following
functions:

    * mode_for_program - pick the reduction from a program file name.

    * frames_in_file - frame slots in a '.bin', from its size.

    * valid_frame_mask - per-frame flags marking the frames that carry data.

    * accumulate_hitmap - decode a '.bin' in chunks and reduce every frame it
    holds to a (32, 32) hitmap, using either mode.

    * resolve_frame_period - the measured wall-clock frame period, or None.

    * live_time_per_frame - live seconds per frame for the rate, per mode.

    * photon_rate - turn an accumulated hitmap into a rate map.

    * color_limits - the map's full (vmin, vmax), so every pixel including
    the hottest is shown as measured.
"""

from __future__ import annotations

import os

import numpy as np

from dapkel_rtp.functions.unpack import unpack

# Bytes per frame in a Kelpie v2 '.bin' file: 4 * 64 * 8 (see unpack()).
BYTES_PER_FRAME = 4 * 64 * 8

# 32-bit words per frame — the granularity the idle pattern repeats at.
WORDS_PER_FRAME = BYTES_PER_FRAME // 4

CLK_PERIOD = 5e-9  # 200 MHz clock -> 5 ns per tick

# Physical bounds used only to sanity-check the *measured* frame period from
# frame_rate_cnt.txt, never to stand in for it: a frame cannot be shorter than
# the exposure it contains, nor than the readout that follows it (~9 µs,
# whether the firmware adds that to the exposure or fits the exposure inside a
# fixed ~9 µs period). A counter left over from another run, or counting
# something other than this acquisition, lands outside these and is rejected.
_READOUT_FLOOR_S = 9e-6
_PERIOD_CEILING_S = 1.0

# The two reductions, named as in dapkel.functions.hitmap_analysis.
MODE_COUNT = "count"
MODE_TIMESTAMP = "timestamp"

# Frames decoded per chunk. Every frame of the acquisition is counted; this
# only bounds how many are held in memory at once (a chunk costs roughly
# 16 MB of decoded output), so an acquisition of any length is affordable.
CHUNK_FRAMES = 2000


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

    NOTE: this is the size of the DDR3 dump, not the number of frames that
    hold data — the file is a fixed-size buffer. Use 'valid_frame_mask' for
    the frames that actually carry data.

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


def valid_frame_mask(
    filepath: str, nframes: int, start_frame: int = 0
) -> np.ndarray:
    """Flag the frames of a '.bin' that carry data.

    A frame is *dead* when all of its 512 words are identical: that covers
    both the all-zero slots the acquisition never wrote and the constant
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


def resolve_frame_period(
    folder: str, nframes: int, exposure: float
) -> tuple[float | None, str]:
    """Return the measured wall-clock frame period, or None with a reason.

    The exe writes the tick count for the acquisition to
    ``frame_rate_cnt.txt``; divided by the frame count that is the measured
    period, as 'dcr_analysis._resolve_frame_time' reads it. Nothing is
    substituted when it is missing or fails the consistency check described
    at ``_READOUT_FLOOR_S`` — the caller then reports no rate instead of a
    modelled one.

    Parameters
    ----------
    folder : str
        Folder holding the acquisition (where ``frame_rate_cnt.txt`` lands).
    nframes : int
        Frames the acquisition was asked for — the tick count covers all of
        them, including the ones that carried no data.
    exposure : float
        Exposure per frame, in seconds, for the consistency check.

    Returns
    -------
    tuple[float | None, str]
        The measured frame period in seconds and a short source label, or
        None and the reason it could not be used.
    """
    cnt_file = os.path.join(folder, "frame_rate_cnt.txt")
    try:
        with open(cnt_file) as fh:
            ticks = int(fh.read().strip())
    except (OSError, ValueError):
        return None, "no frame_rate_cnt.txt"
    if ticks <= 0 or nframes <= 0:
        return None, "frame_rate_cnt.txt empty"

    period = ticks * CLK_PERIOD / nframes
    if period > _PERIOD_CEILING_S or period < max(exposure, _READOUT_FLOOR_S):
        return None, f"frame_rate_cnt.txt implausible ({period * 1e6:.3g} µs)"
    return period, f"{period * 1e6:.4g} µs frame (measured)"


def live_time_per_frame(
    mode: str, exposure: float, folder: str, nframes: int
) -> tuple[float | None, str, str]:
    """Return (live seconds per frame, rate unit, source) for a mode.

    ``MODE_COUNT`` accumulates photons only while the pixel is exposed, so
    the live time is the exposure the GUI set and the rate is in cps.
    ``MODE_TIMESTAMP`` records at most one firing per frame, so its live time
    is the measured wall-clock frame period and the rate is a firing rate in
    Hz (see the module docstring).

    Parameters
    ----------
    mode : str
        'MODE_COUNT' or 'MODE_TIMESTAMP'.
    exposure : float
        Exposure per frame, in seconds.
    folder : str
        Acquisition folder, for ``frame_rate_cnt.txt`` in timestamp mode.
    nframes : int
        Frames the acquisition was asked for, for the same.

    Returns
    -------
    tuple[float | None, str, str]
        Live seconds per frame (None when it is not known — a zero exposure,
        or no usable measured frame period — in which case the caller shows
        the counted map instead of a rate), the rate unit, and a short
        human-readable source.
    """
    if mode == MODE_COUNT:
        if not exposure > 0:
            return None, "cps", "no exposure set"
        return exposure, "cps", f"{exposure * 1e6:.4g} µs exposure"

    period, source = resolve_frame_period(folder, nframes, exposure)
    return period, "Hz", source


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
