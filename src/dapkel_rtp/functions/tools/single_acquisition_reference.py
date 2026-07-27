"""Single Acquisition -- reference script (for sharing outside the codebase).

This is a standalone, minimal reproduction of exactly what the DAPKEL-RTP
GUI does for ONE single acquisition (the "Single Acquisition" tab, one
press of "Run Acquisition"). PyQt5, threading, and the GUI's error-recovery
machinery are stripped out on purpose -- what's left is just the hardware
protocol: which two executables get run, in what order, and with exactly
what command-line arguments.

Two steps, run in order:
  1. Power management (once): Kelpie_v2_pwr_mgt.exe loads a "program" file
     into the FPGA, selecting which SPAD readout channel/mode is active.
  2. Acquisition: Kelpie_v2.exe captures NFRAMES frames into one .bin file
     using that active channel/mode.

This file has no dependency on the rest of the dapkel_rtp package -- it can
be copied out and handed to someone who only needs to understand the
executable interface, not the application around it.
"""

import os
import subprocess

# =============================================================================
# 1. Paths -- point these at your own copy of the exes / program files.
#    In the app itself these are resolved by dapkel_rtp/gui/gui/_paths.py.
# =============================================================================

# Folder containing Kelpie_v2.exe and Kelpie_v2_pwr_mgt.exe.
EXE_DIR = r"C:\path\to\dapkel_rtp\functions\helpers"

# Folder containing the FPGA program_*.txt files (one per SPAD readout
# channel/mode -- see the catalogue below).
PROGRAMS_DIR = r"C:\path\to\dapkel_rtp\params\camera\programs"

# Folder containing bitfile/Kelpie_top.bit. Kelpie_v2_pwr_mgt.exe MUST be
# launched with this as its working directory: it resolves the bitfile via
# the relative path "./bitfile/Kelpie_top.bit".
PARAMS_CAMERA_DIR = r"C:\path\to\dapkel_rtp\params\camera"

# Where the acquired .bin file gets written.
OUTPUT_FOLDER = r"C:\path\to\output"
OUTPUT_FILENAME = "data"  # -> written as OUTPUT_FOLDER/data.bin

# =============================================================================
# 2. Program selection -- which SPAD readout channel/mode to activate.
#    Confirmed meanings:
#      S0C / S1C / S2C / S3C  -- one 32x32 SPAD quadrant each, photon
#                                 counting mode ("C"). The physical sensor
#                                 is 64x64, built from these 4 quadrants.
#      S0T / S1T / S2T / S3T  -- same 4 quadrants, timing mode ("T").
#      ORC / ORT              -- OR-tree combined readout: all 4 quadrants
#                                 OR'd together into one 32x32 grid (every
#                                 physical SPAD contributes, at reduced
#                                 spatial resolution), counting/timing resp.
#    Available but not independently verified here -- see program_*.txt in
#    PROGRAMS_DIR for the full list, ask the chip designer if exact
#    semantics matter for your use case:
#      ORS0S1 / ORS0S2 / ORS0S3, coincS0S1 / coincS0S2 / coincS0S3,
#      C2T / C3T / C4T
# =============================================================================

PROGRAM_FILE = os.path.join(PROGRAMS_DIR, "program_S3C.txt")

# =============================================================================
# 3. Chip configuration -- 7 independent bits packed into one integer,
#    passed to Kelpie_v2.exe as its first argument. Bit 3 is reserved/unused.
# =============================================================================

chip_debug = 0               # bit 0 -- enable debug readout mode
chip_timing = 1               # bit 1 -- 1 = external trigger timing mode
chip_artif_rdout = 0          # bit 2 -- artificial/synthetic readout (test mode)
# bit 3 reserved/unused
single_shot_noise = 0         # bit 4 -- 0 = single-shot, 1 = noise mode
memory_select0 = 0            # bit 5 -\
memory_select1 = 0            # bit 6 -/ together select the active on-chip memory bank
debug_last_row = 0            # bit 7 -- debug the last SPAD row only
external_frame_trigger = 0    # bit 8 -- 1 = wait for external SMA sync trigger instead (separate feature)

CHIP_CONFIG = (
    external_frame_trigger << 8
    | debug_last_row << 7
    | memory_select1 << 6
    | memory_select0 << 5
    | single_shot_noise << 4
    # bit 3 reserved/unused
    | chip_artif_rdout << 2
    | chip_timing << 1
    | chip_debug
)

# =============================================================================
# 4. Timing / frame count
# =============================================================================

CLK_PERIOD = 5e-9  # seconds per FPGA clock tick (200 MHz)

# Exposure time PER FRAME, set directly: whatever value you set here is
# the actual exposure achieved (e.g. 0.2 us -> 200 ns exposure). Readout
# takes the rest of the fixed ~9 us frame period: readout = 9 us -
# exposure. (Requires external_frame_trigger=0 above -- that's a separate
# SMA hardware-sync feature.)
EXPOSURE_TIME_US = 0.0
EXPOSURE_TIME_CLKS = round(EXPOSURE_TIME_US * 1e-6 / CLK_PERIOD)

# Frames captured into this ONE .bin file (up to ~1.1 million).
NFRAMES = 10_000

# FPGA shift-register bit count, used only by the power-management step.
# 17 config bits per SPAD x 32x32 SPADs, minus 1.
NBITS = 17 * (32 * 32) - 1  # 17407

# Clock-phase shift, used only by the power-management step. Unrelated to
# the per-chip bits above despite the similar name.
CLK_SHIFT = 2400


def run_power_management():
    """Load PROGRAM_FILE into the FPGA. Run once; re-run only if
    PROGRAM_FILE changes -- it does not need to precede every acquisition."""
    exe_path = os.path.join(EXE_DIR, "Kelpie_v2_pwr_mgt.exe")
    cmd = [
        exe_path,
        str(NBITS),
        PROGRAM_FILE,
        PROGRAM_FILE,
        PROGRAM_FILE,
        PROGRAM_FILE,  # same program file in all 4 slots -- see note below
        str(CLK_SHIFT),
    ]
    print("Running:", " ".join(cmd))
    # cwd=PARAMS_CAMERA_DIR is required: see the PARAMS_CAMERA_DIR comment.
    subprocess.run(cmd, check=True, cwd=PARAMS_CAMERA_DIR)
    # Note on the 4 identical PROGRAM_FILE args: Kelpie_v2_pwr_mgt.exe's
    # signature has 4 program-file slots. The app always fills all 4 with
    # the same file for the single/chain-acquisition modes it supports;
    # this is not something we've had a reason to vary.


def run_single_acquisition():
    """Capture NFRAMES frames into one .bin file using whichever program
    was most recently loaded by run_power_management()."""
    exe_path = os.path.join(EXE_DIR, "Kelpie_v2.exe")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    # The exe does raw string concatenation on folder+filename, so the
    # folder argument needs a trailing path separator.
    folder_arg = OUTPUT_FOLDER.rstrip(os.sep) + os.sep

    cmd = [
        exe_path,
        str(CHIP_CONFIG),
        str(EXPOSURE_TIME_CLKS),
        str(NFRAMES),
        folder_arg,
        OUTPUT_FILENAME,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=EXE_DIR)
    print(f"Wrote: {os.path.join(OUTPUT_FOLDER, OUTPUT_FILENAME + '.bin')}")


if __name__ == "__main__":
    run_power_management()
    run_single_acquisition()
