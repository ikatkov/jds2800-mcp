import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jds2800_mcp.api import API
from jds2800_mcp.cli import BatchError, parser, run
from jds2800_mcp.manual import MANUAL_URI, get_manual
from jds2800_mcp.power import CALIBRATION_URI, POWER_GUIDE_URI, get_power_guide

ROOT = Path(__file__).resolve().parents[1]


def test_cli_no_waveform_argument_regression(generator):
    args = parser().parse_args(["configure", "1", "--frequency-hz", "3000"])
    assert run(API(generator), args)["frequency_hz"] == 3000


def test_cli_batch_reports_completed_results(generator, tmp_path):
    import pytest

    path = tmp_path / "batch.json"
    path.write_text(
        json.dumps(
            [
                {"operation": "set_outputs", "arguments": {"ch2": True}},
                {
                    "operation": "configure_channel",
                    "arguments": {"channel": 1, "frequency_hz": 16e6},
                },
                {"operation": "set_outputs", "arguments": {"ch1": False}},
            ]
        )
    )
    args = parser().parse_args(["batch", str(path)])
    with pytest.raises(BatchError) as error:
        run(API(generator), args)
    assert error.value.index == 1
    assert error.value.completed == [{"ch1": True, "ch2": True}]
    assert generator.io.registers[20] == [1, 1]


def test_cli_discovery_does_not_open_port():
    result = subprocess.run(
        [sys.executable, "-m", "jds2800_mcp.cli", "--port", "/missing", "waveforms"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)[0] == {"id": 0, "name": "SINE"}
    assert result.stderr == ""


def test_cli_no_generator_exits_with_json_error():
    script = """
import sys
from jds2800_mcp import transport
from jds2800_mcp.cli import main
transport.ports = lambda: []
sys.exit(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "info"],
        env=dict(os.environ) | {"JDS2800_PORT": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["type"] == "DeviceError"
    assert "No USB serial ports found" in error["error"]


def test_cli_manual_available_without_generator():
    result = subprocess.run(
        [sys.executable, "-m", "jds2800_mcp.cli", "--port", "/missing", "manual"],
        capture_output=True,
        text=True,
        check=True,
    )
    reference = json.loads(result.stdout)
    assert reference == get_manual()
    assert "JDS2800_EN_manual.pdf" in reference
    assert "6 MHz" in reference
    assert result.stderr == ""


def test_mcp_handshake_discovery_and_structured_errors(calibration_file):
    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "jds2800_mcp.server", "--port", "/missing"],
            env=dict(os.environ),
            cwd=str(ROOT),
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                init = await client.initialize()
                assert init.serverInfo.name == "JDS2800"
                assert "get_manual" in init.instructions
                listing = await client.list_tools()
                assert len(listing.tools) == 17
                read = next(t for t in listing.tools if t.name == "get_state")
                assert read.annotations.readOnlyHint
                manual = next(t for t in listing.tools if t.name == "get_manual")
                assert manual.annotations.readOnlyHint
                result = await client.call_tool("get_manual", {})
                assert not result.isError
                assert result.content[0].text == get_manual()
                resources = await client.list_resources()
                resource = next(r for r in resources.resources if str(r.uri) == MANUAL_URI)
                assert resource.mimeType == "text/markdown"
                document = await client.read_resource(MANUAL_URI)
                assert document.contents[0].text == get_manual()
                document = await client.read_resource(POWER_GUIDE_URI)
                assert document.contents[0].text == get_power_guide()
                result = await client.call_tool("get_calibration", {})
                assert not result.isError
                metadata = result.structuredContent or json.loads(result.content[0].text)
                assert metadata["load_ohms"] == 50
                document = await client.read_resource(CALIBRATION_URI)
                assert (
                    json.loads(document.contents[0].text)["calibration_id"] == "synthetic-test-only"
                )
                result = await client.call_tool(
                    "preview_power",
                    {
                        "channel": 1,
                        "frequency_hz": 1e6,
                        "power_dbm": 0,
                    },
                )
                assert result.isError
                assert "Serial error" in result.content[0].text
                result = await client.call_tool("list_waveforms", {})
                assert not result.isError
                result = await client.call_tool("get_device_info", {})
                assert result.isError
                assert "Serial error" in result.content[0].text
                result = await client.call_tool("configure_channel", {"channel": 3})
                assert result.isError

    asyncio.run(check())
