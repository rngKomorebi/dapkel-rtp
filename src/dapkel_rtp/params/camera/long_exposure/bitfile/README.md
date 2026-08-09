# long_exposure

Put the long-exposure bitstream here as `Kelpie_top.bit`.

Frame is shutter + 9 µs.

(This file only keeps the folder in git — `Kelpie_v2_pwr_mgt.exe` opens
`./bitfile/Kelpie_top.bit` relative to its working directory, so the app selects
a firmware by which folder it runs the exe from. See `gui/gui/_paths.py`.)
