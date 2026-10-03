import asyncio
import json
import math
from types import SimpleNamespace

import pytest

from jds2800_mcp.calibrate import collect, measure, save


def test_measure_clears_before_each_numeric_reading_and_records_vpp(monkeypatch):
    commands = []

    async def fake_call(client, name, arguments):
        assert name == "scpi"
        command = arguments["command"]
        commands.append(command)
        if command.endswith("*OPC?"):
            return "1"
        # 0.2 V AC RMS with a 0.1 V DC component; sine Vpp = sqrt(8)*Vrms.
        return f"{math.sqrt(0.05)};0.1;5000000;{math.sqrt(8) * 0.2}"

    monkeypatch.setattr("jds2800_mcp.calibrate.call", fake_call)
    result = asyncio.run(measure(object(), 3, 5e6, repeats=2))
    assert (
        commands
        == [
            ":MEAS:CLE ALL\n*OPC?",
            ":MEAS:ITEM? VRMS,CHAN3;:MEAS:ITEM? VAVG,CHAN3;"
            ":MEAS:ITEM? FREQuency,CHAN3;:MEAS:ITEM? VPP,CHAN3",
        ]
        * 2
    )
    assert result["vrms_ac_v"] == pytest.approx(0.2)
    assert result["measured_dbm"] == pytest.approx(10 * math.log10(0.8))
    assert result["vpp_sine_dbm"] == pytest.approx(result["measured_dbm"])
    assert result["repeatability_db"] == 0
    assert len(result["readings"]) == 2


@pytest.mark.parametrize(
    "reply",
    ["0.2;0;9.9E37;0.5", "0.2;0;1000000;0.5", "0.1;0.2;5000000;0.5", "0.2;0;5000000;0"],
)
def test_measure_rejects_unmeasurable_or_inconsistent_values(monkeypatch, reply):
    async def fake_call(client, name, arguments):
        return "1" if arguments["command"].endswith("*OPC?") else reply

    monkeypatch.setattr("jds2800_mcp.calibrate.call", fake_call)
    with pytest.raises(RuntimeError):
        asyncio.run(measure(object(), 1, 5e6, repeats=2))


def test_resume_rejects_different_grid_before_connecting(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text('{"load_ohms":50,"status":"incomplete","measurement_plan":{}}')
    args = SimpleNamespace(
        confirm_50ohm=True,
        frequencies=[1e6, 2e6],
        amplitudes=[0.2, 0.4],
        acquire_type="NORM",
        repeats=3,
        settle=0.6,
        scope_host="scope.example.test",
        resume=True,
        out=path,
    )
    with pytest.raises(ValueError, match="original measurement grid"):
        asyncio.run(collect(args))


def test_saved_measurements_exclude_connection_metadata(tmp_path):
    path = tmp_path / "measurements.json"
    document = {
        "scope_host": "scope.example.test",
        "scope_info": "IDN: RIGOL,DS1104Z,test-serial\nHost: scope.example.test:5555\nProbe: 1",
        "device": {"serial_number": 123456789, "port": "mock-serial"},
        "readings": [{"port": "mock-serial", "vpp_v": 0.64}],
    }
    save(path, document)
    saved = json.loads(path.read_text())
    assert saved == {
        "scope_info": "IDN: RIGOL,DS1104Z,test-serial\nProbe: 1",
        "device": {"serial_number": 123456789},
        "readings": [{"vpp_v": 0.64}],
    }
    assert document["device"]["port"] == "mock-serial"
