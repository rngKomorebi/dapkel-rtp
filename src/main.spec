# -*- mode: python ; coding: utf-8 -*-

import os

# The icon Windows itself reads: the exe in Explorer, the desktop
# shortcut, the Alt-Tab entry. Separate from the PNGs in 'datas' below,
# which are what Qt draws once the application is running.
ICON = os.path.join(SPECPATH, 'dapkel_rtp', 'resources', 'dapkel-rtp.ico')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # The four vendor binaries the app actually runs, listed one by one
        # rather than by bundling the whole 'helpers' folder. That folder is
        # also the default output path, so globbing it swept every acquisition
        # sitting there into the release -- 'live/live.bin' alone is 16 MB of
        # stale preview data. No measurement file belongs in the exe: add
        # runtime dependencies here explicitly instead of widening this back to
        # the directory.
        # The rendered icon sizes Qt is handed at runtime. PyInstaller
        # cannot see them: they are read by name through
        # importlib.resources, never imported.
        ('dapkel_rtp/resources/*.png', 'dapkel_rtp/resources'),
        ('dapkel_rtp/functions/helpers/Kelpie_v2.exe', 'dapkel_rtp/functions/helpers'),
        ('dapkel_rtp/functions/helpers/Kelpie_v2_pwr_mgt.exe', 'dapkel_rtp/functions/helpers'),
        ('dapkel_rtp/functions/helpers/okFrontPanel.dll', 'dapkel_rtp/functions/helpers'),
        ('dapkel_rtp/functions/helpers/okimpl_fpoip.dll', 'dapkel_rtp/functions/helpers'),
        ('dapkel_rtp/params/camera/programs', 'dapkel_rtp/params/camera/programs'),
        # Legacy single-bitfile folder, still the fallback when a firmware
        # version has no bitstream of its own placed yet.
        ('dapkel_rtp/params/camera/bitfile', 'dapkel_rtp/params/camera/bitfile'),
        # One folder per firmware version: Kelpie_v2_pwr_mgt.exe takes no
        # bitstream argument and opens './bitfile/Kelpie_top.bit' relative to
        # its working directory, so the app selects a version by the directory
        # it launches the exe from. Both must ship.
        (
            'dapkel_rtp/params/camera/short_exposure',
            'dapkel_rtp/params/camera/short_exposure',
        ),
        (
            'dapkel_rtp/params/camera/long_exposure',
            'dapkel_rtp/params/camera/long_exposure',
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DAPKEL-RTP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    # Stamped into the executable, so the download carries the icon in
    # Explorer and on the desktop before it is ever run.
    icon=ICON,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
