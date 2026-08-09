"""How long a Kelpie frame takes, and how long its shutter is open.

The rtp counterpart of ``dapkel.core.timing``, and deliberately the only place
in this package that answers the question — the frame length used to be derived
in three different ways (a counter file, the exposure register, a hardcoded
9 µs), which is how the app came to disagree with itself and with ``dapkel``.

Two quantities describe the timing, and they describe both firmware versions
with no nulls and no mode-dependent meaning:

    * 'open_shutter_time' — how long the shutter is open within one frame.
      Always the exposure register times 'CLK_PERIOD', in *both* versions.

    * 'frame_acq_time' — how long one frame takes. A fixed
      ``FRAME_READOUT_S`` (9 µs) under ``'short_exposure'``, where the shutter
      opens inside it and readout takes the rest;
      ``open_shutter_time + FRAME_READOUT_S`` under ``'long_exposure'``, where
      the firmware appends the readout to the shutter.

So the register always means the same thing and the firmware decides only
whether the frame is fixed or stretches with it.

Not measured from the hardware
------------------------------
There is no readback for this. ``Kelpie_v2.exe`` writes one firmware counter to
``frame_rate_cnt.txt``, and it is not usable as a frame period: across the
group's drive it holds 11 distinct values, it is overwritten by every
acquisition so only the last survives, and it does not track the exposure
register coherently — a clean 50/100/200/500 ns sweep read 9.700, 9.710, 9.700
and 9.770 µs per frame, which is not monotonic. One live-view folder's value
implies ~8 300 frames for a file holding ~500. Nothing here reads it.

What is stated instead is what the firmware was told and what the firmware
does with it, which ``Kelpie_run.m`` states directly (``exp_time = 0 -> 9 us``,
``1e-6 -> 10 us``, ``2e-6 -> 11 us``) and which the group's data is consistent
with at ~9.7 µs per frame.

This file can also be imported as a module and contains the following
functions:

    * resolve_frame_acq_time - frame length from firmware and shutter time.

    * open_shutter_time - shutter-open seconds from the register value.
"""

from __future__ import annotations

# 200 MHz clock -> 5 ns per exposure-register tick.
CLK_PERIOD = 5e-9

# The readout the firmware appends to every frame, whatever the shutter does.
FRAME_READOUT_S = 9e-6

# Named as in dapkel.core.timing.resolve_cycle_time. Do not introduce a third
# vocabulary for the same two modes.
FIRMWARE_SHORT_EXPOSURE = "short_exposure"
FIRMWARE_LONG_EXPOSURE = "long_exposure"
FIRMWARE_VERSIONS = (FIRMWARE_SHORT_EXPOSURE, FIRMWARE_LONG_EXPOSURE)

__all__ = [
    "CLK_PERIOD",
    "FRAME_READOUT_S",
    "FIRMWARE_SHORT_EXPOSURE",
    "FIRMWARE_LONG_EXPOSURE",
    "FIRMWARE_VERSIONS",
    "open_shutter_time",
    "resolve_frame_acq_time",
]


def open_shutter_time(clks: int) -> float:
    """Return the shutter-open seconds a register value asks for.

    Nominal, not measured: 'functions.tools.exposure_sweep' found that register
    0 still returns counts, so there is a photon-sensitive baseline the register
    does not control and the true window may be larger. Unresolved.
    """
    return int(clks) * CLK_PERIOD


def resolve_frame_acq_time(
    firmware_version: str, open_shutter_time_s: float
) -> tuple[float, str]:
    """Return how long one frame takes, and a sentence saying why.

    Parameters
    ----------
    firmware_version : str
        'short_exposure' (the frame is a fixed 9 µs, the shutter opens inside
        it) or 'long_exposure' (the firmware adds 9 µs of readout to the
        shutter time).
    open_shutter_time_s : float
        Shutter-open time within one frame, in seconds — the exposure register
        times 'CLK_PERIOD', in both firmware versions.

    Returns
    -------
    tuple[float, str]
        Frame length in seconds, and a human-readable source string.

    Raises
    ------
    ValueError
        Raised on an unknown ``firmware_version``.
    """
    shutter = float(open_shutter_time_s)
    if firmware_version == FIRMWARE_SHORT_EXPOSURE:
        return (
            FRAME_READOUT_S,
            f"short_exposure: fixed {FRAME_READOUT_S * 1e6:.0f} µs frame, "
            f"{shutter * 1e9:.0f} ns shutter inside it",
        )
    if firmware_version == FIRMWARE_LONG_EXPOSURE:
        total = shutter + FRAME_READOUT_S
        return (
            total,
            f"long_exposure: {shutter * 1e6:.3f} µs shutter + "
            f"{FRAME_READOUT_S * 1e6:.0f} µs readout = {total * 1e6:.3f} µs frame",
        )
    raise ValueError(
        "firmware_version must be "
        f"{FIRMWARE_SHORT_EXPOSURE!r} or {FIRMWARE_LONG_EXPOSURE!r}, "
        f"got {firmware_version!r}"
    )
