import json
import math
from contextlib import contextmanager

import pytest

from jds2800_mcp.driver import Generator
from jds2800_mcp.power import Calibration


class MemoryTransport:
    def __init__(self):
        self.port = "memory"
        self.registers = {
            0: 15,
            1: 123456789,
            20: [1, 0],
            21: 0,
            22: 0,
            23: [100000, 0],
            24: [200000, 0],
            25: 2000,
            26: 1000,
            27: 1000,
            28: 1000,
            29: 500,
            30: 500,
            31: 0,
            33: 0,
        }
        self.writes = []
        self.bad_amplitude = False

    @contextmanager
    def session(self):
        yield self

    def read_register(self, register, arbitrary=False):
        if self.bad_amplitude and register == 25 and self.writes:
            return 123
        return self.registers[register]

    def write_register(self, register, value, arbitrary=False):
        self.writes.append((register, value))
        values = [int(v) for v in str(value).split(",")]
        self.registers[register] = values if len(values) > 1 else values[0]
        if register == 33:
            self.registers[33] = {0: 0, 1: 16, 2: 32, 4: 64, 5: 72, 6: 80, 7: 88, 8: 96, 9: 104}[
                values[0]
            ]


@pytest.fixture
def generator():
    return Generator(transport=MemoryTransport())


@pytest.fixture
def calibration_document():
    document = {
        "schema_version": 1,
        "status": "measured",
        "calibration_id": "synthetic-test-only",
        "created_at": "2026-10-03",
        "device": {"device_type": 15, "serial_number": 123456789},
        "waveform": "SINE",
        "offset_v": 0,
        "load_ohms": 50,
        "measurement_plane": "synthetic test fixture",
        "method": "synthetic test fixture",
        "channels": {},
    }
    for channel, adjustment in ((1, 1), (2, 0.96)):
        curves = []
        for frequency, gain in ((1e6, 0.5), (10e6, 0.45), (15e6, 0.4)):
            points = []
            for amplitude in (0.04, 0.2, 1.0, 5.0):
                rms = amplitude * gain * adjustment / (2 * math.sqrt(2))
                points.append(
                    {
                        "setting_vpp": amplitude,
                        "vrms_ac_v": rms,
                        "measured_dbm": 10 * math.log10(rms**2 / 50 / 0.001),
                    }
                )
            curves.append({"frequency_hz": frequency, "points": points})
        document["channels"][str(channel)] = {
            "scope_channel": 1 if channel == 1 else 3,
            "curves": curves,
        }
    return document


@pytest.fixture
def calibration(calibration_document):
    return Calibration(calibration_document)


@pytest.fixture
def calibration_file(calibration_document, tmp_path, monkeypatch):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration_document))
    monkeypatch.setenv("JDS2800_CALIBRATION", str(path))
    return path
