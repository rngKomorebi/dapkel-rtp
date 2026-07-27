"""Live imaging script for Kelpie v2 SPAD camera.

Equivalent to liveimaging.m — calls the acquisition EXE in a loop and
displays a live grayscale image of photon counts after each acquisition.

NOTE: Kelpie_v2.ex_ and Kelpie_v2_pwr_mgt.ex_ must be renamed to .exe
      before running this script.
"""

import os
import subprocess
import sys

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Interactive window — locate via installed package
    import dapkel_rtp as _pkg

    SCRIPT_DIR = os.path.join(
        os.path.dirname(_pkg.__file__), "functions", "tools"
    )

# Kelpie_v2.exe / Kelpie_v2_pwr_mgt.exe live in the sibling "helpers" folder,
# not alongside this script.
HELPERS_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "helpers")

BITFILE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "../../params/camera"))

try:
    from dapkel_rtp.functions.unpack import unpack_kelpie_binary_data
except ImportError:
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)

# =============================================================================
# Parameters
# =============================================================================
CLK_PERIOD = 5e-9  # seconds per clock tick (200 MHz)
# Exposure time, set directly: whatever value you set here is the actual
# exposure achieved. Readout takes the rest of the fixed ~9 us frame
# period: readout = 9 us - exposure. (Requires external_frame_trigger=0
# below -- that's a separate SMA hardware-sync feature.)
exp_time = 20e-6  # exposure time in seconds
exposure_time = round(exp_time / CLK_PERIOD)

nframes = 800  # frames captured per acquisition (passed to EXE)
nacq = 1000  # number of acquisition loops

# Chip configuration bits
chip_debug = 0
chip_timing = 1
clk_shift = 2400
chip_artif_rdout = 0
single_shot_noise = 0  # 0 = single-shot, 1 = noise
memory_select0 = 0
memory_select1 = 0
debug_last_row = 0
external_frame_trigger = 0  # 1 = wait for external SMA sync trigger instead (separate feature)

chip_config = (
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

nbits = 17 * (32 * 32) - 1
folder = os.path.join(SCRIPT_DIR, "test")
filename = "data"
program_file = os.path.normpath(
    os.path.join(SCRIPT_DIR, "../../params/camera/programs", "program_ORC.txt")
)

os.makedirs(folder, exist_ok=True)

# =============================================================================
# Power management / FPGA initialisation  (runs once)
# =============================================================================
subprocess.run(
    [
        os.path.join(HELPERS_DIR, "Kelpie_v2_pwr_mgt.exe"),
        str(nbits),
        program_file,
        program_file,
        program_file,
        program_file,
        str(clk_shift),
    ],
    check=True,
    cwd=BITFILE_DIR,
)

# =============================================================================
# Live acquisition loop
# =============================================================================
# plt.ion()
# fig, ax = plt.subplots(figsize=(5, 5))
# im = ax.imshow(np.zeros((32, 32)), cmap="gray", aspect="equal", vmin=0, vmax=1)
# cbar = fig.colorbar(im, ax=ax)
# ax.set_title("Kelpie v2 — live photon counts")
# plt.tight_layout()
# plt.show()

# for i in range(nacq):
#     filepath = os.path.join(folder, filename + ".bin")

#     # Capture nframes into the binary file
#     subprocess.run(
#         [
#             os.path.join(HELPERS_DIR, "Kelpie_v2.exe"),
#             str(chip_config),
#             str(exposure_time),
#             str(nframes),
#             folder,
#             filename,
#         ],
#         check=True,
#         cwd=HELPERS_DIR,
#     )

#     # Read only the first frame for the live preview (same as MATLAB: kelpie_data_ddr3(path, 1), now unpack_kelpie_binary_data)
#     time_mat, photon_counts = unpack_kelpie_binary_data(filepath, nframes=1)
#     img = np.fliplr(photon_counts[:, :, 0])

#     im.set_data(img)
#     im.set_clim(img.min(), img.max())
#     fig.canvas.draw()
#     plt.pause(0.5)

#     print(f"Acquisition {i + 1}/{nacq}")

# plt.ioff()
# plt.show()
