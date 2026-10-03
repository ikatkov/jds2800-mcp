"""Validated operations and readback around the existing Python library."""

import math

from .transport import DeviceError, Settings, Transport
from .vendor.legacy import jds6600

WAVEFORMS = (
    "SINE",
    "SQUARE",
    "PULSE",
    "TRIANGLE",
    "PARTIALSINE",
    "CMOS",
    "DC",
    "HALF-WAVE",
    "FULL-WAVE",
    "POS-LADDER",
    "NEG-LADDER",
    "NOISE",
    "EXP-RIZE",
    "EXP-DECAY",
    "MULTI-TONE",
    "SINC",
    "LORENZ",
)
MODES = (
    "WAVE_CH1",
    "WAVE_CH2",
    "MEASURE",
    "COUNTER",
    "SWEEP_CH1",
    "SWEEP_CH2",
    "PULSE",
    "BURST",
    "SYSTEM",
)


def number(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and in [{low}, {high}]")
    return float(value)


def channel_number(channel):
    if type(channel) is not int or channel not in (1, 2):
        raise ValueError("channel must be 1 or 2")
    return channel


def waveform_id(waveform):
    if type(waveform) is int:
        if 0 <= waveform <= 16 or 101 <= waveform <= 160:
            return waveform
    elif isinstance(waveform, str):
        name = waveform.upper()
        if name in WAVEFORMS:
            return WAVEFORMS.index(name)
        if name.startswith("ARBITRARY") and name[9:].isdigit():
            slot = int(name[9:])
            if 1 <= slot <= 60:
                return slot + 100
    raise ValueError("Unknown waveform; use waveforms to list names and IDs")


def waveform_name(value):
    if 0 <= value <= 16:
        return WAVEFORMS[value]
    if 101 <= value <= 160:
        return f"ARBITRARY{value - 100:02d}"
    return f"UNKNOWN_{value}"


class Library(jds6600):
    def __init__(self, io):
        # Bypass legacy's class-level serial handle.
        self.io = io

    def _jds6600__getdata(self, reg, n=1, a=0):
        values = [self.io.read_register(reg + i, arbitrary=bool(a)) for i in range(n)]
        return values[0] if n == 1 else values

    def _jds6600__sendwritecmd(self, reg, val, a=0):
        self.io.write_register(reg, val, arbitrary=bool(a))


class Generator:
    def __init__(self, settings=None, transport=None):
        self.io = transport or Transport(settings or Settings.from_env())
        self.lib = Library(self.io)

    def _model_limit(self):
        value = self.lib.getinfo_devicetype()
        if value not in (15, 30, 40, 50, 60):
            raise DeviceError(f"Unknown device type {value}; cannot determine frequency limits")
        return value * 1e6

    def info(self):
        with self.io.session():
            limit = self._model_limit()
            return {
                "device_type": int(limit / 1e6),
                "serial_number": self.lib.getinfo_serialnumber(),
                "port": self.io.port,
                "baudrate": 115200,
                "max_sine_hz": limit,
                "backend": "on1arf Python library with bounded serial transport",
            }

    def _channel_state(self, channel):
        value = self.io.read_register(20)
        if not isinstance(value, list) or len(value) != 2 or any(v not in (0, 1) for v in value):
            raise DeviceError(f"Invalid channel output reply: {value}")
        waveform = self.io.read_register(20 + channel)
        return {
            "channel": channel,
            "enabled": bool(value[channel - 1]),
            "waveform": waveform_name(waveform),
            "waveform_id": waveform,
            "frequency_hz": self.lib.getfrequency(channel),
            "amplitude_vpp": self.lib.getamplitude(channel),
            "offset_v": self.lib.getoffset(channel),
            "duty_percent": self.lib.getdutycycle(channel),
        }

    def state(self, channel=None):
        if channel is not None:
            channel_number(channel)
        with self.io.session():
            result = {
                "port": self.io.port,
                "mode": self.lib.getmode()[1],
                "phase_deg": self.lib.getphase(),
            }
            result["channels"] = [
                self._channel_state(c) for c in ((channel,) if channel else (1, 2))
            ]
            return result

    @staticmethod
    def waveforms():
        return [{"id": i, "name": name} for i, name in enumerate(WAVEFORMS)] + [
            {"id": i + 100, "name": f"ARBITRARY{i:02d}"} for i in range(1, 61)
        ]

    def _validate(self, state):
        waveform = state["waveform_id"]
        maximum = self._model_limit()
        # Manual p. 6 merges the PULSE, TTL/CMOS and arbitrary rows at 6 MHz.
        if waveform in (2, 5) or 101 <= waveform <= 160:
            maximum = min(maximum, 6e6)
        elif waveform != 0:
            maximum = min(maximum, 25e6)
        freq = number("frequency_hz", state["frequency_hz"], 0, maximum)
        if 0 < freq < 1e-8:
            raise ValueError("Minimum nonzero frequency is 1e-8 Hz")
        amplitude_limit = 20 if freq <= 10e6 else 10 if freq <= 30e6 else 5
        if waveform != 0 and freq > 10e6:
            amplitude_limit = min(amplitude_limit, 5)
        ampl = number("amplitude_vpp", state["amplitude_vpp"], 0.002, amplitude_limit)
        offset_limit = 9.99 if ampl > 2 else 2.5 if ampl > 0.2 else 0.25
        offset = number("offset_v", state["offset_v"], -offset_limit, offset_limit)
        if abs(offset) + ampl / 2 > 10:
            raise ValueError("abs(offset_v) + amplitude_vpp/2 must be <= 10 V")
        number("duty_percent", state["duty_percent"], 0.1, 99.9)

    def configure(
        self,
        channel,
        waveform=None,
        frequency_hz=None,
        amplitude_vpp=None,
        offset_v=None,
        duty_percent=None,
        enabled=None,
    ):
        """Validate first, gate the channel while changing it, then verify readback."""
        channel_number(channel)
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if waveform is not None:
            waveform = waveform_id(waveform)
        requested = {
            "waveform_id": waveform,
            "frequency_hz": frequency_hz,
            "amplitude_vpp": amplitude_vpp,
            "offset_v": offset_v,
            "duty_percent": duty_percent,
            "enabled": enabled,
        }
        if not any(v is not None for v in requested.values()):
            raise ValueError("Supply at least one channel setting")
        with self.io.session():
            before = self._channel_state(channel)
            target = before | {k: v for k, v in requested.items() if v is not None}
            self._validate(target)
            if (
                target["waveform_id"] == 1
                and duty_percent is not None
                and not math.isclose(duty_percent, 50)
            ):
                raise ValueError(
                    "SQUARE has fixed 50% physical duty on this hardware; "
                    "use PULSE for adjustable duty"
                )
            mode = self.lib.getmode()[1]
            if mode not in ("WAVE_CH1", "WAVE_CH2"):
                raise ValueError(
                    f"Channel configuration requires wave mode; current mode is {mode}. "
                    "Use set_mode explicitly first."
                )
            changed = any(v is not None for k, v in requested.items() if k != "enabled")
            outputs = list(self.lib.getchannelenable())
            if changed:
                outputs[channel - 1] = False
                self.lib.setchannelenable(*outputs)
            unit = 0
            try:
                # Zero offset first so a previous large offset doesn't clamp the
                # new amplitude. Output is gated until all settings are verified.
                if changed:
                    self.lib.setoffset(channel, 0)
                    self.lib.setwaveform(channel, target["waveform_id"])
                    freq = target["frequency_hz"]
                    unit = 0
                    if freq > 0 and (
                        round(freq * 100) == 0 or abs(freq * 100 - round(freq * 100)) > 1e-7
                    ):
                        if freq <= 80:
                            unit = 4
                        elif freq <= 80000:
                            unit = 3
                    self.lib.setfrequency(channel, freq, multiplier=unit)
                    self.lib.setamplitude(channel, target["amplitude_vpp"])
                    self.lib.setoffset(channel, target["offset_v"])
                    self.lib.setdutycycle(channel, target["duty_percent"])
                actual = self._channel_state(channel)
                tolerance = {
                    "frequency_hz": (0.005 if unit == 0 else 0.000005 if unit == 3 else 5e-9)
                    + 1e-12,
                    "amplitude_vpp": 0.000500001,
                    "offset_v": 0.005000001,
                    "duty_percent": 0.050000001,
                }
                for key in ("waveform_id", *tolerance):
                    if key == "waveform_id":
                        match = actual[key] == target[key]
                    else:
                        match = math.isclose(
                            actual[key], target[key], rel_tol=1e-12, abs_tol=tolerance[key]
                        )
                    if not match:
                        raise DeviceError(
                            f"Readback mismatch for {key}: requested {target[key]}, "
                            f"received {actual[key]}"
                        )
                outputs[channel - 1] = target["enabled"]
                self.lib.setchannelenable(*outputs)
                actual = self._channel_state(channel)
                if actual["enabled"] != target["enabled"]:
                    raise DeviceError("Output enable readback mismatch")
                return actual
            except Exception as exc:
                # Best effort; do not replay uncertain writes or silently claim rollback.
                try:
                    outputs[channel - 1] = False
                    self.lib.setchannelenable(*outputs)
                except Exception:
                    pass
                raise DeviceError(
                    f"Configuration failed; channel {channel} was requested OFF. "
                    f"Check state before continuing: {exc}"
                ) from exc

    def outputs(self, ch1=None, ch2=None):
        for value in (ch1, ch2):
            if value is not None and type(value) is not bool:
                raise ValueError("Output states must be boolean")
        if ch1 is None and ch2 is None:
            raise ValueError("Supply ch1 or ch2")
        with self.io.session():
            old = self.lib.getchannelenable()
            wanted = (old[0] if ch1 is None else ch1, old[1] if ch2 is None else ch2)
            self.lib.setchannelenable(*wanted)
            actual = self.lib.getchannelenable()
            if actual != wanted:
                raise DeviceError(
                    f"Output readback mismatch: requested {wanted}, received {actual}"
                )
            return {"ch1": actual[0], "ch2": actual[1]}

    def phase(self, phase_deg):
        value = number("phase_deg", phase_deg, -360, 360)
        encoded = round((value % 360) * 10) % 3600
        with self.io.session():
            self.io.write_register(31, encoded)
            actual = self.lib.getphase()
            if not math.isclose(actual, encoded / 10, abs_tol=1e-9):
                raise DeviceError(f"Phase readback mismatch: {actual}")
            return {"phase_deg": actual}

    def mode(self, mode):
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        with self.io.session():
            self.lib.setmode(mode)
            actual = self.lib.getmode()[1]
            if actual != mode:
                raise DeviceError(f"Mode readback mismatch: requested {mode}, received {actual}")
            return {"mode": actual, "actions_stopped": True}

    def stop(self):
        with self.io.session():
            self.lib.stopallactions()
            self.lib.setchannelenable(False, False)
            actual = self.lib.getchannelenable()
            if actual != (False, False):
                raise DeviceError(f"Outputs did not turn off: {actual}")
            return {"actions_stopped": True, "outputs": list(actual)}

    def sweep(
        self, channel, start_hz, end_hz, time_s, direction="RISE", scale="LINEAR", start=False
    ):
        channel_number(channel)
        if direction not in ("RISE", "FALL", "RISE&FALL") or scale not in ("LINEAR", "LOGARITHM"):
            raise ValueError("Invalid sweep direction or scale")
        number("time_s", time_s, 0.1, 999.9)
        with self.io.session():
            state = self._channel_state(channel)
            for freq in (start_hz, end_hz):
                number("sweep frequency", freq, 0.01, self._model_limit())
                self._validate(state | {"frequency_hz": freq})
            self.lib.setmode(f"SWEEP_CH{channel}")
            self.lib.sweep_setstartfreq(start_hz)
            self.lib.sweep_setendfreq(end_hz)
            self.lib.sweep_settime(time_s)
            self.lib.sweep_setdirection(direction)
            self.lib.sweep_setmode(scale)
            result = {
                "channel": channel,
                "start_hz": self.lib.sweep_getstartfreq(),
                "end_hz": self.lib.sweep_getendfreq(),
                "time_s": self.lib.sweep_gettime(),
                "direction": self.lib.sweep_getdirection()[1],
                "scale": self.lib.sweep_getmode()[1],
                "started": False,
            }
            expected = (
                round(start_hz * 100) / 100,
                round(end_hz * 100) / 100,
                round(time_s * 10) / 10,
                direction,
                scale,
            )
            if (
                tuple(result[k] for k in ("start_hz", "end_hz", "time_s", "direction", "scale"))
                != expected
            ):
                raise DeviceError(f"Sweep readback mismatch: {result}")
            if start:
                self.lib.sweep_start()
                result["started"] = True
            return result

    def read_register(self, register):
        if type(register) is not int or not 0 <= register <= 89:
            raise ValueError("register must be an integer from 0 through 89")
        with self.io.session():
            return {"register": register, "value": self.io.read_register(register)}

    def read_arbitrary(self, slot):
        if type(slot) is not int or not 1 <= slot <= 60:
            raise ValueError("slot must be 1 through 60")
        with self.io.session():
            samples = self.lib.arb_getwave(slot)
            if not isinstance(samples, list) or len(samples) != 2048:
                raise DeviceError("Arbitrary waveform reply must have 2048 samples")
            return {"slot": slot, "samples": samples}

    def upload_arbitrary(self, slot, samples):
        if type(slot) is not int or not 1 <= slot <= 60:
            raise ValueError("slot must be 1 through 60")
        if (
            not isinstance(samples, list)
            or len(samples) != 2048
            or any(type(v) is not int or not 0 <= v <= 4095 for v in samples)
        ):
            raise ValueError("samples must be 2048 integers in [0, 4095]")
        with self.io.session():
            self.lib.arb_setwave(slot, samples)
            if self.read_arbitrary(slot)["samples"] != samples:
                raise DeviceError("Arbitrary waveform upload readback mismatch")
            return {"slot": slot, "sample_count": 2048, "verified": True}
