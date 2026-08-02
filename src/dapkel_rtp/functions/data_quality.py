"""Data-quality check for one acquisition, run from the app that took it.

Nothing here contributes to a physics result. This answers one question about
a fresh '.bin', while the camera is still set up and the run can be repeated:
did the TDC actually record timing?

The failure mode is silent, exactly as described in
``dapkel.functions.data_quality``. When the ring-oscillator TDC never stops -
or the readout is misconfigured - 'unpack' still returns a full array of
plausible-looking integers, every downstream analysis still runs, and the
delta-t histogram still has a shape. It is simply meaningless. There is no
exception and no obviously wrong number; the only way to catch it is to look
at the raw code distribution. A working pixel's codes spread over the full
~0..1300 oscillator range, a broken run collapses onto a handful of values.

What this module adds over the offline version is what the live app needs:

    * one file at a time, chosen from the folder being acquired into, rather
      than a whole tagged series - the point is to check the run you just
      took;

    * an exact histogram accumulated over the file in chunks instead of the
      raw codes kept in memory. Pooling all 1024 pixels of a million-frame
      acquisition would be a billion values; the per-code histogram answers
      every question asked of it (count, unique codes, quantiles, most common
      code) exactly, at a fixed ~64 kB;

    * the same structural dead-frame rejection the live hitmap uses
      ('hitmap.valid_frame_mask'), so the fixed-size DDR3 dump's unwritten
      slots and the chip's pre-acquisition idle pattern are not counted as
      frames that failed to record timing;

    * the program tag read off the file name, because the check only means
      anything for a *timestamp* program. In a ``*C`` (count) program the
      bits this module decodes as coarse/fine time are photon counts, so no
      verdict is given for such a file rather than a misleading one.

This file can also be imported as a module and contains the following
functions:

    * detect_tag - the Kelpie program tag in a '.bin' file name, or None.

    * mode_for_bin - the readout mode a '.bin' file name implies, or None.

    * scan_bin_files - the '.bin' files in a folder, with size and frames.

    * collect_time_codes - accumulate one file's TDC-code histogram.

    * summarize - turn that histogram into numbers and a verdict.

    * check_file - collect + summarize, the one call the GUI makes.

    * histogram_for_display - rebin the exact histogram for plotting.

    * format_report - the summary as a short monospaced block.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

import numpy as np

from dapkel_rtp.functions.hitmap import (
    BYTES_PER_FRAME,
    CHUNK_FRAMES,
    MODE_COUNT,
    MODE_TIMESTAMP,
    frames_in_file,
    mode_for_program,
    valid_frame_mask,
)
from dapkel_rtp.functions.unpack import unpack

__all__ = [
    # readout mode of a file (MODE_COUNT/MODE_TIMESTAMP re-exported from
    # hitmap, so a caller needs only this module)
    "MODE_AUTO",
    "MODE_COUNT",
    "MODE_TIMESTAMP",
    "detect_tag",
    "mode_for_bin",
    # find and check files
    "scan_bin_files",
    "collect_time_codes",
    "summarize",
    "check_file",
    # present the result
    "histogram_for_display",
    "format_report",
    "VERDICT_PASS",
    "VERDICT_SUSPECT",
    "VERDICT_FAIL",
    "VERDICT_NA",
]

# A frame counts as having recorded timing when its code is strictly positive,
# matching dapkel.functions.data_quality's 'valid_min' default. Empty slots
# decode to zero or to a small negative code (see 'unpack'), never above it.
VALID_MIN = 0.0

# Widest code 'unpack' can produce: coarse time is 10 bits, so the corrected
# coarse tops out at 1023 and ts = (coarse - 1) * 8 + (8 - fine) at 8184. The
# histogram is grown past this if a future decode ever exceeds it, so nothing
# is silently clipped into the last bin.
CODE_MAX = 8184

# Program tags this GUI can write, longest first so 'ORS0S1' is preferred over
# any shorter tag that happens to be a substring of it.
_KNOWN_TAGS = (
    "ORS0S1",
    "ORS0S2",
    "ORS0S3",
    "coincS0S1",
    "coincS0S2",
    "coincS0S3",
    "ORC",
    "ORT",
    "S0C",
    "S1C",
    "S2C",
    "S3C",
    "S0T",
    "S1T",
    "S2T",
    "S3T",
    "C2T",
    "C3T",
    "C4T",
)

# A tag must stand on its own: preceded by the start of the name or a
# non-letter (the '_' the acquisition tabs insert), and followed by the end,
# a digit (the acquisition index, e.g. 'data_ORT12.bin') or a non-letter.
_TAG_RE = re.compile(
    "(?<![A-Za-z])("
    + "|".join(sorted(_KNOWN_TAGS, key=len, reverse=True))
    + ")(?![A-Za-z])",
    re.IGNORECASE,
)

# --- Verdict thresholds ----------------------------------------------------
# Heuristics, not physics: they only decide which of three words is printed
# next to the numbers, and every number they are derived from is reported
# alongside so the run can be judged directly. Chosen from what the failure
# looks like (dapkel's docs/guide/data_quality.md): healthy codes spread over
# the ~0..1300 oscillator range, a dead TDC collapses onto a handful of
# values, often a single code repeated across every frame.

# Below this many valid codes there is nothing to judge - a genuinely dark
# pixel over a short file can legitimately produce a few scattered codes.
MIN_SAMPLE = 100

# "A few unique values out of thousands of frames means the run is unusable."
FAIL_UNIQUE = 4
SUSPECT_UNIQUE = 16

# One code taking most of the distribution is the classic stuck-TDC signature.
FAIL_TOP_SHARE = 0.9
SUSPECT_TOP_SHARE = 0.5

# Central 98% of the codes spanning less than this much of the ~1300-code
# range is narrow enough to be worth a second look - a count-mode file
# mistaken for a timestamp one lands here, for instance. Only SUSPECT, never
# FAIL: a pulsed source at a fixed delay legitimately concentrates the
# first-photon times into a narrow peak, which is exactly what a delta-t
# measurement is after.
SUSPECT_SPREAD = 128

VERDICT_PASS = "PASS"
VERDICT_SUSPECT = "SUSPECT"
VERDICT_FAIL = "FAIL"
VERDICT_NA = "n/a"

# Passed as 'mode' to ask for the readout mode to be read off the file name.
MODE_AUTO = "auto"


def detect_tag(path: str) -> str | None:
    """Return the Kelpie program tag in a '.bin' file name, or None.

    The acquisition tabs name their output ``<prefix>_<tag><index>.bin``, so
    the tag that produced a file is normally recoverable from its name. A file
    named some other way returns None rather than a guess.

    Parameters
    ----------
    path : str
        Path to, or name of, the '.bin' file.

    Returns
    -------
    str | None
        The tag as spelled in the program file (e.g. ``'ORT'``), or None when
        the name carries no recognisable tag.
    """
    match = _TAG_RE.search(os.path.basename(path or ""))
    if match is None:
        return None
    found = match.group(1).upper()
    for tag in _KNOWN_TAGS:
        if tag.upper() == found:
            return tag
    return found


def mode_for_bin(path: str) -> tuple[str | None, str | None]:
    """Return the readout mode a '.bin' file name implies, with its tag.

    Parameters
    ----------
    path : str
        Path to, or name of, the '.bin' file.

    Returns
    -------
    tuple[str | None, str | None]
        ``(mode, tag)``, where mode is 'MODE_COUNT' or 'MODE_TIMESTAMP' as
        'hitmap.mode_for_program' decides it, or ``(None, None)`` when the
        name carries no recognisable tag - in which case the caller must say
        so rather than assume a mode.
    """
    tag = detect_tag(path)
    if tag is None:
        return None, None
    return mode_for_program(tag), tag


def _natural_key(name: str) -> list:
    """Sort key ordering by the digit runs in a name, so ``_2`` precedes
    ``_10``."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
    ]


def scan_bin_files(folder: str) -> list[dict]:
    """List the '.bin' files in a folder with what can be known cheaply.

    Only file metadata is read - nothing is decoded - so this stays instant on
    a folder holding hundreds of multi-hundred-megabyte acquisitions.

    Parameters
    ----------
    folder : str
        Path to the folder with the '.bin' data files.

    Returns
    -------
    list[dict]
        One entry per file, naturally sorted by name, with keys ``path``,
        ``name``, ``size`` (bytes), ``frames`` (whole frame slots the file has
        room for), ``mtime``, ``tag`` and ``mode`` (both None when the name
        carries no recognisable program tag).

    Raises
    ------
    NotADirectoryError
        Raised when ``folder`` is not an existing directory.
    """
    if not folder or not os.path.isdir(folder):
        raise NotADirectoryError(f"Not a folder:\n  {folder}")

    entries = []
    with os.scandir(folder) as it:
        for item in it:
            if not item.is_file() or not item.name.lower().endswith(".bin"):
                continue
            try:
                stat = item.stat()
            except OSError:
                continue  # vanished or locked mid-scan; nothing to report
            mode, tag = mode_for_bin(item.name)
            entries.append(
                {
                    "path": item.path,
                    "name": item.name,
                    "size": stat.st_size,
                    "frames": stat.st_size // BYTES_PER_FRAME,
                    "mtime": stat.st_mtime,
                    "tag": tag,
                    "mode": mode,
                }
            )
    entries.sort(key=lambda e: _natural_key(e["name"]))
    return entries


def collect_time_codes(
    filepath: str,
    nframes: int | None = None,
    pixel: tuple[int, int] | None = None,
    *,
    chunk_frames: int = CHUNK_FRAMES,
    progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> dict:
    """Accumulate one file's TDC-code histogram, chunk by chunk.

    The rtp counterpart of 'dapkel.functions.data_quality.collect_time_mat':
    same quantity (the per-frame TDC codes, keeping only the frames whose
    timestamp is valid), gathered from a single file as an exact per-code
    histogram instead of the raw codes, so pooling every pixel of a long
    acquisition costs a fixed amount of memory. Frames that carry no data are
    dropped structurally by 'hitmap.valid_frame_mask' - they were never
    written, so they are not evidence of a TDC that failed to record.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file to check.
    nframes : int | None, optional
        Frames to examine from the start of the file. When None (default)
        every frame slot the file holds is examined. Never reads past the end
        of the file.
    pixel : tuple[int, int] | None, optional
        A single ``(row, col)`` pixel to histogram. When None (default) the
        codes of all 32x32 pixels are pooled.
    chunk_frames : int, optional
        Frames decoded at a time. Affects memory only, never the result. The
        default is 'hitmap.CHUNK_FRAMES'.
    progress : callable, optional
        Called as ``progress(frames_done, frames_total)`` after each chunk.
    should_abort : callable, optional
        Polled between chunks; when it returns True the walk stops and the
        partial result is returned with ``aborted`` set.

    Returns
    -------
    dict
        ``hist`` (int64 counts indexed by TDC code), ``pixel_valid``
        ((32, 32) int64 count of valid codes per pixel, always over the whole
        array even when one pixel was histogrammed), ``frames_read``,
        ``frames_with_data``, ``frames_in_file``, ``pixel``, ``filepath`` and
        ``aborted``.

    Raises
    ------
    ValueError
        Raised when the file holds no whole frame, or ``pixel`` is off the
        32x32 array.
    """
    if pixel is not None:
        row, col = int(pixel[0]), int(pixel[1])
        if not (0 <= row < 32 and 0 <= col < 32):
            raise ValueError(
                f"pixel must be within the 32x32 array, got ({row}, {col})."
            )
        pixel = (row, col)

    slots = frames_in_file(filepath)
    read = slots if nframes is None else min(int(nframes), slots)
    if read < 1:
        raise ValueError(
            f"{os.path.basename(filepath)} holds no whole "
            f"{BYTES_PER_FRAME}-byte frame."
        )

    hist = np.zeros(CODE_MAX + 1, dtype=np.int64)
    pixel_valid = np.zeros((32, 32), dtype=np.int64)
    frames_with_data = 0
    done = 0
    aborted = False

    for start in range(0, read, max(1, int(chunk_frames))):
        if should_abort is not None and should_abort():
            aborted = True
            break

        n = min(int(chunk_frames), read - start)
        valid = valid_frame_mask(filepath, n, start_frame=start)
        done += n
        if valid.any():
            frames_with_data += int(valid.sum())
            time_series, _ = unpack(
                filepath, n, compute_time_series=True, start_frame=start
            )
            live = time_series[:, :, valid]
            good = live > VALID_MIN
            pixel_valid += good.sum(axis=2)

            if pixel is None:
                codes = live[good]
            else:
                r, c = pixel
                codes = live[r, c][good[r, c]]

            if codes.size:
                counts = np.bincount(codes.astype(np.int64))
                if counts.size > hist.size:
                    # Cannot happen for a code 'unpack' produced, but growing
                    # beats folding an out-of-range code into the last bin.
                    hist = np.concatenate(
                        [hist, np.zeros(counts.size - hist.size, np.int64)]
                    )
                hist[: counts.size] += counts

        if progress is not None:
            progress(done, read)

    return {
        "hist": hist,
        "pixel_valid": pixel_valid,
        "frames_read": done,
        "frames_with_data": frames_with_data,
        "frames_in_file": slots,
        "pixel": pixel,
        "filepath": filepath,
        "aborted": aborted,
    }


def _quantile(hist: np.ndarray, cum: np.ndarray, q: float) -> int:
    """Return the code at quantile ``q`` of a per-code histogram."""
    total = int(cum[-1])
    if total <= 0:
        return 0
    return int(np.searchsorted(cum, q * total, side="left"))


def summarize(result: dict, mode: str | None = None) -> dict:
    """Turn a collected histogram into the numbers, and a verdict.

    Every statistic is computed exactly from the per-code histogram, so it is
    the same number the raw codes would have given.

    Parameters
    ----------
    result : dict
        The dict returned by 'collect_time_codes'.
    mode : str | None, optional
        Readout mode of the file, from 'mode_for_bin'. In 'MODE_COUNT' the
        decoded "codes" are photon-count bits rather than time, so no verdict
        is returned. None (default) means the mode is not known, and no
        verdict is returned either — the numbers are all still reported, but
        whether they mean anything depends on which program wrote the file,
        so that is asked for rather than assumed.

    Returns
    -------
    dict
        The input keys plus ``mode``, ``n_codes``, ``unique``, ``median``,
        ``p1``, ``p99``, ``spread``, ``mean``, ``top_code``, ``top_share``,
        ``pixels_live``, ``pixels_total``, ``occupancy`` (valid codes per
        examined pixel-frame), ``verdict`` and ``reason``.
    """
    hist = result["hist"]
    cum = np.cumsum(hist)
    n = int(cum[-1]) if cum.size else 0
    unique = int(np.count_nonzero(hist))

    if n:
        codes_axis = np.arange(hist.size, dtype=np.float64)
        mean = float((codes_axis * hist).sum() / n)
        median = _quantile(hist, cum, 0.5)
        p1 = _quantile(hist, cum, 0.01)
        p99 = _quantile(hist, cum, 0.99)
        top_code = int(np.argmax(hist))
        top_share = float(hist[top_code] / n)
    else:
        mean = 0.0
        median = p1 = p99 = top_code = 0
        top_share = 0.0

    pixel_valid = result["pixel_valid"]
    npix = 1 if result["pixel"] is not None else pixel_valid.size
    frames = result["frames_with_data"]
    occupancy = n / (frames * npix) if frames and npix else 0.0

    verdict, reason = _verdict(mode, frames, n, unique, top_share, p99 - p1)

    return {
        **result,
        "mode": mode,
        "n_codes": n,
        "unique": unique,
        "median": median,
        "p1": p1,
        "p99": p99,
        "spread": p99 - p1,
        "mean": mean,
        "top_code": top_code,
        "top_share": top_share,
        "pixels_live": int(np.count_nonzero(pixel_valid)),
        "pixels_total": int(pixel_valid.size),
        "occupancy": occupancy,
        "verdict": verdict,
        "reason": reason,
    }


def _verdict(
    mode: str | None,
    frames: int,
    n: int,
    unique: int,
    top_share: float,
    spread: int,
) -> tuple[str, str]:
    """Classify a code distribution against the thresholds above."""
    if frames == 0:
        # Nothing was written into the range examined, so this says nothing
        # about the TDC - reported before the mode checks, because it is true
        # of a count file just the same.
        return (
            VERDICT_FAIL,
            "no frame in the examined range carries data - the acquisition "
            "wrote nothing there",
        )
    if mode == MODE_COUNT:
        return (
            VERDICT_NA,
            "count-mode file - these bits are photon counts, not time; "
            "check timing on a *T acquisition",
        )
    if mode is None:
        # A count file decodes to a perfectly plausible-looking - and
        # perfectly meaningless - code distribution, so a file whose program
        # cannot be named gets its numbers and no verdict. Say which program
        # wrote it to get one.
        return (
            VERDICT_NA,
            "unknown program - no tag in the file name; say whether this was "
            "a timestamp (*T) or a count (*C) run to get a verdict",
        )
    if n == 0:
        return VERDICT_FAIL, "no pixel-frame recorded a timestamp at all"
    if n < MIN_SAMPLE:
        return (
            VERDICT_NA,
            f"only {n} valid code(s) - too few to judge; check more frames "
            f"or a brighter pixel",
        )
    if unique <= FAIL_UNIQUE:
        return (
            VERDICT_FAIL,
            f"codes collapsed onto {unique} value(s) - the TDC is not timing",
        )
    if top_share > FAIL_TOP_SHARE:
        return (
            VERDICT_FAIL,
            f"{top_share:.1%} of all codes are the single value "
            f"- the TDC is stuck",
        )
    if unique < SUSPECT_UNIQUE:
        return VERDICT_SUSPECT, f"only {unique} distinct codes"
    if top_share > SUSPECT_TOP_SHARE:
        return VERDICT_SUSPECT, f"one code takes {top_share:.1%} of the total"
    if spread < SUSPECT_SPREAD:
        return (
            VERDICT_SUSPECT,
            f"central 98% spans only {spread} codes of the ~1300 range",
        )
    return VERDICT_PASS, f"{unique} distinct codes spread over {spread}"


def check_file(
    filepath: str,
    nframes: int | None = None,
    pixel: tuple[int, int] | None = None,
    mode: str | None = MODE_AUTO,
    **kwargs,
) -> dict:
    """Collect and summarize one file - the single call the GUI makes.

    Parameters
    ----------
    filepath : str
        Path to the '.bin' file to check.
    nframes : int | None, optional
        Frames to examine. None (default) examines the whole file.
    pixel : tuple[int, int] | None, optional
        Pixel to histogram, or None (default) to pool all of them.
    mode : str | None, optional
        'MODE_COUNT' or 'MODE_TIMESTAMP' to state which program wrote the
        file, overriding its name. The default, 'MODE_AUTO', reads the mode
        off the file name and leaves it unknown when there is no tag there.
    **kwargs
        Passed through to 'collect_time_codes' (``chunk_frames``,
        ``progress``, ``should_abort``).

    Returns
    -------
    dict
        The summary dict from 'summarize', with ``tag`` (the tag found in the
        file name, or None) and ``mode_source`` ('name' or 'stated') added.
    """
    detected, tag = mode_for_bin(filepath)
    if mode == MODE_AUTO:
        mode, source = detected, "name"
    else:
        source = "stated"
    result = collect_time_codes(filepath, nframes, pixel, **kwargs)
    summary = summarize(result, mode)
    summary["tag"] = tag
    summary["mode_source"] = source
    return summary


def histogram_for_display(
    hist: np.ndarray, bins: int = 256
) -> tuple[np.ndarray, np.ndarray]:
    """Rebin the exact per-code histogram down to at most ``bins`` columns.

    Only the plot is rebinned; every reported number comes from the full-
    resolution histogram. Bins are whole numbers of codes wide and the range
    is the observed one, so no count is split across columns or invented
    outside them.

    Parameters
    ----------
    hist : np.ndarray
        Per-code counts, as returned by 'collect_time_codes'.
    bins : int, optional
        Maximum number of columns to draw. The default is 256.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(edges, values)`` ready for ``ax.stairs(values, edges)``. Both are
        empty when no code was recorded.
    """
    nonzero = np.nonzero(hist)[0]
    if nonzero.size == 0:
        return np.empty(0), np.empty(0)

    lo, hi = int(nonzero[0]), int(nonzero[-1])
    span = hi - lo + 1
    width = max(1, -(-span // max(1, int(bins))))  # ceil division
    n_bins = -(-span // width)

    padded = np.zeros(n_bins * width, dtype=np.int64)
    padded[:span] = hist[lo : hi + 1]
    values = padded.reshape(n_bins, width).sum(axis=1)
    edges = lo + width * np.arange(n_bins + 1)
    return edges, values


def format_report(summary: dict) -> str:
    """Render a summary as a short monospaced block.

    Parameters
    ----------
    summary : dict
        The dict returned by 'check_file' or 'summarize'.

    Returns
    -------
    str
        Six lines: file, frames, codes, spread, pixels, verdict.
    """
    pixel = summary["pixel"]
    where = "all 32x32 pixels" if pixel is None else f"pixel ({pixel[0]},{pixel[1]})"
    tag = summary.get("tag")
    mode = summary.get("mode")
    if summary.get("mode_source") == "stated":
        which = f"{mode} program (stated)"
    elif tag:
        which = f"tag {tag} · {mode} program"
    else:
        which = "no program tag in the file name"

    n = summary["n_codes"]
    read = summary["frames_read"]
    slots = summary["frames_in_file"]
    with_data = summary["frames_with_data"]

    if n:
        spread = (
            f"median {summary['median']}, 1–99% {summary['p1']}–"
            f"{summary['p99']} ({summary['spread']} wide), most common "
            f"{summary['top_code']} ({summary['top_share']:.1%})"
        )
    else:
        spread = "—"

    lines = [
        f"file     {os.path.basename(summary['filepath'])}  ·  {which}",
        f"frames   {read} of {slots} examined, {with_data} carried data"
        + ("   [ABORTED]" if summary["aborted"] else ""),
        f"codes    {n:,} valid from {where}, {summary['unique']} unique "
        f"(occupancy {summary['occupancy']:.3g} per pixel-frame)",
        f"spread   {spread}",
        f"pixels   {summary['pixels_live']}/{summary['pixels_total']} "
        f"recorded timing",
        f"verdict  {summary['verdict']} — {summary['reason']}",
    ]
    return "\n".join(lines)
