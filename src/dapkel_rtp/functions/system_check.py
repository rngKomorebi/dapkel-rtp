"""What the PC must provide for the helper exes to run, and how they fail without it.

The GUI runs anywhere Qt does, but every acquisition goes through
``Kelpie_v2.exe`` / ``Kelpie_v2_pwr_mgt.exe``, and those two depend on things
the app cannot ship:

    * The **Microsoft Visual C++ 2015-2022 x64 runtime** -- both exes and
      ``okFrontPanel.dll`` import ``MSVCP140.dll``, ``VCRUNTIME140.dll`` and
      ``VCRUNTIME140_1.dll``. On a PC without it the exe never starts, and all
      the app sees is an exit code. 'explain_exit_code' turns that code into
      the sentence the operator needs.

    * The **Opal Kelly FrontPanel USB driver**, for ``okFrontPanel.dll`` to
      find the board over WinUSB. Without it the exe starts and reports no
      device -- an ordinary failure, not one this module can tell apart.

    * **ANSI-only arguments.** Both exes take ``argv`` as narrow strings
      (``_configure_narrow_argv``), so Windows converts every argument to the
      PC's ANSI code page before the exe sees it. A character the code page
      lacks arrives as '?', and the exe writes to, or reads from, a path that
      does not exist. 'unpassable_argument' finds such an argument before the
      exe is started. Czech diacritics are fine on a Czech-locale PC; Cyrillic
      or CJK in a folder or user name is not.

This file can also be imported as a module and contains the following
functions:

    * explain_exit_code - what a helper's Windows exit status means, if known.

    * missing_vc_runtime - the Visual C++ runtime DLLs absent from System32.

    * unpassable_argument - the first argument the exe cannot receive intact.
"""

from __future__ import annotations

import os
import sys

__all__ = [
    "VC_RUNTIME_DLLS",
    "VC_REDIST_URL",
    "explain_exit_code",
    "missing_vc_runtime",
    "unpassable_argument",
]

# Imported by Kelpie_v2.exe, Kelpie_v2_pwr_mgt.exe and okFrontPanel.dll.
VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

# NTSTATUS codes a process exits with when the loader gives up before main().
_STATUS_DLL_NOT_FOUND = 0xC0000135
_STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139
_STATUS_INVALID_IMAGE_FORMAT = 0xC000007B


def missing_vc_runtime(system_dir: str | None = None) -> list[str]:
    """Return the Visual C++ runtime DLLs missing from System32.

    That is where the redistributable installs them. A DLL found nowhere else
    on the search path is what makes the exe fail to start, so this is the
    first thing to check after a 'STATUS_DLL_NOT_FOUND'. Always empty off
    Windows, where the exes cannot run in any case.

    Parameters
    ----------
    system_dir : str | None, optional
        Folder to look in. The default is ``%SystemRoot%\\System32``.

    Returns
    -------
    list[str]
        File names from 'VC_RUNTIME_DLLS' that are not there.
    """
    if system_dir is None:
        if sys.platform != "win32":
            return []
        root = os.environ.get("SystemRoot", r"C:\Windows")
        system_dir = os.path.join(root, "System32")
    return [
        name
        for name in VC_RUNTIME_DLLS
        if not os.path.isfile(os.path.join(system_dir, name))
    ]


def explain_exit_code(
    returncode: int, system_dir: str | None = None
) -> str | None:
    """Say what a helper exe's exit code means when Windows, not the exe, set it.

    Parameters
    ----------
    returncode : int
        'subprocess' return code. Windows reports NTSTATUS values unsigned;
        a signed one is accepted too.
    system_dir : str | None, optional
        Passed to 'missing_vc_runtime'.

    Returns
    -------
    str | None
        A message naming the fix, or None when the code is the exe's own --
        including every ordinary failure such as no board connected. A
        non-None result means the exe never ran, so retrying cannot help.
    """
    code = int(returncode) & 0xFFFFFFFF
    redist = (
        "Install the Microsoft Visual C++ 2015-2022 Redistributable (x64) "
        f"from {VC_REDIST_URL} and restart the app."
    )
    if code == _STATUS_DLL_NOT_FOUND:
        missing = missing_vc_runtime(system_dir)
        if missing:
            return (
                "The helper exe could not start: Windows has no "
                f"{', '.join(missing)}. {redist}"
            )
        return (
            "The helper exe could not start: Windows could not find a DLL it "
            "needs. The Visual C++ runtime is present, so check that "
            "okFrontPanel.dll sits beside the exe and that the Opal Kelly "
            "FrontPanel USB driver is installed."
        )
    if code == _STATUS_ENTRYPOINT_NOT_FOUND:
        return (
            "The helper exe could not start: a DLL it loaded is older than "
            f"the one it was built against. {redist}"
        )
    if code == _STATUS_INVALID_IMAGE_FORMAT:
        return (
            "The helper exe could not start: a DLL it loaded is damaged or "
            f"32-bit, and the exe is 64-bit. {redist}"
        )
    return None


def unpassable_argument(
    args: list[str], encoding: str | None = None
) -> str | None:
    """Return the first argument a narrow-argv exe would receive mangled.

    Parameters
    ----------
    args : list[str]
        The arguments, without the exe path itself (Windows starts the exe
        through the wide API, so its own path is not affected).
    encoding : str | None, optional
        Code page to check against. The default is the PC's ANSI code page
        ('mbcs'), which is what the C runtime converts ``argv`` to. Off
        Windows there is none, and every argument passes.

    Returns
    -------
    str | None
        The offending argument, or None when all of them survive.
    """
    if encoding is None:
        if sys.platform != "win32":
            return None
        encoding = "mbcs"
    for arg in args:
        try:
            # 'mbcs' with 'strict' refuses best-fit substitutes too, so a
            # character Windows would quietly turn into a lookalike fails here.
            str(arg).encode(encoding)
        except UnicodeEncodeError:
            return str(arg)
    return None
