"""Per-instrument, per-channel waveform power from measured 50-ohm calibration."""

import bisect
import json
import math
import os
from importlib.resources import files
from pathlib import Path

from .driver import channel_number, number

CALIBRATION_URI = "jds2800://calibration"
POWER_GUIDE_URI = "jds2800://power-guide"
SQUARE_CALIBRATION_URI = "jds2800://calibration/square"
SQUARE_POWER_GUIDE_URI = "jds2800://square-power-guide"
POWER_METRIC = "AC_RMS_INCLUDING_HARMONICS"


def calibrated_waveform(value):
    if not isinstance(value, str) or value.upper() not in ("SINE", "SQUARE"):
        raise CalibrationError("Calibrated power supports only SINE or SQUARE")
    return value.upper()


def get_power_guide(waveform="SINE"):
    waveform = calibrated_waveform(waveform)
    filename = (
        "JDS2800-power-calibration.md" if waveform == "SINE" else "JDS2800-square-calibration.md"
    )
    return files("jds2800_mcp").joinpath("docs", filename).read_text(encoding="utf-8")


class CalibrationError(ValueError):
    """Missing, incompatible, malformed, or out-of-range calibration."""


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def interpolate(x, xs, ys):
    index = max(0, min(bisect.bisect_right(xs, x) - 1, len(xs) - 2))
    weight = (x - xs[index]) / (xs[index + 1] - xs[index])
    return ys[index] + weight * (ys[index + 1] - ys[index])


class Calibration:
    def __init__(self, document):
        self.document = document
        try:
            self._validate()
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise CalibrationError(f"Invalid calibration: {exc}") from exc

    @classmethod
    def load(cls, waveform="SINE"):
        waveform = calibrated_waveform(waveform)
        variable = "JDS2800_CALIBRATION" if waveform == "SINE" else "JDS2800_SQUARE_CALIBRATION"
        override = os.environ.get(variable)
        filename = "calibration.json" if waveform == "SINE" else "square-calibration.json"
        path = Path(override) if override else files("jds2800_mcp").joinpath("data", filename)
        try:
            calibration = cls(json.loads(path.read_text(encoding="utf-8")))
            calibration.require_waveform(waveform)
            return calibration
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(
                f"No readable {waveform} power calibration. Measure both channels into 50 ohms; "
                f"select the resulting JSON with {variable}."
            ) from exc

    def _validate(self):
        doc = self.document
        for key in ("calibration_id", "created_at", "measurement_plane", "method"):
            if not isinstance(doc[key], str) or not doc[key].strip():
                raise ValueError(f"Missing calibration metadata: {key}")
        if (
            doc["schema_version"] != 1
            or doc["status"] != "measured"
            or doc["waveform"] not in ("SINE", "SQUARE")
            or doc["offset_v"] != 0
            or doc["load_ohms"] != 50
        ):
            raise ValueError(
                "Requires completed schema-1 SINE/SQUARE zero-offset/50-ohm measurements"
            )
        if doc["waveform"] == "SQUARE" and (
            doc.get("duty_percent") != 50 or doc.get("power_metric") != POWER_METRIC
        ):
            raise ValueError(
                "Square calibration requires 50% duty and explicit AC RMS power metric"
            )
        if (
            type(doc["device"]["serial_number"]) is not int
            or doc["device"]["serial_number"] < 0
            or doc["device"]["device_type"] != 15
        ):
            raise ValueError("Requires a 15 MHz device with an integer serial number")
        for channel in ("1", "2"):
            curves = doc["channels"][channel]["curves"]
            if len(curves) < 2:
                raise ValueError("Each channel needs at least two frequency curves")
            frequencies = [curve["frequency_hz"] for curve in curves]
            if not all(finite(f) and 0 < f <= 15e6 for f in frequencies) or frequencies != sorted(
                set(frequencies)
            ):
                raise ValueError("Frequency curves must be unique, ascending, and <=15 MHz")
            grid = None
            for curve in curves:
                points = curve["points"]
                amplitudes = [point["setting_vpp"] for point in points]
                powers = [point["measured_dbm"] for point in points]
                if (
                    len(points) < 2
                    or not all(finite(a) and 0.002 <= a <= 20 for a in amplitudes)
                    or amplitudes != sorted(set(amplitudes))
                    or not all(finite(p) for p in powers)
                    or powers != sorted(set(powers))
                ):
                    raise ValueError(
                        "Amplitude and measured power must be finite and strictly ascending"
                    )
                if grid is not None and amplitudes != grid:
                    raise ValueError("Frequency curves must share an amplitude grid")
                grid = amplitudes
                for point in points:
                    rms = point["vrms_ac_v"]
                    if (
                        not finite(rms)
                        or rms <= 0
                        or abs(10 * math.log10(rms * rms / 50 / 0.001) - point["measured_dbm"])
                        > 0.001
                    ):
                        raise ValueError("Power must agree with the measured AC RMS voltage")

    def require_device(self, info):
        expected = self.document["device"]
        if any(info[key] != expected[key] for key in ("device_type", "serial_number")):
            raise CalibrationError(
                f"Calibration is for model {expected['device_type']}, serial "
                f"{expected['serial_number']}; connected generator is serial {info['serial_number']}"
            )

    def require_waveform(self, waveform):
        if self.document["waveform"] != waveform:
            raise CalibrationError(
                f"Cannot use {self.document['waveform']} calibration for {waveform} output"
            )

    def summary(self, channel=None, include_points=False):
        if channel is not None:
            channel_number(channel)
        doc = self.document
        result = {
            key: doc[key]
            for key in (
                "calibration_id",
                "created_at",
                "device",
                "load_ohms",
                "waveform",
                "offset_v",
                "measurement_plane",
                "method",
            )
        }
        result["channels"] = {}
        result["guide_uri"] = (
            POWER_GUIDE_URI if doc["waveform"] == "SINE" else SQUARE_POWER_GUIDE_URI
        )
        result["power_metric"] = POWER_METRIC
        result["duty_percent"] = 50
        result["scope_analog_bandwidth_hz"] = doc.get("scope_analog_bandwidth_hz")
        result["limitations"] = (
            f"Scope-referenced AC RMS power of {doc['waveform']} into physical 50-ohm loads. "
            "Includes harmonics within the scope bandwidth and excludes DC. "
            "Includes measured cable loss; not a traceable absolute RF power calibration "
            "or a measurement of fundamental power alone."
        )
        if "verification" in doc:
            result["verification"] = doc["verification"]
        for name in (str(channel),) if channel else ("1", "2"):
            curves = doc["channels"][name]["curves"]
            result["channels"][name] = {
                "frequencies_hz": [curve["frequency_hz"] for curve in curves],
                "power_range_dbm_across_all_frequencies": [
                    max(curve["points"][0]["measured_dbm"] for curve in curves),
                    min(curve["points"][-1]["measured_dbm"] for curve in curves),
                ],
                "points": sum(len(curve["points"]) for curve in curves),
            }
            if include_points:
                result["channels"][name]["curves"] = curves
        return result

    def plan(self, channel, frequency_hz, power_dbm):
        channel_number(channel)
        curves = self.document["channels"][str(channel)]["curves"]
        frequencies = [curve["frequency_hz"] for curve in curves]
        if not finite(frequency_hz) or not frequencies[0] <= frequency_hz <= frequencies[-1]:
            raise CalibrationError(
                f"Frequency is outside calibration: {frequencies[0]:g}..{frequencies[-1]:g} Hz"
            )
        if not finite(power_dbm):
            raise CalibrationError("power_dbm must be finite")
        index = max(0, min(bisect.bisect_right(frequencies, frequency_hz) - 1, len(curves) - 2))
        left, right = curves[index : index + 2]
        weight = math.log(frequency_hz / left["frequency_hz"]) / math.log(
            right["frequency_hz"] / left["frequency_hz"]
        )
        amplitudes = [point["setting_vpp"] for point in left["points"]]
        powers = [
            lo["measured_dbm"] + weight * (hi["measured_dbm"] - lo["measured_dbm"])
            for lo, hi in zip(left["points"], right["points"], strict=True)
        ]
        if not powers[0] <= power_dbm <= powers[-1]:
            raise CalibrationError(
                f"Power is outside channel {channel} calibration at {frequency_hz:g} Hz: "
                f"{powers[0]:.3f}..{powers[-1]:.3f} dBm"
            )
        log_amplitudes = [math.log10(a) for a in amplitudes]
        voltage = round(10 ** interpolate(power_dbm, powers, log_amplitudes), 3)
        predicted = interpolate(math.log10(voltage), log_amplitudes, powers)
        return {
            "channel": channel,
            "frequency_hz": frequency_hz,
            "requested_power_dbm": power_dbm,
            "amplitude_vpp": voltage,
            "predicted_power_dbm": predicted,
            "quantization_error_db": predicted - power_dbm,
            "calibrated_power_range_dbm": [powers[0], powers[-1]],
            "frequency_bracket_hz": [left["frequency_hz"], right["frequency_hz"]],
            "load_ohms": 50,
            "waveform": self.document["waveform"],
            "duty_percent": 50,
            "power_metric": POWER_METRIC,
            "scope_analog_bandwidth_hz": self.document.get("scope_analog_bandwidth_hz"),
            "offset_v": 0,
            "calibration_id": self.document["calibration_id"],
            "measurement_plane": self.document["measurement_plane"],
        }


class PowerController:
    def __init__(self, generator, calibration=None):
        self.generator = generator
        self.calibration = calibration

    def _calibration(self, waveform="SINE"):
        waveform = calibrated_waveform(waveform)
        calibration = self.calibration or Calibration.load(waveform)
        calibration.require_waveform(waveform)
        return calibration

    def get_calibration(self, channel=None, include_points=False, waveform="SINE"):
        """Read metadata/table without connecting to the generator."""
        return self._calibration(waveform).summary(channel, include_points)

    def _plan(self, calibration, channel, frequency_hz, power_dbm):
        calibration.require_device(self.generator.info())
        plan = calibration.plan(channel, frequency_hz, power_dbm)
        number("frequency_hz", frequency_hz, 0, self.generator._model_limit())
        return plan

    def preview_power(self, channel, frequency_hz, power_dbm, waveform="SINE"):
        calibration = self._calibration(waveform)
        with self.generator.io.session():
            return self._plan(calibration, channel, frequency_hz, power_dbm)

    def set_power(self, channel, frequency_hz, power_dbm, enabled=None, waveform="SINE"):
        calibration = self._calibration(waveform)
        with self.generator.io.session():
            plan = self._plan(calibration, channel, frequency_hz, power_dbm)
            state = self.generator.configure(
                channel,
                waveform=plan["waveform"],
                frequency_hz=frequency_hz,
                amplitude_vpp=plan["amplitude_vpp"],
                offset_v=0,
                duty_percent=50,
                enabled=enabled,
            )
            return plan | {"state": state, "scope_verified_now": False}
