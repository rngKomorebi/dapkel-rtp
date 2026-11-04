import pytest

from dapkel_rtp.functions.timing import (
    CLK_PERIOD,
    FIRMWARE_LONG_EXPOSURE,
    FIRMWARE_SHORT_EXPOSURE,
    FRAME_READOUT_S,
    open_shutter_time,
    resolve_frame_acq_time,
)


def test_open_shutter_time_is_register_times_clock():
    assert open_shutter_time(0) == 0.0
    assert open_shutter_time(200) == pytest.approx(200 * CLK_PERIOD)
    assert open_shutter_time(200) == pytest.approx(1e-6)


def test_short_exposure_frame_is_fixed():
    for shutter in (0.0, 50e-9, 1e-6):
        frame, source = resolve_frame_acq_time(FIRMWARE_SHORT_EXPOSURE, shutter)
        assert frame == FRAME_READOUT_S
        assert source.startswith("short_exposure")


def test_long_exposure_frame_adds_readout():
    # Kelpie_run.m: exp_time 0 -> 9 us, 1e-6 -> 10 us, 2e-6 -> 11 us.
    for shutter, expected in [(0.0, 9e-6), (1e-6, 10e-6), (2e-6, 11e-6)]:
        frame, source = resolve_frame_acq_time(FIRMWARE_LONG_EXPOSURE, shutter)
        assert frame == pytest.approx(expected)
        assert source.startswith("long_exposure")


def test_unknown_firmware_raises():
    with pytest.raises(ValueError, match="firmware_version"):
        resolve_frame_acq_time("medium_exposure", 1e-6)
