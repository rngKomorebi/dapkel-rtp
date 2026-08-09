"""Acquisition metadata: what was set, where, and when, written beside the data.

Until now nothing recorded how a '.bin' was taken. The numbers lived in the
GUI's spin boxes and nowhere else, so a folder of data could not be re-analysed
without remembering — or guessing — the frame count, the exposure and the
firmware it was acquired with. Guessing has already cost the group one round of
wrong conclusions: a '.bin' holds more frame slots than the run asked for, so
"read every frame the file holds" silently counts real frames twice.

The exe's own ``frame_rate_cnt.txt`` is not that record and never was. It holds
one firmware counter, it is overwritten by every acquisition so only the last
survives, and across the group's drive it does not track the exposure register
coherently: a clean 50/100/200/500 ns sweep read 9.700, 9.710, 9.700 and
9.770 µs per frame — not monotonic. Nothing here reads it.

One file per folder
-------------------
``metadata.json`` describes *runs*, not files. Every file of a run shares its
settings and differs only in when it was written, so a 10 000-file run gets one
record, with the filename pattern and index range needed to match a file back
to it. A folder can hold several runs — a ``Start#`` continuation, or two chain
jobs pointing at the same folder — so the file is a ``runs`` array that
'upsert_run' appends to. An existing ``metadata.json`` that is not ours is
never overwritten; the record goes to ``metadata_dapkel_rtp.json`` instead.

Key names
---------
Two physical quantities describe the timing, and they describe both firmware
versions with no nulls and no mode-dependent meaning:

    * ``open_shutter_time_s`` — how long the shutter is open within one frame.
      Always the exposure register times the 5 ns clock tick.

    * ``frame_acq_time_s`` — how long one frame takes. A fixed 9 µs under
      ``short_exposure``; ``open_shutter_time_s + 9 µs`` under
      ``long_exposure``.

So the register always means the same thing and the firmware decides only
whether the frame is fixed or stretches. This deliberately does *not* reuse
``dapkel``'s ``frame_cycle_s`` / ``exp_time_s`` / ``exposure_window_s`` triple,
which needs a null in every record and puts two similar names on two different
quantities. Nothing reads an rtp acquisition record yet — ``dapkel``'s own
``.meta.json`` sidecars sit next to '.npy' files in ``processed/`` and are a
different artefact — so the divergence costs nothing today, and when the two
are wired together ``dapkel`` learns these names. ``firmware_version`` keeps
``dapkel``'s exact vocabulary ('short_exposure' / 'long_exposure'), because
that one *is* shared.

``wallclock_time_s`` also keeps ``dapkel``'s meaning — ``total_frames *
frame_acq_time_s``, a derived camera time, not a measurement. The measured host
duration is a separate key, ``wallclock_time_measured_s``. They differ by a lot
(9.7 s of camera against 68.2 s at the bench for the 2026-07-22 batch: a 14 %
duty cycle), so collapsing them into one name would make every rate wrong by
that factor.

The frame length itself is not computed here — 'functions.timing' owns it, and
``resolve_frame_acq_time`` is re-exported from this module only so a caller
writing a record needs one import.

This file can also be imported as a module and contains the following
functions:

    * probe_readout - what a run's '.bin' actually holds, replay included.

    * build_run_record - assemble one run's record from settings + measurements.

    * upsert_run - merge a record into a folder's 'metadata.json', atomically.

    * read_runs - the records a folder's 'metadata.json' holds.

    * run_for_file - the record describing a given '.bin', or None.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone

from dapkel_rtp import __version__ as APP_VERSION
from dapkel_rtp.functions.hitmap import (
    BYTES_PER_FRAME,
    REPLAY_BLOCK_FRAMES,
    frames_in_file,
    tail_is_replay,
)
from dapkel_rtp.functions.timing import (
    CLK_PERIOD,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    FRAME_READOUT_S,
    resolve_frame_acq_time,
)

SCHEMA_VERSION = 1

METADATA_FILENAME = "metadata.json"

# Used when the folder already holds a 'metadata.json' that is not ours. An
# operator's or another tool's file is never overwritten to make room for this
# one.
FALLBACK_FILENAME = "metadata_dapkel_rtp.json"

__all__ = [
    "SCHEMA_VERSION",
    "METADATA_FILENAME",
    "FALLBACK_FILENAME",
    "FRAME_READOUT_S",
    "FIRMWARE_SHORT_EXPOSURE",
    "FIRMWARE_LONG_EXPOSURE",
    "resolve_frame_acq_time",
    "probe_readout",
    "build_run_record",
    "new_run_id",
    "upsert_run",
    "read_runs",
    "run_for_file",
    "file_names_for_run",
]


# ---------------------------------------------------------------------------
# What the readout actually wrote
# ---------------------------------------------------------------------------

_REPLAY_NOTE = (
    "Slots at or past nframes are a byte-exact replay of the slots "
    "{block} earlier, so the file holds nframes frames of data and nothing "
    "more. Read only the first nframes: reading the whole file counts "
    "{dup} frames twice."
)

_UNVERIFIED_NOTE = (
    "The tail past nframes was NOT a byte-exact replay of the slots {block} "
    "earlier, which is what every file measured so far has been. Look at it "
    "before trusting or discarding it -- it may be real data this run wrote."
)

_NO_TAIL_NOTE = (
    "The file holds no slots past nframes, so there is no replayed tail to "
    "account for."
)

# A run shorter than one readout block cannot have a replayed tail: there is
# nothing a block back to replay. Its surplus slots were simply never written,
# and read as the chip's constant idle pattern -- measured at 7 692 dead slots
# of 8 192 on a ~500-frame live-view file. 'hitmap.valid_frame_mask' drops those.
_DEAD_TAIL_NOTE = (
    "nframes is under one {block}-frame readout block, so the surplus slots "
    "cannot be a replay -- this run never wrote them. They read as the chip's "
    "constant idle pattern and valid_frame_mask drops them. Still read only the "
    "first nframes: anything beyond is either idle or left over from an earlier "
    "run."
)


def probe_readout(filepath: str, nframes: int, verify: bool = True) -> dict:
    """Describe what one of a run's '.bin' files actually holds.

    Records the requested frame count and the raw file shape side by side
    rather than collapsing them into one number: those two disagreeing is the
    whole of the block-quantisation story, and a record keeping only one of
    them destroys the evidence.

    Parameters
    ----------
    filepath : str
        Path to one '.bin' of the run.
    nframes : int
        Frames the run asked for.
    verify : bool, optional
        Byte-compare the tail against the slots one block earlier
        ('hitmap.tail_is_replay'). One pass over the file; worth doing once per
        run so a firmware change shows up rather than being assumed away. The
        default is True.

    Returns
    -------
    dict
        ``bytes_in_file``, ``frame_slots_in_file``, ``independent_frames``,
        ``duplicate_tail_frames``, ``duplicate_tail_source_start``,
        ``replay_block_frames``, ``verified`` (True/False, or None when not
        checked or not checkable) and ``note``.
    """
    n = int(nframes)
    size = os.path.getsize(filepath)
    slots = frames_in_file(filepath)
    dup = max(0, slots - n)
    source_start = n - REPLAY_BLOCK_FRAMES if dup and n >= REPLAY_BLOCK_FRAMES else None

    verified = tail_is_replay(filepath, n) if verify else None
    if dup == 0:
        note = _NO_TAIL_NOTE
    elif n < REPLAY_BLOCK_FRAMES:
        note = _DEAD_TAIL_NOTE.format(block=REPLAY_BLOCK_FRAMES)
    elif verified is False:
        note = _UNVERIFIED_NOTE.format(block=REPLAY_BLOCK_FRAMES)
    elif verified is True:
        note = _REPLAY_NOTE.format(block=REPLAY_BLOCK_FRAMES, dup=dup)
    else:
        # Not checked (verify=False): say what is expected, not what is known.
        note = (
            f"{dup} slots past nframes were not inspected. Every file measured "
            f"so far replays the slots {REPLAY_BLOCK_FRAMES} earlier there. "
            "Read only the first nframes."
        )

    return {
        "bytes_in_file": size,
        "frame_slots_in_file": slots,
        "independent_frames": min(n, slots),
        "duplicate_tail_frames": dup,
        "duplicate_tail_source_start": source_start,
        "replay_block_frames": REPLAY_BLOCK_FRAMES,
        "bytes_per_frame": BYTES_PER_FRAME,
        "verified": verified,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_git_commit_cached: str | None | bool = False  # False = not looked up yet


def _git_commit() -> str | None:
    """Short HEAD of the source tree, or None (frozen build, no git, no repo)."""
    global _git_commit_cached
    if _git_commit_cached is not False:
        return _git_commit_cached  # type: ignore[return-value]

    _git_commit_cached = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            _git_commit_cached = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass  # provenance is nice to have, never a reason to fail a run
    return _git_commit_cached  # type: ignore[return-value]


def _sha256(path: str | None) -> str | None:
    """Hex SHA-256 of a file, or None when it is missing or unreadable."""
    if not path or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _utc_iso(stamp: float) -> str | None:
    """Epoch seconds as '2026-08-04T14:22:07.412Z', or None if unconvertible.

    A timestamp the platform will not convert must cost one field, not the whole
    record — the point of writing it is that the run is documented.
    """
    try:
        dt = datetime.fromtimestamp(stamp, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _local_iso(stamp: float) -> str | None:
    """Epoch seconds as local time with its UTC offset, or None (see '_utc_iso').

    Windows raises OSError from 'astimezone' for timestamps near the epoch.
    """
    try:
        return (
            datetime.fromtimestamp(stamp)
            .astimezone()
            .isoformat(timespec="milliseconds")
        )
    except (OSError, OverflowError, ValueError):
        return None


def new_run_id(started: float, folder: str, filename_prefix: str) -> str:
    """Return a run id that is unique per folder without needing randomness.

    Shaped ``<utc timestamp>-<8 hex>``, the hex being a digest of the folder,
    prefix and start time, so two runs started in the same second into
    different folders cannot collide and the id is reproducible from its parts.
    """
    seed = f"{folder}|{filename_prefix}|{started!r}".encode()
    # Uniqueness comes from the digest, so an unconvertible timestamp falls back
    # to the raw seconds rather than putting 'None' in the id.
    stamp = _utc_iso(started) or f"{started:.3f}"
    return f"{stamp}-{hashlib.sha256(seed).hexdigest()[:8]}"


# ---------------------------------------------------------------------------
# Building a record
# ---------------------------------------------------------------------------


def build_run_record(
    settings: dict,
    *,
    run_id: str,
    status: str,
    started: float,
    finished: float | None = None,
    n_files_written: int = 0,
    per_file_elapsed_s: list | None = None,
    readout: dict | None = None,
    bytes_per_file: int | None = None,
) -> dict:
    """Assemble one run's record from what was set plus what was measured.

    Parameters
    ----------
    settings : dict
        What the operator set, gathered by the tab that started the run. Read
        here:

        ``folder``, ``filename_prefix``, ``program_tag``, ``mode``,
        ``program_file`` (full path), ``start_index``, ``nacq_requested``,
        ``nframes``, ``open_shutter_clks``, ``firmware_version``,
        ``firmware_bitfile`` (full path or None), ``firmware_bitfile_source``
        ('short_exposure' / 'long_exposure' / 'legacy fallback' / None),
        ``firmware_programmed_this_session`` (bool), ``chip_config``,
        ``chip_config_bits`` (dict), ``bias_voltage_v`` (float or None),
        ``exe`` (full path to Kelpie_v2.exe), ``power_management`` (dict).

        Missing keys degrade to None rather than raising: an incomplete record
        is worth more than no record.
    run_id : str
        From 'new_run_id'. Reused when updating an in-flight record.
    status : str
        'completed', 'aborted', 'failed', or 'running' for a record written
        mid-run. A leftover 'running' means the app never got to finish it.
    started, finished : float
        ``time.time()`` at the start and end of the run. ``finished`` is None
        while it is still going.
    n_files_written : int, optional
        '.bin' files this run has actually written so far.
    per_file_elapsed_s : list, optional
        Wall-clock seconds each acquisition took. Summarised to min/median/max
        rather than stored per file — 10 000 numbers say no more than three.
    readout : dict, optional
        From 'probe_readout', for one file of the run.
    bytes_per_file : int, optional
        Size of one '.bin'. Every file of a run is the same size.

    Returns
    -------
    dict
        The run record, ready for 'upsert_run'.
    """
    get = settings.get

    nframes = int(get("nframes") or 0)
    clks = int(get("open_shutter_clks") or 0)
    shutter_s = clks * CLK_PERIOD
    firmware = get("firmware_version") or FIRMWARE_SHORT_EXPOSURE
    try:
        frame_s, frame_source = resolve_frame_acq_time(firmware, shutter_s)
    except ValueError as exc:
        frame_s, frame_source = FRAME_READOUT_S, f"unknown firmware: {exc}"

    total_frames = nframes * int(n_files_written)
    elapsed = [float(t) for t in (per_file_elapsed_s or [])]

    record = {
        "run_id": run_id,
        "status": status,
        "started_utc": _utc_iso(started),
        "finished_utc": _utc_iso(finished) if finished is not None else None,
        "started_local": _local_iso(started),
        # ---- which files this run wrote ----
        "file_pattern": "{prefix}_{tag}{i}.bin",
        "filename_prefix": get("filename_prefix"),
        "tag": get("program_tag"),
        "mode": get("mode"),
        "start_index": get("start_index"),
        "nacq_requested": get("nacq_requested"),
        "n_files_written": int(n_files_written),
        "file_index_range": (
            [get("start_index"), get("start_index") + int(n_files_written) - 1]
            if get("start_index") is not None and n_files_written
            else None
        ),
        "bytes_per_file": bytes_per_file,
        # ---- how ----
        "nframes": nframes,
        "n_files": int(n_files_written),
        "total_frames": total_frames,
        "firmware_version": firmware,
        "firmware_bitfile": _basename_or_none(get("firmware_bitfile")),
        "firmware_bitfile_sha256": _sha256(get("firmware_bitfile")),
        # Both firmware folders hold a file called 'Kelpie_top.bit', so the
        # basename alone cannot say which was loaded -- and if neither has been
        # placed yet the app falls back to the legacy single-bitfile folder, in
        # which case 'firmware_version' records a selection rather than an
        # observation. Say which happened.
        "firmware_bitfile_source": get("firmware_bitfile_source"),
        "firmware_programmed_this_session": bool(
            get("firmware_programmed_this_session")
        ),
        "open_shutter_clks": clks,
        "open_shutter_time_s": shutter_s,
        "open_shutter_time_source": (
            f"nominal: {clks} clks x {CLK_PERIOD * 1e9:.0f} ns. Exposure "
            "register 0 still returns counts (functions/tools/"
            "exposure_sweep.py), so the true open window may exceed nominal by "
            "a baseline nobody has measured yet."
        ),
        "frame_acq_time_s": frame_s,
        "frame_acq_time_source": frame_source,
        "wallclock_time_s": total_frames * frame_s,
        "wallclock_time_note": (
            "total_frames * frame_acq_time_s -- camera time, derived, matching "
            "dapkel's key of the same name. The measured host duration is "
            "wallclock_time_measured_s and is a different number."
        ),
        "wallclock_time_measured_s": (
            round(finished - started, 3) if finished is not None else None
        ),
        "per_file_elapsed_s": (
            {
                "min": round(min(elapsed), 3),
                "median": round(statistics.median(elapsed), 3),
                "max": round(max(elapsed), 3),
            }
            if elapsed
            else None
        ),
        "chip_config": get("chip_config"),
        "chip_config_bits": get("chip_config_bits"),
        "program_file": _basename_or_none(get("program_file")),
        "program_sha256": _sha256(get("program_file")),
        "power_management": get("power_management"),
        # ---- what landed on disk ----
        "readout": readout,
        # ---- operator context ----
        "bias_voltage_v": get("bias_voltage_v"),
        # ---- provenance ----
        "folder": get("folder"),
        "host": _hostname(),
        "user": os.environ.get("USERNAME") or os.environ.get("USER"),
        "app_version": APP_VERSION,
        "app_git_commit": _git_commit(),
        "exe": _basename_or_none(get("exe")),
        "exe_sha256": _sha256(get("exe")),
    }
    return record


def _basename_or_none(path: str | None) -> str | None:
    return os.path.basename(path) if path else None


def _hostname() -> str | None:
    try:
        import socket

        return socket.gethostname()
    except Exception:  # noqa: BLE001 - provenance never fails a run
        return None


def file_names_for_run(record: dict) -> list[str]:
    """Return the '.bin' names a record says its run wrote."""
    prefix = record.get("filename_prefix")
    tag = record.get("tag")
    start = record.get("start_index")
    count = record.get("n_files_written") or 0
    if prefix is None or tag is None or start is None:
        return []
    return [f"{prefix}_{tag}{i}.bin" for i in range(start, start + count)]


# ---------------------------------------------------------------------------
# Reading and writing the folder's metadata.json
# ---------------------------------------------------------------------------


def _load(path: str) -> dict | None:
    """Parse a metadata file, or None when it is absent or not JSON we wrote."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict) or "schema_version" not in doc:
        return None
    if not isinstance(doc.get("runs"), list):
        return None
    return doc


def read_runs(folder: str) -> list[dict]:
    """Return the run records a folder holds, newest last. Empty when none."""
    for name in (METADATA_FILENAME, FALLBACK_FILENAME):
        doc = _load(os.path.join(folder, name))
        if doc is not None:
            return list(doc["runs"])
    return []


def run_for_file(filepath: str) -> dict | None:
    """Return the run record describing a '.bin', or None when not recorded.

    Matches by name against each run's filename pattern and index range, so a
    file still resolves after the folder has been re-sorted — but not after it
    has been moved out, since the record stays with the folder.
    """
    folder, name = os.path.split(os.path.abspath(filepath))
    for record in reversed(read_runs(folder)):
        if name in file_names_for_run(record):
            return record
    return None


def upsert_run(folder: str, record: dict) -> str:
    """Merge one run record into the folder's 'metadata.json', atomically.

    Appends the record, or replaces the existing one carrying the same
    ``run_id`` — so a record written mid-run is updated in place at the end
    rather than duplicated. Written to a temporary file and moved over the
    target, so a kill mid-write cannot leave a half-written record.

    An existing ``metadata.json`` that this module did not write is never
    touched: the record goes to ``metadata_dapkel_rtp.json`` instead, and that
    path is what gets returned.

    Parameters
    ----------
    folder : str
        The run's output folder.
    record : dict
        From 'build_run_record'.

    Returns
    -------
    str
        Path actually written.

    Raises
    ------
    OSError
        Raised when the folder cannot be written to.
    """
    os.makedirs(folder, exist_ok=True)

    target = os.path.join(folder, METADATA_FILENAME)
    doc = _load(target)
    if doc is None and os.path.exists(target):
        # Something else owns that name. Do not overwrite it.
        target = os.path.join(folder, FALLBACK_FILENAME)
        doc = _load(target)

    if doc is None:
        doc = {"schema_version": SCHEMA_VERSION, "runs": []}
    # Keep a newer schema_version as found rather than downgrading it; a future
    # version of this module wrote it and knows more than this one does.
    doc["schema_version"] = max(
        SCHEMA_VERSION, int(doc.get("schema_version") or SCHEMA_VERSION)
    )

    runs = doc["runs"]
    for i, existing in enumerate(runs):
        if isinstance(existing, dict) and existing.get("run_id") == record.get(
            "run_id"
        ):
            runs[i] = record
            break
    else:
        runs.append(record)

    tmp = f"{target}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, target)
    return target
