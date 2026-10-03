import math

import pytest

from jds2800_mcp.driver import waveform_id
from jds2800_mcp.transport import DeviceError


@pytest.mark.parametrize(
    "arguments",
    [
        {"frequency_hz": 16e6},
        {"frequency_hz": math.nan},
        {"amplitude_vpp": math.inf},
        {"amplitude_vpp": -1},
        {"offset_v": 3},
        {"duty_percent": 100},
        {"waveform": -1},
        {"waveform": 100},
        {"enabled": 1},
        {"waveform": "PULSE", "frequency_hz": 7e6},
        {"waveform": "ARBITRARY01", "frequency_hz": 7e6},
        {"waveform": "ARBITRARY60", "frequency_hz": 7e6},
        {"waveform": 130, "frequency_hz": 7e6},
        {"amplitude_vpp": 0.1, "offset_v": 0.3},
        {"amplitude_vpp": 20, "offset_v": 1},
        {"waveform": "SQUARE", "frequency_hz": 12e6, "amplitude_vpp": 6},
    ],
)
def test_invalid_parameters_do_not_write(generator, arguments):
    with pytest.raises(ValueError):
        generator.configure(1, **arguments)
    assert generator.io.writes == []


def test_configuration_gates_output_and_preserves_other_channel(generator):
    result = generator.configure(1, waveform="TRIANGLE", frequency_hz=1234.56, offset_v=1)
    assert generator.io.writes[0] == (20, "0,0")
    assert generator.io.writes[-1] == (20, "1,0")
    assert result["frequency_hz"] == 1234.56
    assert result["enabled"] is True
    assert generator.state(2)["channels"][0]["frequency_hz"] == 2000


@pytest.mark.parametrize("waveform", ["ARBITRARY01", "ARBITRARY60"])
def test_arbitrary_frequency_boundary_is_supported(generator, waveform):
    result = generator.configure(1, waveform=waveform, frequency_hz=6e6)
    assert result["frequency_hz"] == 6e6
    assert result["waveform"] == waveform


def test_arbitrary_sweep_limit_rejected_before_mode_or_output_changes(generator):
    generator.io.registers[21] = 101
    with pytest.raises(ValueError, match="frequency_hz"):
        generator.sweep(1, 1000, 7e6, 1)
    assert generator.io.writes == []


def test_does_not_enable_previously_off_output(generator):
    result = generator.configure(2, waveform="PULSE", duty_percent=30)
    assert result["enabled"] is False
    assert generator.io.registers[20] == [1, 0]


def test_readback_mismatch_requests_output_off(generator):
    generator.io.bad_amplitude = True
    with pytest.raises(DeviceError, match="Readback mismatch"):
        generator.configure(1, amplitude_vpp=1.5)
    assert generator.io.registers[20] == [0, 0]


def test_negative_phase_regression(generator):
    assert generator.phase(-90) == {"phase_deg": 270}
    assert generator.io.registers[31] == 2700
    assert generator.phase(360) == {"phase_deg": 0}


def test_fractional_hz_not_rounded_to_zero(generator):
    assert generator.configure(1, frequency_hz=1e-8)["frequency_hz"] == 1e-8
    assert generator.io.registers[23] == [1, 4]


def test_single_output_change_preserves_other(generator):
    assert generator.outputs(ch2=True) == {"ch1": True, "ch2": True}
    assert generator.outputs(ch1=False) == {"ch1": False, "ch2": True}


def test_busy_mode_rejected_before_writing(generator):
    generator.io.registers[33] = 80  # SWEEP_CH1 readback mode encoding
    with pytest.raises(ValueError, match="requires wave mode"):
        generator.configure(1, frequency_hz=100)
    assert generator.io.writes == []


def test_waveform_ids_reject_negative_python_indexes():
    for value in (-1, -100, 17, 100, 161, True):
        with pytest.raises(ValueError):
            waveform_id(value)
    assert waveform_id("ARBITRARY60") == 160


def test_arbitrary_validation_prevents_storage_write(generator):
    with pytest.raises(ValueError):
        generator.upload_arbitrary(1, [0] * 2047)
    with pytest.raises(ValueError):
        generator.upload_arbitrary(1, [4096] * 2048)
    assert generator.io.writes == []


def test_sweep_enters_mode_and_does_not_start_or_enable_outputs(generator):
    result = generator.sweep(2, 1000, 2000, 1)
    assert result == {
        "channel": 2,
        "start_hz": 1000,
        "end_hz": 2000,
        "time_s": 1,
        "direction": "RISE",
        "scale": "LINEAR",
        "started": False,
    }
    assert generator.state()["mode"] == "SWEEP_CH2"
    assert generator.io.registers[20] == [1, 0]
    assert generator.io.registers[32] == [0, 0, 0, 0]


def test_enable_only_configuration_regression(generator):
    assert generator.configure(2, enabled=True)["enabled"] is True
    assert all(register == 20 for register, _ in generator.io.writes)


def test_square_duty_request_explains_hardware_behavior(generator):
    with pytest.raises(ValueError, match="use PULSE"):
        generator.configure(1, waveform="SQUARE", duty_percent=30)
    assert generator.io.writes == []
