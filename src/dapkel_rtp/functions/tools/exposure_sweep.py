"""Exposure sweep -- does the firmware act on the exposure we send it?

Diagnostic for the observation that 50, 100, 200 and 500 ns "acquisition
windows" all return the same number of photons in ORC. The host side has been
ruled out by inspection (see the notes at the bottom of this file), so what is
left to establish is what the *firmware* does with the value. This script
measures that, from two independent quantities per acquisition:

  1. ``frame_rate_cnt.txt`` -- Kelpie_v2.exe writes WireOut 0x21 there after
     every acquisition. It is a clock-tick count for the whole acquisition,
     i.e. a direct measurement of the frame period the firmware actually ran.
     If this does not move when the exposure register changes, the firmware
     is not acting on it at all and nothing downstream can.

  2. the decoded photon counts -- total, per-frame-per-pixel mean, and the
     per-pixel-per-frame maximum (the count field is 9 bits, so 511 is
     saturation, and 1 would mean one latched event per frame is all the
     readout can report).

Together they separate the three candidate explanations:

  * frame period does not move, counts do not move
        -> firmware ignores the exposure register in this range (their side).
  * frame period moves by exactly the exposure delta, counts do not move
        -> the register is applied to the frame period but the SPADs are not
           gated by it (they collect over the whole ~9 us frame), so a
           sub-microsecond change is a few percent of the live time and
           invisible. Also their side, but a different bug -- or just a
           documentation error on ours.
  * counts pinned at 1 per pixel per frame (or at 511)
        -> saturation, not a bug at all: every window is already long enough
           to register an event, so lengthening it cannot add counts.

Run from the repo root:

    python -m dapkel_rtp.functions.tools.exposure_sweep

Requires the camera connected and powered -- it programs the FPGA and runs
real acquisitions.
"""

import os
import subprocess
import sys

import numpy as np

from dapkel_rtp.functions.hitmap import (
    BYTES_PER_FRAME,
    MODE_COUNT,
    valid_frame_mask,
)
from dapkel_rtp.functions.unpack import unpack
from dapkel_rtp.gui.gui._paths import (
    functions_dir,
    params_camera_dir,
    programs_dir,
)

# =============================================================================
# Parameters
# =============================================================================

# Nominal seconds per exposure tick. This is the 200 MHz assumption the whole
# codebase makes; with a 10 MHz external reference it holds only if the FPGA
# PLL still synthesises 200 MHz from it. The sweep is specified in *ticks*
# precisely so the measurement does not depend on this constant being right --
# it is used for the printed microsecond columns only.
CLK_PERIOD = 5e-9

PROGRAM = "program_ORC.txt"
NFRAMES = 2000

# Exposure register values, in ticks. The first four are the settings under
# investigation (10 ticks = 50 ns at 5 ns/tick); the rest walk out past the
# ~9 us readout, which is where a firmware that adds the exposure to a fixed
# readout overhead must start showing an effect no matter what.
EXPOSURE_TICKS = [0, 10, 20, 40, 100, 400, 2_000, 10_000, 40_000]

OUTPUT_FOLDER = os.path.join(functions_dir(), "exposure_sweep")

_NBITS = 17 * (32 * 32) - 1
_CLK_SHIFT = 2400

# 9-bit count field -> this value means the per-frame counter railed.
_COUNT_FIELD_MAX = 511


# =============================================================================
# Hardware calls -- identical argument order to the GUI's worker.py
# =============================================================================


def program_fpga(program_file: str) -> None:
    """Load ``program_file`` into the FPGA. Run once before the sweep."""
    subprocess.run(
        [
            os.path.join(functions_dir(), "Kelpie_v2_pwr_mgt.exe"),
            str(_NBITS),
            program_file,
            program_file,
            program_file,
            program_file,
            str(_CLK_SHIFT),
        ],
        check=True,
        cwd=params_camera_dir(),
    )


def acquire(chip_config: int, exposure_ticks: int, nframes: int, name: str) -> str:
    """Run one acquisition and return the path of the '.bin' it wrote."""
    folder_arg = OUTPUT_FOLDER.rstrip(os.sep) + os.sep
    subprocess.run(
        [
            os.path.join(functions_dir(), "Kelpie_v2.exe"),
            str(chip_config),
            str(exposure_ticks),
            str(nframes),
            folder_arg,
            name,
        ],
        check=True,
        cwd=functions_dir(),
    )
    return os.path.join(OUTPUT_FOLDER, name + ".bin")


def read_frame_rate_cnt() -> int | None:
    """Return the tick count Kelpie_v2.exe wrote for the last acquisition.

    The exe reads WireOut 0x21 once the acquisition reports done and dumps it
    to ``frame_rate_cnt.txt`` in the output folder, overwriting the previous
    one -- so it must be read after every acquisition, before the next.
    """
    path = os.path.join(OUTPUT_FOLDER, "frame_rate_cnt.txt")
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


# =============================================================================
# Measurement
# =============================================================================


def measure(filepath: str, nframes: int) -> dict:
    """Reduce one acquisition to the numbers the diagnosis turns on."""
    read = min(nframes, os.path.getsize(filepath) // BYTES_PER_FRAME)
    if read < 1:
        return {"frames": 0}

    valid = valid_frame_mask(filepath, read)
    frames = int(valid.sum())
    if frames == 0:
        return {"frames": 0}

    _, counts = unpack(filepath, read, compute_time_series=False)
    counts = counts[:, :, valid]
    return {
        "frames": frames,
        "frames_read": read,
        "total": float(counts.sum()),
        # Counts per pixel per frame: the quantity that must be proportional
        # to the live time if the exposure gates the SPADs.
        "per_pix_frame": float(counts.mean()),
        "max": float(counts.max()),
        # Fraction of pixel-frames that registered nothing. Drops towards 0 as
        # the window saturates; if it is already ~0 at the shortest exposure,
        # every window is long enough and counts cannot grow.
        "empty_frac": float((counts == 0).mean()),
    }


def main() -> int:
    program_file = os.path.join(programs_dir(), PROGRAM)
    if not os.path.isfile(program_file):
        print(f"Program file not found: {program_file}")
        return 1
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # Same bits the GUI defaults to: chip_timing on, everything else off.
    # external_frame_trigger (bit 8) MUST stay 0 -- with it set the frame
    # period is dictated by the external pulses, not by the exposure register,
    # and the sweep would measure nothing.
    chip_config = 1 << 1

    print(f"Program        : {PROGRAM}")
    print(f"chip_config    : {chip_config}")
    print(f"Frames per acq : {NFRAMES}")
    print(f"Output         : {OUTPUT_FOLDER}")
    print(f"Tick assumption: {CLK_PERIOD * 1e9:g} ns  (for the µs columns only)")
    print()

    print(f"Programming FPGA with {PROGRAM} …")
    program_fpga(program_file)
    print()

    header = (
        f"{'exp[ticks]':>10} {'exp[µs]':>9} {'ticks/acq':>12} "
        f"{'ticks/frame':>12} {'frame[µs]':>10} {'frames':>7} "
        f"{'total':>12} {'cnt/pix/frm':>12} {'cnt/frm-tick':>13} "
        f"{'max':>5} {'empty':>7}"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for ticks in EXPOSURE_TICKS:
        name = f"sweep_exp{ticks}"
        acquire(chip_config, ticks, NFRAMES, name)
        cnt = read_frame_rate_cnt()
        m = measure(os.path.join(OUTPUT_FOLDER, name + ".bin"), NFRAMES)

        per_frame = cnt / NFRAMES if cnt else None
        row = {"ticks": ticks, "cnt": cnt, "per_frame": per_frame, **m}
        rows.append(row)

        if not m["frames"]:
            print(f"{ticks:>10} {ticks * CLK_PERIOD * 1e6:>9.3f} "
                  f"{'-' if cnt is None else cnt:>12} "
                  f"{'':>12} {'':>10} {'NO DATA':>7}")
            continue

        # Counts per pixel per tick of *measured* frame period. This is the
        # column the diagnosis turns on: if it is constant while the frame
        # period moves, the sensitive time is the whole frame.
        per_tick = m["per_pix_frame"] / per_frame if per_frame else None
        row["per_tick"] = per_tick

        print(
            f"{ticks:>10} {ticks * CLK_PERIOD * 1e6:>9.3f} "
            f"{'-' if cnt is None else cnt:>12} "
            f"{'-' if per_frame is None else f'{per_frame:.1f}':>12} "
            f"{'-' if per_frame is None else f'{per_frame * CLK_PERIOD * 1e6:.3f}':>10} "
            f"{m['frames']:>7} {m['total']:>12.0f} "
            f"{m['per_pix_frame']:>12.4f} "
            f"{'-' if per_tick is None else f'{per_tick * 1e5:.3f}e-5':>13} "
            f"{m['max']:>5.0f} {m['empty_frac']:>7.3f}"
        )

    print()
    _diagnose(rows)
    return 0


def _diagnose(rows: list[dict]) -> None:
    """Print which of the candidate explanations the numbers support."""
    live = [r for r in rows if r.get("frames")]
    if len(live) < 2:
        print("Not enough usable acquisitions to diagnose.")
        return

    print("Diagnosis")
    print("---------")

    # 1. Does the measured frame period respond to the register at all?
    periods = [r["per_frame"] for r in live if r["per_frame"]]
    if len(periods) >= 2:
        spread = max(periods) - min(periods)
        exp_spread = max(r["ticks"] for r in live) - min(r["ticks"] for r in live)
        if spread < 0.02 * max(periods):
            print(
                "* The measured frame period does not move across the whole "
                "sweep. The firmware is not acting on WireIn 0x04 at all -- "
                "the host writes it verbatim (verified in the exe), so this "
                "is on the firmware side. Take it to the designers with this "
                "table."
            )
        elif abs(spread - exp_spread) < 0.1 * max(exp_spread, 1):
            print(
                "* The measured frame period tracks the exposure register "
                f"one-for-one ({spread:.0f} ticks of period for "
                f"{exp_spread} ticks of exposure). The register IS applied, "
                "so a flat count at 50-500 ns is not the register being "
                "ignored -- see the next point."
            )
        else:
            print(
                f"* The frame period moves by {spread:.0f} ticks over "
                f"{exp_spread} ticks of exposure -- neither ignored nor "
                "one-for-one. Note the ratio: it is the real ticks-per-"
                "exposure-unit, and if it is not 1 the 5 ns/tick assumption "
                "in the GUI is wrong (relevant with the 10 MHz external "
                "reference)."
            )

    # 2. Is the count saturated, so no window length could change it?
    shortest = min(live, key=lambda r: r["ticks"])
    if shortest["max"] <= 1.0:
        print(
            "* Counts never exceed 1 per pixel per frame, so the readout "
            "reports at most one event per frame. Lengthening the window "
            f"then cannot add counts once it is long enough -- and at "
            f"{shortest['empty_frac'] * 100:.1f}% empty pixel-frames the "
            "shortest window already is. This is saturation, not a bug: to "
            "see the window length, attenuate until the empty fraction is "
            "well above 50%."
        )
    elif shortest["max"] >= _COUNT_FIELD_MAX:
        print(
            f"* The count field is railed at {_COUNT_FIELD_MAX} (9 bits) at "
            "the shortest exposure, so it cannot grow. Attenuate the source "
            "or shorten the frame before reading anything into the sweep."
        )

    # 3. What is the counts proportional to -- the exposure, or the whole
    #    frame? Constant counts per tick of measured frame period across a
    #    wide range of frame periods says the sensitive time IS the frame,
    #    and there is no gate to shorten.
    per_tick = [r["per_tick"] for r in live if r.get("per_tick")]
    if len(per_tick) >= 2 and len(periods) >= 2:
        mean = sum(per_tick) / len(per_tick)
        dev = max(abs(v - mean) for v in per_tick) / mean
        fold = max(periods) / min(periods)
        if dev < 0.1 and fold > 2:
            print(
                f"* Counts per pixel per frame-period tick is constant to "
                f"±{dev * 100:.1f}% across a {fold:.0f}x range of frame "
                "period -- the pixels are sensitive for the WHOLE frame, "
                "not for a programmable window inside it. The exposure "
                "register therefore only sets the frame length, and since "
                f"that has a floor of ~{min(periods):.0f} ticks "
                f"({min(periods) * CLK_PERIOD * 1e6:.2f} µs), every setting "
                "below the floor collects for exactly the same time. "
                f"Implied per-pixel rate: {mean / CLK_PERIOD / 1e3:.1f} kcps."
            )
        else:
            lo = min(live, key=lambda r: r["ticks"])
            hi = max(live, key=lambda r: r["ticks"])
            print(
                f"* Counts per pixel per frame went x"
                f"{hi['per_pix_frame'] / lo['per_pix_frame']:.3f} over the "
                f"sweep, per frame-period tick x{max(per_tick) / min(per_tick):.3f}. "
                "The latter varying means the live time is NOT simply the "
                "frame period -- compare against the exposure instead."
            )

    zero = next((r for r in live if r["ticks"] == 0), None)
    if zero and zero["total"] > 0:
        print(
            f"* Exposure 0 still returned {zero['total']:.0f} counts. There "
            "is a photon-sensitive interval the exposure register does not "
            "control; whatever it is, it is the baseline every short window "
            "sits on top of, and the GUI's 'rate = counts / exposure' is "
            "wrong by that baseline. Ask the designers what it is."
        )


# =============================================================================
# What has already been ruled out on the host side (no need to re-check)
# =============================================================================
#
# GUI / scripts: every call site computes
#     exposure_ticks = round(exp_us * 1e-6 / 5e-9)
# so 50/100/200/500 ns -> 10/20/40/100 ticks exactly. The spinboxes carry 3
# decimals of a microsecond, i.e. 1 ns of resolution, so nothing is rounded
# away either. Checked in tab_acquisition.py, tab_chain_acquisition.py,
# tab_live_view.py and helpers/kelpie_run.py -- all agree.
#
# Kelpie_v2.exe (disassembled): argv[2] -> atoi -> and the value goes
# straight into
#     okFrontPanel_SetWireInValue(dev, ep=0x04, value, mask=0xFFFFFFFF)
#     okFrontPanel_UpdateWireIns(dev)
# with no clamp, scale or truncation anywhere in between. The exe makes only
# four wire-in writes in total: ep 0x03 = chip_config, ep 0x04 = exposure,
# ep 0x06 = nframes, ep 0x07 = nframes * 512 - 8 (the DDR3 transfer size).
# It then fires TriggerIn 0x41 bit 0 to start, polls TriggerOut 0x62 bit 1
# for done, and reads WireOut 0x21 into frame_rate_cnt.txt.
#
# So the exposure the firmware receives is exactly the number of ticks the GUI
# displayed. Anything that goes wrong after that is behind WireIn 0x04.

if __name__ == "__main__":
    sys.exit(main())
