import sys

import pytest

from dapkel_rtp.functions.system_check import (
    VC_RUNTIME_DLLS,
    explain_exit_code,
    missing_vc_runtime,
    unpassable_argument,
)

DLL_NOT_FOUND = 0xC0000135  # what Windows reports when MSVCP140.dll is absent


def test_missing_vc_runtime(tmp_path):
    assert missing_vc_runtime(str(tmp_path)) == list(VC_RUNTIME_DLLS)
    for name in VC_RUNTIME_DLLS:
        (tmp_path / name).write_bytes(b"")
    assert missing_vc_runtime(str(tmp_path)) == []


def test_dll_not_found_names_the_redistributable(tmp_path):
    (tmp_path / "vcruntime140.dll").write_bytes(b"")

    msg = explain_exit_code(DLL_NOT_FOUND, system_dir=str(tmp_path))

    assert "msvcp140.dll" in msg
    assert "vcruntime140_1.dll" in msg
    assert "vcruntime140.dll," not in msg  # present, so not blamed
    assert "Visual C++" in msg


def test_dll_not_found_with_runtime_present_points_at_driver(tmp_path):
    for name in VC_RUNTIME_DLLS:
        (tmp_path / name).write_bytes(b"")
    msg = explain_exit_code(DLL_NOT_FOUND, system_dir=str(tmp_path))
    assert "Opal Kelly" in msg


def test_signed_exit_codes_are_recognised(tmp_path):
    signed = DLL_NOT_FOUND - (1 << 32)  # -1073741515
    assert explain_exit_code(signed, system_dir=str(tmp_path)) is not None


@pytest.mark.parametrize("code", [0, 1, 2, 255, -1])
def test_exe_own_exit_codes_are_left_alone(code):
    assert explain_exit_code(code) is None


@pytest.mark.parametrize("code", [0xC0000139, 0xC000007B])
def test_other_loader_failures(code):
    assert "Visual C++" in explain_exit_code(code)


def test_unpassable_argument_against_a_code_page():
    ok = ["17407", r"C:\Users\lab\data" + "\\", "data_ORT1"]
    assert unpassable_argument(ok, encoding="cp1252") is None

    cyrillic = r"C:\Users\Сергей\data" + "\\"
    assert unpassable_argument([*ok, cyrillic], encoding="cp1252") == cyrillic
    # Czech diacritics: fine in the Central European code page, not in Western.
    czech = r"D:\měření" + "\\"
    assert unpassable_argument([czech], encoding="cp1250") is None
    assert unpassable_argument([czech], encoding="cp1252") == czech


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has an ANSI code page")
def test_unpassable_argument_passes_everything_off_windows():
    assert unpassable_argument([r"/home/Сергей/data/"]) is None


@pytest.mark.skipif(sys.platform != "win32", reason="needs the 'mbcs' codec")
def test_unpassable_argument_ascii_always_passes_on_windows():
    assert unpassable_argument(["17407", r"C:\data" + "\\", "data_ORT1"]) is None
