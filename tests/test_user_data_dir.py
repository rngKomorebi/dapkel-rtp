"""Masks and custom firmware live in the user's folder, not beside the exe.

The old places were a 'masks' folder beside the exe (frozen) and
src/dapkel_rtp/params/masks/ (source). Masks saved there are copied across
once, without touching the originals or anything already in the new folder.
"""

import os
import sys

import pytest

from dapkel_rtp.gui.gui import _paths


@pytest.fixture
def profile(monkeypatch, tmp_path):
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return local / "DAPKEL" / "dapkel-rtp"


@pytest.fixture
def old_masks(monkeypatch, tmp_path):
    old = tmp_path / "old_masks"
    old.mkdir()
    monkeypatch.setattr(_paths, "legacy_masks_dirs", lambda: [str(old)])
    return old


def test_folders_are_in_the_profile(profile, old_masks):
    assert _paths.user_data_dir() == str(profile)
    assert _paths.masks_dir() == str(profile / "masks")
    assert _paths.custom_firmware_dir() == str(profile / "firmware")


def test_frozen_exe_writes_nothing_beside_itself(monkeypatch, profile, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(desktop / "DAPKEL-RTP.exe"))

    assert _paths.masks_dir() == str(profile / "masks")
    assert _paths.custom_firmware_dir() == str(profile / "firmware")
    assert list(desktop.iterdir()) == []


def test_frozen_legacy_masks_were_beside_the_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DAPKEL-RTP.exe"))

    assert _paths.legacy_masks_dirs() == [str(tmp_path / "masks")]


def test_old_masks_are_copied_once_and_kept(profile, old_masks):
    (old_masks / "D0_M0.json").write_text('{"old": 1}', encoding="utf-8")
    (old_masks / "notes.txt").write_text("not a mask", encoding="utf-8")

    folder = _paths.masks_dir()

    assert (profile / "masks" / "D0_M0.json").read_text(encoding="utf-8") == (
        '{"old": 1}'
    )
    assert not (profile / "masks" / "notes.txt").exists()
    assert (old_masks / "D0_M0.json").exists()  # originals left in place

    # Once only: a mask deleted from the new folder does not come back.
    os.remove(os.path.join(folder, "D0_M0.json"))
    _paths.masks_dir()
    assert not (profile / "masks" / "D0_M0.json").exists()


def test_migration_never_overwrites_a_newer_mask(profile, old_masks):
    (old_masks / "D0_M0.json").write_text('{"old": 1}', encoding="utf-8")
    new = profile / "masks"
    new.mkdir(parents=True)
    (new / "D0_M0.json").write_text('{"new": 1}', encoding="utf-8")

    _paths.masks_dir()

    assert (new / "D0_M0.json").read_text(encoding="utf-8") == '{"new": 1}'


def test_no_old_folder_is_fine(profile, monkeypatch, tmp_path):
    monkeypatch.setattr(
        _paths, "legacy_masks_dirs", lambda: [str(tmp_path / "missing")]
    )

    assert os.path.isdir(_paths.masks_dir())
