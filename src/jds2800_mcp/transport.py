"""Bounded serial transactions, shared by MCP and CLI processes (macOS/Linux)."""

import fcntl
import hashlib
import math
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial
from serial.tools import list_ports


class DeviceError(RuntimeError):
    """A connection, framing, acknowledgement or readback failure."""


MODEL_CODES = (15, 30, 40, 50, 60)


def ports() -> list[dict]:
    return [
        {
            "device": p.device,
            "description": p.description,
            "vid": p.vid,
            "pid": p.pid,
            "serial_number": p.serial_number,
        }
        for p in list_ports.comports()
    ]


@dataclass(frozen=True)
class Settings:
    port: str | None = None
    timeout: float = 1.0
    lock_timeout: float = 5.0

    def __post_init__(self):
        for name in ("timeout", "lock_timeout"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 60:
                raise ValueError(f"{name} must be finite and between 0 and 60 seconds")

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("JDS2800_PORT") or None,
            float(os.environ.get("JDS2800_TIMEOUT", "1")),
            float(os.environ.get("JDS2800_LOCK_TIMEOUT", "5")),
        )


class Transport:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.serial = None
        self.port = None
        self._detected_identity = None

    @staticmethod
    def candidates():
        # Bluetooth/headset and debug-console ports are not USB generator ports.
        # Include USB devices even if their adapter VID is missing or unfamiliar.
        result = {}
        for entry in ports():
            port = entry["device"].replace("/dev/tty.", "/dev/cu.")
            if entry.get("vid") is None and "usb" not in port.lower() and "acm" not in port.lower():
                continue
            description = (entry.get("description") or "").lower()
            priority = 0 if "jds" in description else 1 if entry.get("vid") == 0x1A86 else 2
            result[port] = min(priority, result.get(port, priority))
        return sorted(result, key=lambda port: (result[port], port))

    def _identify(self):
        model = self.read_register(0)
        if type(model) is not int or model not in MODEL_CODES:
            raise DeviceError(f"Not a supported JDS generator: model reply {model!r}")
        device_serial = self.read_register(1)
        if type(device_serial) is not int or device_serial < 0:
            raise DeviceError(f"Invalid generator serial number: {device_serial!r}")
        outputs = self.read_register(20)
        if (
            not isinstance(outputs, list)
            or len(outputs) != 2
            or any(value not in (0, 1) for value in outputs)
        ):
            raise DeviceError(f"Invalid generator channel reply: {outputs!r}")
        return model, device_serial

    def resolve_port(self):
        if self.settings.port:
            return self.settings.port
        candidates = self.candidates()
        if not candidates:
            raise DeviceError(
                "No USB serial ports found for JDS2800 discovery. Connect the generator "
                "or set --port / JDS2800_PORT explicitly."
            )
        matches = []
        failures = []
        for port in candidates:
            try:
                with self._connection(
                    port,
                    timeout=min(self.settings.timeout, 0.5),
                    lock_timeout=min(self.settings.lock_timeout, 0.25),
                ):
                    identity = self._identify()
                matches.append((port, identity))
            except DeviceError as exc:
                failures.append(f"{port}: {exc}")
        if not matches:
            raise DeviceError(
                "No JDS2800-compatible generator answered on the available USB "
                "serial ports. Tried "
                + "; ".join(failures)
                + ". Check the connection or set --port / JDS2800_PORT explicitly."
            )
        if len(matches) > 1:
            found = ", ".join(
                f"{port} (model {identity[0]}, serial {identity[1]})" for port, identity in matches
            )
            raise DeviceError(
                f"Multiple JDS-compatible generators found: {found}. "
                "Select one with --port or JDS2800_PORT."
            )
        port, self._detected_identity = matches[0]
        return port

    @contextmanager
    def session(self):
        # One operation owns the port. Persistent MCP and short-lived CLI clients
        # can coexist; compound operations keep the lease until readback completes.
        with self.lock:
            if self.serial is not None:
                yield self
                return
            port = self.resolve_port()
            with self._connection(port):
                # Recheck under the operation's lease in case devices changed
                # between probing and reopening. Never replay the caller's action.
                if not self.settings.port and self._identify() != self._detected_identity:
                    raise DeviceError(f"Generator identity changed on {port}; try discovery again")
                yield self

    @contextmanager
    def _connection(self, port, timeout=None, lock_timeout=None):
        canonical = os.path.realpath(port).replace("/dev/tty.", "/dev/cu.")
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:20]
        path = Path(tempfile.gettempdir()) / f"jds2800-{os.getuid()}-{digest}.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        timeout = self.settings.timeout if timeout is None else timeout
        lock_timeout = self.settings.lock_timeout if lock_timeout is None else lock_timeout
        try:
            deadline = time.monotonic() + lock_timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DeviceError(
                            f"Generator busy on {port}; timed out waiting for lock"
                        ) from None
                    time.sleep(0.02)
            self.serial = serial.Serial(
                port,
                115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout,
                write_timeout=timeout,
                exclusive=True,
            )
            self.port = port
            self.serial.reset_input_buffer()
            yield self
        except (serial.SerialException, OSError) as exc:
            raise DeviceError(f"Serial error on {port}: {exc}") from exc
        finally:
            try:
                if self.serial is not None:
                    connection = self.serial
                    self.serial = None
                    connection.close()
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _send(self, command: str):
        if self.serial is None:
            raise DeviceError("No serial session")
        data = (command + "\n").encode("ascii")
        if self.serial.write(data) != len(data):
            raise DeviceError("Incomplete serial write; device state may have changed")

    def _line(self, max_bytes=20000):
        data = self.serial.read_until(b"\n", size=max_bytes)
        if not data.endswith(b"\n"):
            raise DeviceError(f"Incomplete or timed out device reply: {data[:120]!r}")
        try:
            return data.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise DeviceError(f"Non-ASCII device reply: {data[:120]!r}") from exc

    def read_register(self, register: int, arbitrary=False):
        command = "b" if arbitrary else "r"
        self._send(f":{command}{register:02d}=0.")
        line = self._line()
        prefix = f":{command}{register:02d}="
        if not line.startswith(prefix) or (not arbitrary and not line.endswith(".")):
            raise DeviceError(f"Unexpected reply to register {register}: {line[:120]!r}")
        payload = line[len(prefix) :].removesuffix(".")
        if arbitrary:
            payload = payload.removesuffix(",")
        if not re.fullmatch(r"-?\d+(,-?\d+)*", payload):
            raise DeviceError(f"Malformed register {register} value: {payload[:120]!r}")
        values = [int(v) for v in payload.split(",")]
        return values[0] if len(values) == 1 else values

    def write_register(self, register: int, value, arbitrary=False):
        command = "a" if arbitrary else "w"
        payload = str(value)
        if not re.fullmatch(r"-?\d+(,-?\d+)*", payload):
            raise ValueError("Register payload must contain comma-separated integers")
        self._send(f":{command}{register:02d}={payload}.")
        reply = self._line()
        if reply != ":ok":
            raise DeviceError(f"Write to register {register} was not acknowledged: {reply!r}")
