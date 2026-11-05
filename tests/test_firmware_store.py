"""Custom firmware: added, listed after a restart, resolved, recorded, removed.

Every test points the store at a temporary folder, so nothing here touches the
real params/camera/ or the shipped bitstreams.
"""

import json
import os

import pytest

from dapkel_rtp.gui.gui import firmware_store as store
from dapkel_rtp.gui.gui._paths import (
    BITFILE_NAME,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
)

# What every Xilinx .bit starts with, then some filler.
FAKE_BIT = store.BIT_PREAMBLE + b"\x00\x3aKelpie_top;COMPRESS=TRUE" + bytes(64)


@pytest.fixture
def root(monkeypatch, tmp_path):
    folder = tmp_path / "firmware"
    monkeypatch.setattr(store, "custom_firmware_dir", lambda: str(folder))
    return folder


@pytest.fixture
def bitfile(tmp_path):
    path = tmp_path / "downloads" / "Kelpie_FW_external_APD.bit"
    path.parent.mkdir()
    path.write_bytes(FAKE_BIT)
    return path


def test_nothing_added_lists_only_the_shipped_two(root):
    assert store.list_custom() == []
    assert store.all_keys() == [FIRMWARE_SHORT_EXPOSURE, FIRMWARE_LONG_EXPOSURE]


def test_added_firmware_is_a_copy_laid_out_for_pwr_mgt(root, bitfile):
    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)

    assert fw.key == "custom:external_APD"
    assert fw.bitfile == str(root / "external_APD" / "bitfile" / BITFILE_NAME)
    assert open(fw.bitfile, "rb").read() == FAKE_BIT
    # The original can go; the copy stays.
    os.remove(bitfile)
    assert store.get_custom(fw.key) == fw


def test_added_firmware_survives_a_restart(root, bitfile):
    store.add_custom(str(bitfile), "external_APD", FIRMWARE_LONG_EXPOSURE)

    # A restart has nothing but the folder to go on.
    (fw,) = store.list_custom()
    assert fw.name == "external_APD"
    assert fw.timing == FIRMWARE_LONG_EXPOSURE
    assert fw.source_file == str(bitfile)
    assert fw.sha256 and len(fw.sha256) == 64
    assert store.all_keys()[-1] == "custom:external_APD"


def test_key_names_the_bitstream_timing_names_the_model(root, bitfile):
    store.add_custom(str(bitfile), "external_APD", FIRMWARE_LONG_EXPOSURE)

    assert store.timing_of("custom:external_APD") == FIRMWARE_LONG_EXPOSURE
    assert store.label_of("custom:external_APD") == "external_APD"
    assert store.timing_of(FIRMWARE_SHORT_EXPOSURE) == FIRMWARE_SHORT_EXPOSURE
    assert store.timing_of("custom:gone") is None
    assert store.label_of("custom:gone") == "gone"


def test_resolve_runs_pwr_mgt_from_the_custom_folder(root, bitfile):
    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)

    bits = store.resolve_bitstream(fw.key)

    assert bits.cwd == fw.folder
    assert bits.bitfile == fw.bitfile
    assert bits.source.startswith("custom: external_APD")
    assert not bits.fell_back


def test_missing_custom_never_falls_back_to_the_legacy_bitstream(root):
    bits = store.resolve_bitstream("custom:gone")

    assert bits.bitfile is None
    assert not bits.fell_back


def test_metadata_keeps_dapkels_vocabulary(root, bitfile):
    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_LONG_EXPOSURE)

    meta = store.firmware_metadata(fw.key, loaded_key=fw.key)

    assert meta["firmware_version"] == FIRMWARE_LONG_EXPOSURE
    assert meta["firmware_name"] == "external_APD"
    assert meta["firmware_bitfile"] == fw.bitfile
    assert meta["firmware_programmed_this_session"] is True
    # The shipped short_exposure is a different bitstream with the same timing.
    assert (
        store.firmware_metadata(fw.key, FIRMWARE_LONG_EXPOSURE)[
            "firmware_programmed_this_session"
        ]
        is False
    )


def test_name_taken_needs_replace(root, bitfile):
    store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)

    with pytest.raises(FileExistsError):
        store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)

    fw = store.add_custom(
        str(bitfile), "external_APD", FIRMWARE_LONG_EXPOSURE, replace=True
    )
    assert fw.timing == FIRMWARE_LONG_EXPOSURE


@pytest.mark.parametrize(
    "name",
    ["", "../escape", "a b", "short_exposure", "long_exposure", "_leading", "x" * 65],
)
def test_bad_names_are_refused(root, bitfile, name):
    with pytest.raises(ValueError):
        store.add_custom(str(bitfile), name, FIRMWARE_SHORT_EXPOSURE)
    assert not root.exists() or list(root.iterdir()) == []


def test_bad_timing_is_refused(root, bitfile):
    with pytest.raises(ValueError, match="timing"):
        store.add_custom(str(bitfile), "external_APD", "medium_exposure")


def test_suggested_name_is_valid():
    assert store.suggest_name("C:/x/Kelpie_FW_external_APD.bit") == (
        "Kelpie_FW_external_APD"
    )
    for odd in ("C:/x/my firmware (v2).bit", "C:/x/__.bit", "C:/x/long_exposure.bit"):
        assert store.valid_name(store.suggest_name(odd))


def test_folder_with_a_bad_manifest_is_skipped_not_guessed(root, bitfile):
    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)
    manifest = os.path.join(fw.folder, store.MANIFEST_NAME)
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump({"timing": "unknown"}, fh)

    assert store.list_custom() == []


def test_bitstream_check(tmp_path, bitfile):
    assert store.looks_like_bitstream(str(bitfile))
    text = tmp_path / "notes.bit"
    text.write_text("not a bitstream")
    assert not store.looks_like_bitstream(str(text))


def test_remove_deletes_the_copy_only(root, bitfile):
    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)

    store.remove_custom(fw.key)

    assert store.list_custom() == []
    assert not os.path.exists(fw.folder)
    assert bitfile.exists()


# --- the Firmware box ---


@pytest.fixture(scope="session")
def qapp():
    # Session-wide: a QApplication that is garbage-collected mid-run takes the
    # module-level QObjects (FIRMWARE_LIST, FPGA) with it, and later tests
    # then find them deleted.
    QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_combo_lists_added_firmware_and_keeps_selection(qapp, root, bitfile):
    app = qapp
    from dapkel_rtp.gui.gui.firmware_widgets import FIRMWARE_LIST, FirmwareCombo

    combo = FirmwareCombo()
    other = FirmwareCombo(compact=True)
    seen = []
    other.firmwareChanged.connect(seen.append)
    other.select_key(FIRMWARE_LONG_EXPOSURE)
    seen.clear()

    fw = store.add_custom(str(bitfile), "external_APD", FIRMWARE_SHORT_EXPOSURE)
    FIRMWARE_LIST.changed.emit()
    app.processEvents()

    for box in (combo, other):
        keys = [box.itemData(i) for i in range(box.count())]
        assert fw.key in keys
    # Another tab adding a firmware is not a firmware change here.
    assert other.key() == FIRMWARE_LONG_EXPOSURE
    assert seen == []

    combo.select_key(fw.key)
    assert combo.key() == fw.key
    assert combo.currentData() == fw.key
