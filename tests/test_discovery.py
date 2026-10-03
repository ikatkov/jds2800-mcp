import pytest
import serial

import jds2800_mcp.transport as transport
from jds2800_mcp.transport import DeviceError, Settings, Transport


def usb_port(device, vid=0x1A86):
    return {"device": device, "vid": vid, "description": "USB serial"}


def fake_devices(monkeypatch, entries, profiles):
    opened, commands, closed = [], [], []

    class Serial:
        def __init__(self, port, *args, **kwargs):
            opened.append(port)
            self.port = port
            self.profile = profiles[port]
            if isinstance(self.profile, list):
                self.profile = self.profile.pop(0)
            if isinstance(self.profile, Exception):
                raise self.profile
            self.buffer = b""
            self.timeout = kwargs["timeout"]

        def reset_input_buffer(self):
            self.buffer = b""

        def write(self, data):
            commands.append((self.port, data))
            register = int(data[2:4])
            value = self.profile.get(register)
            if value is not None:
                payload = ",".join(str(v) for v in value) if isinstance(value, list) else str(value)
                self.buffer = f":r{register:02d}={payload}.\r\n".encode()
            return len(data)

        def read_until(self, *args, **kwargs):
            data, self.buffer = self.buffer, b""
            return data

        def close(self):
            closed.append(self.port)

    monkeypatch.setattr(transport, "ports", lambda: entries)
    monkeypatch.setattr(transport.serial, "Serial", Serial)
    return opened, commands, closed


def test_iterates_past_wrong_adapter_and_only_reads(monkeypatch):
    first, right = "/dev/cu.usbserial-fake-first", "/dev/cu.usbserial-fake-right"
    opened, commands, closed = fake_devices(
        monkeypatch,
        [usb_port(first), usb_port(right)],
        {
            first: {0: 99},
            right: {0: 15, 1: 123456789, 20: [0, 0], 31: 900},
        },
    )
    io = Transport(Settings())
    with io.session():
        assert io.port == right
        assert io.read_register(31) == 900
    assert opened == [first, right, right]  # Last connection verifies identity under the lease.
    assert closed == opened
    assert all(command.startswith(b":r") for _, command in commands)
    assert io.serial is None


def test_falls_back_to_non_ch340_usb_port_and_deduplicates_macos_aliases(monkeypatch):
    right = "/dev/cu.usbmodem-fake-right"
    entries = [
        usb_port("/dev/tty.usbmodem-fake-right", None),
        usb_port(right, None),
        {"device": "/dev/cu.Bluetooth-Incoming-Port", "vid": None},
        {"device": "/dev/cu.debug-console", "vid": None},
    ]
    opened, _, _ = fake_devices(monkeypatch, entries, {right: {0: 40, 1: 123, 20: [1, 0]}})
    with Transport(Settings()).session() as io:
        assert io.port == right
    assert opened == [right, right]


def test_no_usb_ports_gives_actionable_error(monkeypatch):
    monkeypatch.setattr(transport, "ports", lambda: [])
    with pytest.raises(DeviceError, match="No USB serial ports found"):
        with Transport(Settings()).session():
            pytest.fail("Should not open a session")


def test_failed_probes_list_each_port_and_release_connections(monkeypatch):
    first, second = "/dev/cu.usbserial-fake-silent", "/dev/cu.usbserial-fake-unavailable"
    opened, _, closed = fake_devices(
        monkeypatch,
        [usb_port(first), usb_port(second)],
        {
            first: {},
            second: serial.SerialException("busy elsewhere"),
        },
    )
    io = Transport(Settings())
    with pytest.raises(DeviceError) as error:
        with io.session():
            pytest.fail("No generator should match")
    assert first in str(error.value) and second in str(error.value)
    assert "busy elsewhere" in str(error.value)
    assert closed == [first] and len(opened) == 2
    assert io.serial is None


def test_two_matching_generators_require_explicit_choice(monkeypatch):
    first, second = "/dev/cu.usbserial-fake-one", "/dev/cu.usbserial-fake-two"
    fake_devices(
        monkeypatch,
        [usb_port(first), usb_port(second)],
        {
            first: {0: 15, 1: 1, 20: [0, 0]},
            second: {0: 60, 1: 2, 20: [1, 0]},
        },
    )
    with pytest.raises(DeviceError, match="Multiple JDS-compatible generators"):
        with Transport(Settings()).session():
            pytest.fail("Ambiguous generator should not be selected")


def test_explicit_port_bypasses_other_ports(monkeypatch):
    right = "/dev/cu.usbserial-fake-explicit"
    opened, _, _ = fake_devices(monkeypatch, [], {right: {31: 42}})
    monkeypatch.setattr(transport, "ports", lambda: pytest.fail("Must not scan explicit port"))
    with Transport(Settings(right)).session() as io:
        assert io.read_register(31) == 42
    assert opened == [right]


@pytest.mark.parametrize(
    "profile", [{0: 15, 1: -1}, {0: 15, 1: 3, 20: [2, 0]}, {0: [15, 0]}, {0: 15, 1: 3, 20: 0}]
)
def test_partial_or_malformed_identity_does_not_match(monkeypatch, profile):
    port = "/dev/cu.usbserial-fake-invalid"
    fake_devices(monkeypatch, [usb_port(port)], {port: profile})
    with pytest.raises(DeviceError, match="No JDS2800-compatible generator"):
        with Transport(Settings()).session():
            pytest.fail("Malformed identity must not match")


def test_identity_change_between_probe_and_action_prevents_action(monkeypatch):
    port = "/dev/cu.usbserial-fake-replaced"
    _, commands, _ = fake_devices(
        monkeypatch,
        [usb_port(port)],
        {
            port: [{0: 15, 1: 1, 20: [0, 0]}, {0: 15, 1: 2, 20: [0, 0]}],
        },
    )
    with pytest.raises(DeviceError, match="identity changed"):
        with Transport(Settings()).session() as io:
            io.write_register(20, "1,1")
    assert all(command.startswith(b":r") for _, command in commands)
