import os
import subprocess
import sys
import threading
import time

import pytest

from jds2800_mcp.transport import DeviceError, Settings, Transport


def serial_reply(reply, action):
    master, slave = os.openpty()
    port = os.ttyname(slave)
    commands = []

    def emulator():
        command = bytearray()
        while not command.endswith(b"\n"):
            command += os.read(master, 1)
        commands.append(bytes(command))
        # Intentionally fragment the reply, like a USB serial device.
        middle = len(reply) // 2
        os.write(master, reply[:middle])
        time.sleep(0.01)
        os.write(master, reply[middle:])

    thread = threading.Thread(target=emulator, daemon=True)
    thread.start()
    io = Transport(Settings(port, timeout=0.1, lock_timeout=0.1))
    try:
        with io.session():
            result = action(io)
        return result, commands
    finally:
        thread.join(0.5)
        os.close(master)
        os.close(slave)
        assert io.serial is None


def test_fragmented_line_read():
    result, commands = serial_reply(b":r27=1000.\r\n", lambda io: io.read_register(27))
    assert result == 1000
    assert commands == [b":r27=0.\n"]


@pytest.mark.parametrize("reply", [b":r28=1000.\r\n", b":r27=nope.\r\n", b":r27=1000."])
def test_mismatched_malformed_and_incomplete_frames_fail(reply):
    with pytest.raises(DeviceError):
        serial_reply(reply, lambda io: io.read_register(27))


def test_write_requires_exact_ack():
    with pytest.raises(DeviceError, match="not acknowledged"):
        serial_reply(b":error\r\n", lambda io: io.write_register(20, "1,0"))


def test_nested_transaction_reuses_port():
    def action(io):
        handle = io.serial
        with io.session():
            assert io.serial is handle
            return io.read_register(20)

    result, _ = serial_reply(b":r20=1,0.\r\n", action)
    assert result == [1, 0]


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts(value):
    with pytest.raises(ValueError):
        Settings(timeout=value)


def test_other_process_cannot_interleave_serial_operations():
    master, slave = os.openpty()
    port = os.ttyname(slave)
    try:
        with Transport(Settings(port)).session():
            script = """
import sys
from jds2800_mcp.transport import Transport, Settings, DeviceError
try:
    with Transport(Settings(sys.argv[1], lock_timeout=0.1)).session():
        raise AssertionError('Lock should prevent opening')
except DeviceError as exc:
    assert 'busy' in str(exc)
    print('busy')
"""
            result = subprocess.run(
                [sys.executable, "-c", script, port],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            assert result.stdout.strip() == "busy"
    finally:
        os.close(master)
        os.close(slave)
