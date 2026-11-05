"""Firmware the user has added to this install, alongside the two that ship.

The app ships two bitstreams, ``short_exposure`` and ``long_exposure``. Any
other build -- an external-APD variant, a debug build from the FPGA designers --
used to mean copying it over one of those two by hand, after which the record
said ``short_exposure`` about a bitstream that was nothing of the kind.

Now a ``.bit`` can be *added*: it is copied into
'_paths.custom_firmware_dir' (``%LOCALAPPDATA%\\DAPKEL\\dapkel-rtp\\firmware``),
one folder per firmware, laid out the way Kelpie_v2_pwr_mgt.exe needs::

    <custom_firmware_dir>/<name>/bitfile/Kelpie_top.bit
    <custom_firmware_dir>/<name>/firmware.json

The exe opens './bitfile/Kelpie_top.bit' relative to its working directory, so
the folder is the cwd it runs from, exactly as for the shipped two. The copy
means the firmware outlives the file it was added from (a Downloads folder gets
cleaned), and the shipped bitstreams are never touched. The folder is per user
and outside the exe's own, so a newer exe finds the same firmware.

Nothing else remembers what was added: the folder *is* the list, so a restart
finds it again and deleting the folder forgets it.

**Firmware keys.** Every Firmware box stores a key: ``short_exposure`` or
``long_exposure`` for the shipped two, ``custom:<name>`` for an added one. The
key is what identifies the bitstream (the FPGA state compares keys, so switching
from the shipped short_exposure to a custom one reprograms). It is *not* what
the timing maths reads: an added firmware declares which of the two timing
models it follows, and 'timing_of' returns that. ``metadata.json`` keeps
``firmware_version`` as the timing model -- the vocabulary ``dapkel`` reads --
and names the bitstream in ``firmware_name`` beside it.

No Qt here, so it is testable without a display; the widgets that drive it are
in 'firmware_widgets'.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import NamedTuple

from ._paths import (
    BITFILE_NAME,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    FIRMWARE_VERSIONS,
    custom_firmware_dir,
    firmware_bitfile,
    resolve_pwr_mgt_cwd,
)

CUSTOM_PREFIX = "custom:"
MANIFEST_NAME = "firmware.json"

# A name becomes a folder name and a key, so keep it to what is safe as both.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Every Xilinx .bit starts with this 13-byte preamble (a 9-byte field of
# 0F F0 pairs, then the length of the next field). Not proof of a good
# bitstream, but a file without it is certainly not one.
BIT_PREAMBLE = bytes.fromhex("00090ff00ff00ff00ff0000001")

LEGACY_SOURCE = "legacy fallback (params/camera/bitfile)"

__all__ = [
    "CUSTOM_PREFIX",
    "CustomFirmware",
    "Bitstream",
    "is_custom",
    "valid_name",
    "looks_like_bitstream",
    "list_custom",
    "get_custom",
    "all_keys",
    "add_custom",
    "remove_custom",
    "timing_of",
    "label_of",
    "resolve_bitstream",
    "firmware_metadata",
]


@dataclass(frozen=True)
class CustomFirmware:
    """One added firmware, as found on disk."""

    name: str
    timing: str  # FIRMWARE_SHORT_EXPOSURE or FIRMWARE_LONG_EXPOSURE
    folder: str
    source_file: str | None = None
    added_utc: str | None = None
    sha256: str | None = None

    @property
    def key(self) -> str:
        return CUSTOM_PREFIX + self.name

    @property
    def bitfile(self) -> str:
        return os.path.join(self.folder, "bitfile", BITFILE_NAME)


class Bitstream(NamedTuple):
    """What Power Mgt will load for a firmware key."""

    cwd: str  # run Kelpie_v2_pwr_mgt.exe from here
    bitfile: str | None  # the .bit it will open, None if there is none
    source: str  # for metadata.json: where the .bit came from
    fell_back: bool  # a shipped firmware's .bit is missing; legacy used


# ---------------------------------------------------------------------------
# Names and keys
# ---------------------------------------------------------------------------


def is_custom(key: str | None) -> bool:
    return bool(key) and key.startswith(CUSTOM_PREFIX)


def valid_name(name: str) -> bool:
    """A name usable as a folder and a key: letters, digits, '.', '_', '-'."""
    return bool(_NAME_RE.match(name or "")) and name not in FIRMWARE_VERSIONS


def suggest_name(path: str) -> str:
    """A valid name from a file's stem, e.g. 'Kelpie_FW_external_APD'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:64]
    if not name or not name[0].isalnum():
        name = "custom_" + name if name else "custom"
    if name in FIRMWARE_VERSIONS:
        name = name + "_custom"
    return name


def looks_like_bitstream(path: str) -> bool:
    """True when the file starts like a Xilinx .bit."""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(BIT_PREAMBLE)) == BIT_PREAMBLE
    except OSError:
        return False


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def _read(folder: str) -> CustomFirmware | None:
    """The firmware in *folder*, or None when it is incomplete.

    A folder without a .bit, or whose manifest is missing or names no valid
    timing model, is skipped rather than guessed at: guessing the timing would
    write a wrong frame length into every run's record.
    """
    name = os.path.basename(folder)
    if not valid_name(name):
        return None
    if not os.path.isfile(os.path.join(folder, "bitfile", BITFILE_NAME)):
        return None
    try:
        with open(os.path.join(folder, MANIFEST_NAME), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    timing = manifest.get("timing")
    if timing not in FIRMWARE_VERSIONS:
        return None
    return CustomFirmware(
        name=name,
        timing=timing,
        folder=folder,
        source_file=manifest.get("source_file"),
        added_utc=manifest.get("added_utc"),
        sha256=manifest.get("sha256"),
    )


def list_custom() -> list[CustomFirmware]:
    """Every added firmware, sorted by name (case-insensitive)."""
    root = custom_firmware_dir()
    if not os.path.isdir(root):
        return []
    found = []
    for entry in sorted(os.listdir(root), key=str.lower):
        folder = os.path.join(root, entry)
        if os.path.isdir(folder):
            fw = _read(folder)
            if fw is not None:
                found.append(fw)
    return found


def get_custom(key: str) -> CustomFirmware | None:
    """The added firmware behind *key*, or None if it is not (or no longer) there."""
    if not is_custom(key):
        return None
    name = key[len(CUSTOM_PREFIX):]
    if not valid_name(name):
        return None
    return _read(os.path.join(custom_firmware_dir(), name))


def all_keys() -> list[str]:
    """Shipped firmware first, then the added ones."""
    return list(FIRMWARE_VERSIONS) + [fw.key for fw in list_custom()]


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_custom(
    source: str, name: str, timing: str, replace: bool = False
) -> CustomFirmware:
    """Copy *source* into the store as firmware *name*.

    Parameters
    ----------
    source : str
        The .bit to add. It is copied; the original can be moved or deleted
        afterwards.
    name : str
        Shown in the Firmware boxes and written to metadata.json. See
        'valid_name'.
    timing : str
        Which timing model the bitstream follows: 'short_exposure' (fixed
        9 µs frame) or 'long_exposure' (shutter + 9 µs).
    replace : bool
        Overwrite a firmware of the same name. Otherwise that raises.

    Raises
    ------
    ValueError
        Bad name or timing, or *source* is not a file.
    FileExistsError
        *name* is taken and *replace* is False.
    """
    if not valid_name(name):
        raise ValueError(
            f"{name!r} cannot be a firmware name: use letters, digits, '.', "
            "'_' and '-', start with a letter or digit, at most 64 characters, "
            "and not short_exposure or long_exposure."
        )
    if timing not in FIRMWARE_VERSIONS:
        raise ValueError(
            f"timing must be {FIRMWARE_SHORT_EXPOSURE!r} or "
            f"{FIRMWARE_LONG_EXPOSURE!r}, got {timing!r}"
        )
    if not os.path.isfile(source):
        raise ValueError(f"not a file: {source}")

    folder = os.path.join(custom_firmware_dir(), name)
    if os.path.exists(folder) and not replace:
        raise FileExistsError(f"a firmware called {name!r} already exists")

    bit_dir = os.path.join(folder, "bitfile")
    os.makedirs(bit_dir, exist_ok=True)
    target = os.path.join(bit_dir, BITFILE_NAME)
    shutil.copyfile(source, target)
    manifest = {
        "name": name,
        "timing": timing,
        "source_file": os.path.abspath(source),
        "added_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "sha256": _sha256(target),
    }
    with open(os.path.join(folder, MANIFEST_NAME), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    fw = _read(folder)
    assert fw is not None  # just written
    return fw


def remove_custom(key: str) -> None:
    """Delete an added firmware's folder -- the app's copy, not the original.

    Only ever a folder directly inside 'custom_firmware_dir', so a bad key
    cannot reach anything else.
    """
    fw = get_custom(key)
    if fw is None:
        return
    root = os.path.realpath(custom_firmware_dir())
    folder = os.path.realpath(fw.folder)
    if os.path.dirname(folder) != root:
        raise ValueError(f"refusing to delete outside {root}: {folder}")
    shutil.rmtree(folder)


# ---------------------------------------------------------------------------
# What a key means
# ---------------------------------------------------------------------------


def timing_of(key: str | None) -> str | None:
    """The timing model a firmware follows, or None for an unknown key."""
    if key in FIRMWARE_VERSIONS:
        return key
    fw = get_custom(key) if key else None
    return fw.timing if fw is not None else None


def label_of(key: str | None) -> str:
    """The firmware's name as shown to people -- also for a removed one."""
    if not key:
        return "none"
    if is_custom(key):
        return key[len(CUSTOM_PREFIX):]
    return key


def resolve_bitstream(key: str) -> Bitstream:
    """Where Power Mgt runs from for *key*, and which .bit that loads.

    A shipped firmware whose .bit is missing falls back to the legacy
    params/camera/bitfile/ (see '_paths.resolve_pwr_mgt_cwd'). An added one
    never does: falling back would load something other than what was asked
    for and record it as the added firmware.
    """
    if is_custom(key):
        fw = get_custom(key)
        if fw is None:
            folder = os.path.join(custom_firmware_dir(), label_of(key))
            return Bitstream(folder, None, f"custom: {label_of(key)}", False)
        source = f"custom: {fw.name}"
        if fw.source_file:
            source += f" (added from {fw.source_file})"
        return Bitstream(fw.folder, fw.bitfile, source, False)

    cwd, bitfile = resolve_pwr_mgt_cwd(key)
    if firmware_bitfile(key) is not None:
        return Bitstream(cwd, bitfile, key, False)
    return Bitstream(cwd, bitfile, LEGACY_SOURCE, True)


def firmware_metadata(key: str, loaded_key: str | None) -> dict:
    """The firmware half of a run's metadata settings.

    ``firmware_version`` is the timing model, the word ``dapkel`` understands;
    ``firmware_name`` says which bitstream -- the same word for a shipped
    firmware, the added name for a custom one.
    """
    bits = resolve_bitstream(key)
    return {
        "firmware_version": timing_of(key),
        "firmware_name": label_of(key),
        "firmware_bitfile": bits.bitfile,
        "firmware_bitfile_source": bits.source,
        "firmware_programmed_this_session": loaded_key == key,
    }
