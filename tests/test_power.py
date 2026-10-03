import copy
import math

import pytest

from jds2800_mcp.api import API
from jds2800_mcp.cli import parser, run
from jds2800_mcp.power import Calibration, CalibrationError, PowerController
from jds2800_mcp.transport import DeviceError


def test_zero_dbm_voltage_and_channel_correction(calibration):
    first = calibration.plan(1, 1e6, 0)
    second = calibration.plan(2, 1e6, 0)
    assert first["amplitude_vpp"] == 1.265
    assert second["amplitude_vpp"] == 1.318
    assert abs(first["quantization_error_db"]) < 0.005


def test_log_frequency_interpolation(calibration):
    plan = calibration.plan(1, math.sqrt(1e6 * 10e6), 0)
    assert plan["amplitude_vpp"] == 1.333
    assert abs(plan["predicted_power_dbm"]) < 0.005


@pytest.mark.parametrize("channel", [1, 2])
def test_table_endpoints_roundtrip(calibration, channel):
    for curve in calibration.document["channels"][str(channel)]["curves"]:
        for point in curve["points"]:
            plan = calibration.plan(channel, curve["frequency_hz"], point["measured_dbm"])
            assert plan["amplitude_vpp"] == point["setting_vpp"]
            assert abs(plan["predicted_power_dbm"] - point["measured_dbm"]) < 1e-10


@pytest.mark.parametrize(
    "frequency,power",
    [(0, 0), (9e5, 0), (15000001, 0), (math.nan, 0), (1e6, math.inf), (1e6, -100), (1e6, 24)],
)
def test_out_of_range_power_never_writes(generator, calibration, frequency, power):
    with pytest.raises(CalibrationError):
        PowerController(generator, calibration).set_power(1, frequency, power, enabled=True)
    assert generator.io.writes == []


def test_wrong_device_never_writes(generator, calibration):
    generator.io.registers[1] = 123
    with pytest.raises(CalibrationError, match="serial"):
        PowerController(generator, calibration).set_power(1, 1e6, 0)
    assert generator.io.writes == []


def test_set_power_forces_sine_zero_offset_and_preserves_other_output(generator, calibration):
    generator.io.registers[21] = 3
    generator.io.registers[27] = 1100
    power = PowerController(generator, calibration)
    result = power.set_power(1, 1e6, 0, enabled=False)
    assert result["state"]["waveform"] == "SINE"
    assert result["state"]["offset_v"] == 0
    assert result["state"]["enabled"] is False
    assert result["state"]["amplitude_vpp"] == 1.265
    assert result["scope_verified_now"] is False
    assert generator.io.registers[20] == [0, 0]
    assert generator.io.registers[24] == [200000, 0]


def test_set_power_preserves_enable_state(generator, calibration):
    result = PowerController(generator, calibration).set_power(2, 5e6, -10)
    assert result["state"]["enabled"] is False
    assert generator.io.registers[20] == [1, 0]


def test_readback_failure_turns_channel_off(generator, calibration):
    generator.io.bad_amplitude = True
    with pytest.raises(DeviceError, match="Readback mismatch"):
        PowerController(generator, calibration).set_power(1, 1e6, 0)
    assert generator.io.registers[20] == [0, 0]


def test_preview_has_no_writes(generator, calibration):
    result = PowerController(generator, calibration).preview_power(1, 5e6, -10)
    assert result["requested_power_dbm"] == -10
    assert generator.io.writes == []


@pytest.mark.parametrize(
    "key,value",
    [("status", "incomplete"), ("load_ohms", 1000000), ("waveform", "SQUARE"), ("offset_v", 1)],
)
def test_incompatible_calibration_rejected(calibration_document, key, value):
    calibration_document[key] = value
    with pytest.raises(CalibrationError):
        Calibration(calibration_document)


def test_nonmonotonic_or_invalid_measurements_rejected(calibration_document):
    for key, value in (
        ("setting_vpp", 0.001),
        ("measured_dbm", math.nan),
        ("vrms_ac_v", 0),
        ("measured_dbm", 20),
    ):
        document = copy.deepcopy(calibration_document)
        document["channels"]["1"]["curves"][0]["points"][1][key] = value
        with pytest.raises(CalibrationError):
            Calibration(document)


def test_mismatched_amplitude_grids_rejected(calibration_document):
    calibration_document["channels"]["1"]["curves"][1]["points"].pop()
    with pytest.raises(CalibrationError, match="grid"):
        Calibration(calibration_document)


def test_missing_file_reports_actionable_error(monkeypatch):
    monkeypatch.setenv("JDS2800_CALIBRATION", "/missing/calibration.json")
    with pytest.raises(CalibrationError, match="Measure both channels"):
        Calibration.load()


def test_cli_power_preview_and_table(generator, calibration):
    api = API(generator, calibration)
    preview = run(
        api, parser().parse_args(["preview-power", "1", "--frequency-hz", "1000000", "--dbm", "0"])
    )
    assert preview["amplitude_vpp"] == 1.265
    assert generator.io.writes == []
    result = run(
        api,
        parser().parse_args(
            ["power", "2", "--frequency-hz", "1000000", "--dbm", "0", "--enabled", "on"]
        ),
    )
    assert result["state"]["enabled"] is True
    summary = run(api, parser().parse_args(["calibration", "--channel", "2"]))
    assert set(summary["channels"]) == {"2"}


def square_calibration(document):
    document = copy.deepcopy(document)
    document.update(waveform="SQUARE", duty_percent=50, power_metric="AC_RMS_INCLUDING_HARMONICS")
    for channel in document["channels"].values():
        for curve in channel["curves"]:
            for point in curve["points"]:
                point["vrms_ac_v"] *= math.sqrt(2)
                point["measured_dbm"] += 10 * math.log10(2)
    return Calibration(document)


def test_square_power_uses_its_table_and_sets_square(generator, calibration_document):
    calibration = square_calibration(calibration_document)
    power = PowerController(generator, calibration)
    result = power.set_power(1, 1e6, 0, enabled=True, waveform="SQUARE")
    assert result["state"]["waveform"] == "SQUARE"
    assert result["state"]["offset_v"] == 0
    assert result["state"]["duty_percent"] == 50
    assert result["state"]["enabled"] is True
    assert result["power_metric"] == "AC_RMS_INCLUDING_HARMONICS"
    assert result["state"]["amplitude_vpp"] == calibration.plan(1, 1e6, 0)["amplitude_vpp"]
    assert result["state"]["amplitude_vpp"] == 0.894


@pytest.mark.parametrize("waveform", ["SQUARE", "CMOS", "PULSE", None])
def test_sine_table_cannot_be_used_for_other_waveforms(generator, calibration, waveform):
    with pytest.raises(CalibrationError):
        PowerController(generator, calibration).set_power(1, 1e6, 0, waveform=waveform)
    assert generator.io.writes == []


def test_square_table_cannot_silently_replace_sine(generator, calibration_document):
    calibration = square_calibration(calibration_document)
    with pytest.raises(CalibrationError, match="Cannot use SQUARE"):
        PowerController(generator, calibration).set_power(1, 1e6, 0)
    assert generator.io.writes == []


def test_square_override_is_separate_from_sine(monkeypatch, tmp_path, calibration_document):
    import json

    sine_path = tmp_path / "sine.json"
    square_path = tmp_path / "square.json"
    sine_path.write_text(json.dumps(calibration_document))
    square_path.write_text(json.dumps(square_calibration(calibration_document).document))
    monkeypatch.setenv("JDS2800_CALIBRATION", str(sine_path))
    monkeypatch.setenv("JDS2800_SQUARE_CALIBRATION", str(square_path))
    assert Calibration.load().document["waveform"] == "SINE"
    assert Calibration.load("SQUARE").document["waveform"] == "SQUARE"
    monkeypatch.setenv("JDS2800_SQUARE_CALIBRATION", str(sine_path))
    with pytest.raises(CalibrationError, match="Cannot use SINE"):
        Calibration.load("SQUARE")


@pytest.mark.parametrize("key,value", [("duty_percent", 30), ("power_metric", "FUNDAMENTAL")])
def test_square_calibration_rejects_wrong_duty_or_power_metric(calibration_document, key, value):
    document = square_calibration(calibration_document).document
    document[key] = value
    with pytest.raises(CalibrationError):
        Calibration(document)


def test_square_cli_and_api(generator, calibration_document):
    api = API(generator, square_calibration(calibration_document))
    args = parser().parse_args(
        ["power", "2", "--frequency-hz", "1000000", "--dbm", "0", "--waveform", "SQUARE"]
    )
    assert run(api, args)["state"]["waveform"] == "SQUARE"
    assert api.call("get_calibration", {"waveform": "SQUARE"})["waveform"] == "SQUARE"
