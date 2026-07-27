"""Batch acquisition and analysis script for Kelpie v2 SPAD camera.

Equivalent to Kelpie_run.m — captures a large dataset, decodes timestamps
and photon counts, then computes timing histograms, DCR, and PDE.

NOTE: Kelpie_v2.ex_ and Kelpie_v2_pwr_mgt.ex_ must be renamed to .exe
      before running this script.
"""

import os
import subprocess
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# Parameters
# =============================================================================
CLK_PERIOD = 5e-9
# Exposure time, set directly: whatever value you set here is the actual
# exposure achieved. Readout takes the rest of the fixed ~9 us frame
# period: readout = 9 us - exposure. (Requires external_frame_trigger=0
# below -- that's a separate SMA hardware-sync feature.)
exp_time = 0e-6
exposure_time = round(exp_time / CLK_PERIOD)

nframes = 10_000  # frames per acquisition (up to ~1.1 million)
nacq = 10

chip_debug = 0
chip_timing = 1
clk_shift = 0
chip_artif_rdout = 0
single_shot_noise = 0
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
folder = os.path.join(SCRIPT_DIR, "test_DCR_python")
folder_exe = folder + os.sep   # exe does string concat, needs trailing backslash
filename = "data"
program_file = os.path.normpath(os.path.join(SCRIPT_DIR, "../../params/camera/programs", "program_S3C.txt"))

# Derive tag from program filename: "program_S0C.txt" → "S0C"
program_tag = os.path.splitext(os.path.basename(program_file))[0].replace(
    "program_", ""
)

os.makedirs(folder, exist_ok=True)

# =============================================================================
# Power management / FPGA initialisation
# =============================================================================
# subprocess.run(
#     [
#         os.path.join(SCRIPT_DIR, "Kelpie_v2_pwr_mgt.exe"),
#         str(nbits),
#         program_file,
#         program_file,
#         program_file,
#         program_file,
#         str(clk_shift),
#     ],
#     check=True,
#     cwd=SCRIPT_DIR,
# )

# =============================================================================
# Acquisition loop
# =============================================================================
t0 = time.perf_counter()
for i in range(nacq):
    filename_i = f"{filename}_{program_tag}{i + 1}"
    subprocess.run(
        [
            os.path.join(SCRIPT_DIR, "Kelpie_v2.exe"),
            str(chip_config),
            str(exposure_time),
            str(nframes),
            folder_exe,
            filename_i,
        ],
        check=True,
        cwd=SCRIPT_DIR,
    )
    print(f"Acquisition {i + 1}/{nacq}")
print(f"Acquisition done in {time.perf_counter() - t0:.1f} s")

# # =============================================================================
# # Decode timestamps and photon counts
# # =============================================================================
# photon_counts = np.zeros((32, 32, nframes, nacq))
# time_mat = np.zeros((32, 32, nframes, nacq))

# t0 = time.perf_counter()
# for i in range(nacq):
#     filename_i = f"{filename}_{program_tag}{i + 1}"
#     filepath = os.path.join(folder, filename_i + ".bin")
#     time_mat[..., i], photon_counts[..., i] = unpack_kelpie_binary_data(
#         filepath, nframes
#     )
#     print(f"Decoded {i + 1}/{nacq}")
# print(f"Decoding done in {time.perf_counter() - t0:.1f} s")

# # =============================================================================
# # Save / load
# # =============================================================================
# np.save("test_time_mat.npy", time_mat)
# # To reload:  time_mat = np.load("test_time_mat.npy")

# time_mat_jitter = (
#     time_mat  # use directly; no reload needed in the same session
# )

# # =============================================================================
# # Timing analysis
# # =============================================================================
# time_coarse_jitter = np.floor(time_mat_jitter / 8).astype(int) + 1
# time_fine_jitter = (time_mat_jitter % 8).astype(int)

# # --- Single-pixel timing histogram ---
# pixx, pixy = 12, 12  # pixel to inspect (0-indexed)
# bin_ax = np.arange(0, 1701)  # 0 to 1700

# fig, ax = plt.subplots()
# ax.hist(time_mat_jitter[pixx, pixy, :, 0].ravel(), bins=bin_ax)
# ax.set_xlabel("Time code [#]")
# ax.set_ylabel("Counts [#]")
# ax.set_title(f"Timing histogram — pixel ({pixx}, {pixy})")
# plt.tight_layout()
# plt.show()

# # --- Per-pixel histograms (all 32×32) ---
# bin_edges = np.arange(1, 331)  # edges → 329 bins
# histos = np.zeros((32, 32, len(bin_edges) - 1))
# for ii in range(32):
#     for jj in range(32):
#         histos[ii, jj, :], _ = np.histogram(
#             time_mat_jitter[ii, jj, :, 0], bins=bin_edges
#         )

# # Single-pixel log plot with circular shift
# pixx2, pixy2 = 11, 15
# fig, ax = plt.subplots()
# ax.semilogy(np.roll(histos[pixx2, pixy2, :], 100))
# ax.grid(True)
# ax.set_title(f"Timing histogram (log) — pixel ({pixx2}, {pixy2})")
# plt.tight_layout()
# plt.show()

# # --- Integrated photon count image ---
# img_int = histos.sum(axis=2)  # (32, 32)
# fig, ax = plt.subplots()
# im = ax.imshow(img_int, aspect="equal")
# plt.colorbar(im, ax=ax)
# ax.set_title("Integrated photon counts")
# plt.tight_layout()
# plt.show()

# # =============================================================================
# # Dark count rate (DCR)
# # =============================================================================
# exp_total_time = exp_time * nframes
# if exp_total_time > 0:
#     DCR = photon_counts.sum(axis=2) / exp_total_time  # (32, 32, nacq)
#     DCR_flat = np.sort(DCR[..., 0].ravel())

#     fig, ax = plt.subplots()
#     ax.semilogy(DCR_flat)
#     ax.set_xlabel("Pixel rank")
#     ax.set_ylabel("DCR [counts/s]")
#     ax.set_title("Dark count rate distribution")
#     plt.tight_layout()
#     plt.show()
# else:
#     print(
#         "exp_time = 0: skipping DCR/PDE calculations (set exp_time > 0 to enable)"
#     )
#     DCR = None

# # =============================================================================
# # Photon detection efficiency (PDE)
# # =============================================================================
# if exp_total_time > 0 and DCR is not None:
#     Area = (10.17e-6) ** 2  # SPAD area in m²
#     wavelength = 530  # nm
#     Hama_resp = (0.267 + 0.279) / 2  # Hamamatsu PD responsivity (A/W)
#     PD_cur = 0.480e-6  # photodiode current (A)

#     Pow = PD_cur / Hama_resp
#     Irradiance = Pow / 0.0001  # W/m² (aperture area = 1 cm²)
#     PowerSpad = Irradiance * Area
#     Nphoton = PowerSpad * wavelength / (1e9 * 6.626e-34 * 299_792_458)

#     NPhoton_Kelpie = (
#         photon_counts.sum(axis=2)[..., 0] / exp_total_time
#     )  # (32, 32)
#     PDE_pixel = (NPhoton_Kelpie - DCR[..., 0]) / Nphoton * 100

#     fig, ax = plt.subplots()
#     im = ax.imshow(PDE_pixel, aspect="equal")
#     plt.colorbar(im, ax=ax)
#     ax.set_title("Photon detection efficiency (%)")
#     plt.tight_layout()
#     plt.show()
