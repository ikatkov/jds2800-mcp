#!/usr/bin/env python3
"""Test JDS2800 through stdio MCP and measure both coax outputs through Rigol MCP.

CH1 -> scope CH1; CH2 -> scope CH3. Leaves both generator outputs OFF.
Supply a Rigol MCP server script. No direct scope socket access.
"""

import argparse
import asyncio
import base64
import json
import math
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from jds2800_mcp.calibrate import save

ROOT = Path(__file__).resolve().parents[1]


async def connect(stack, command, args, env):
    reader, writer = await stack.enter_async_context(
        stdio_client(StdioServerParameters(command=str(command), args=args, env=env, cwd=str(ROOT)))
    )
    client = await stack.enter_async_context(ClientSession(reader, writer))
    await client.initialize()
    return client


async def call(client, name, arguments=None):
    result = await client.call_tool(name, arguments or {})
    if result.isError:
        raise RuntimeError(f"{name}: {result.content}")
    if result.structuredContent:
        data = result.structuredContent
        if set(data) == {"result"} and isinstance(data["result"], str):
            try:
                return json.loads(data["result"])
            except json.JSONDecodeError:
                return data["result"]
        return data
    for content in result.content:
        if content.type == "text":
            try:
                return json.loads(content.text)
            except json.JSONDecodeError:
                return content.text
    return result


def near(value, wanted, absolute=0, relative=0):
    if value is None or not math.isclose(value, wanted, abs_tol=absolute, rel_tol=relative):
        raise AssertionError(
            f"Measured {value}; expected {wanted}, "
            f"tolerance absolute={absolute}, relative={relative}"
        )


async def main(args):
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "wiring": {"generator_1": "scope_1", "generator_2": "scope_3"},
        "tests": [],
    }
    async with AsyncExitStack() as stack:
        env = dict(os.environ)
        generator = await connect(
            stack,
            sys.executable,
            ["-m", "jds2800_mcp.server"] + (["--port", args.port] if args.port else []),
            env,
        )
        scope = await connect(
            stack,
            sys.executable,
            [str(args.rigol_server)],
            env | {"RIGOL_HOST": args.scope_host, "RIGOL_TIMEOUT": "10"},
        )
        report["generator_info"] = await call(generator, "get_device_info")
        report["initial_generator_state"] = await call(generator, "get_state")
        report["scope_info"] = await call(scope, "scope_info")
        try:
            # A following *OPC? keeps each short-lived connection open until the
            # scope has consumed the write, avoiding discarded/pending commands.
            for command in (
                ":CHAN1:PROB 1",
                ":CHAN3:PROB 1",
                ":CHAN1:SCAL 0.5",
                ":CHAN3:SCAL 0.5",
                ":CHAN1:OFFS 0",
                ":CHAN3:OFFS 0",
                ":CHAN1:COUP DC",
                ":CHAN3:COUP DC",
                ":CHAN1:DISP ON",
                ":CHAN3:DISP ON",
                ":TIM:MAIN:SCAL 2E-4",
                ":TIM:MAIN:OFFS 0",
                ":TRIG:EDG:SOUR CHAN1",
                ":TRIG:EDG:LEV 0",
                ":TRIG:SWE AUTO",
                ":RUN",
            ):
                await call(scope, "scpi", {"command": command + "\n*OPC?"})
            actual_scale = float(await call(scope, "scpi", {"command": ":TIM:MAIN:SCAL?"}))
            near(actual_scale, 2e-4, absolute=1e-12)
            await call(generator, "set_mode", {"mode": "WAVE_CH1"})
            await call(generator, "stop_outputs")
            for channel, hz, vpp in ((1, 1000, 2), (2, 2000, 1)):
                await call(
                    generator,
                    "configure_channel",
                    {
                        "channel": channel,
                        "waveform": "SINE",
                        "frequency_hz": hz,
                        "amplitude_vpp": vpp,
                        "offset_v": 0,
                        "duty_percent": 50,
                        "enabled": True,
                    },
                )
            await asyncio.sleep(0.6)
            for channel, hz, vpp in (("1", 1000, 2), ("3", 2000, 1)):
                result = await call(
                    scope,
                    "get_stats",
                    {"channel": channel, "items": ["FREQuency", "VPP", "VAVG", "VRMS"]},
                )
                m = result["measurements"]
                near(m["FREQuency"], hz, relative=0.01)
                near(m["VPP"], vpp, absolute=0.2)
                near(m["VAVG"], 0, absolute=0.1)
                report["tests"].append({"name": f"sine_scope_ch{channel}", "result": result})
            # Verify CLI coexistence while this MCP session is still alive.
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "jds2800_mcp.cli",
                *(["--port", args.port] if args.port else []),
                "state",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode:
                raise AssertionError(stderr.decode())
            report["tests"].append({"name": "cli_with_live_mcp", "result": json.loads(stdout)})
            # Check a triangle with DC offset, then an adjustable-duty pulse.
            await call(scope, "scpi", {"command": ":TRIG:EDG:LEV 1\n*OPC?"})
            await call(
                generator,
                "configure_channel",
                {
                    "channel": 1,
                    "waveform": "TRIANGLE",
                    "frequency_hz": 1000,
                    "amplitude_vpp": 2,
                    "offset_v": 1,
                    "enabled": True,
                },
            )
            await call(
                generator,
                "configure_channel",
                {
                    "channel": 2,
                    "waveform": "PULSE",
                    "frequency_hz": 2000,
                    "amplitude_vpp": 1,
                    "offset_v": 0,
                    "duty_percent": 30,
                    "enabled": True,
                },
            )
            await asyncio.sleep(0.6)
            result = await call(
                scope, "get_stats", {"channel": "1", "items": ["FREQuency", "VPP", "VAVG"]}
            )
            near(result["measurements"]["VAVG"], 1, absolute=0.1)
            near(result["measurements"]["VPP"], 2, absolute=0.2)
            near(result["measurements"]["FREQuency"], 1000, relative=0.01)
            report["tests"].append({"name": "triangle_offset", "result": result})
            result = await call(
                scope, "get_stats", {"channel": "3", "items": ["FREQuency", "VPP", "PDUTy"]}
            )
            near(result["measurements"]["PDUTy"], 0.30, absolute=0.02)
            near(result["measurements"]["FREQuency"], 2000, relative=0.01)
            report["tests"].append({"name": "pulse_30_percent", "result": result})
            screenshot = await scope.call_tool("get_screenshot", {})
            if screenshot.isError:
                raise RuntimeError(screenshot.content)
            for content in screenshot.content:
                if content.type == "image":
                    (args.out / "scope-triangle-pulse.png").write_bytes(
                        base64.b64decode(content.data)
                    )
            phase = await call(generator, "set_phase", {"phase_deg": -90})
            near(phase["phase_deg"], 270, absolute=1e-9)
            report["tests"].append({"name": "negative_phase_readback", "result": phase})
            await call(generator, "set_phase", {"phase_deg": 0})
            # Independent output switching: CH1 off must leave CH2 running.
            await call(generator, "set_outputs", {"ch1": False})
            await asyncio.sleep(0.3)
            result = await call(scope, "get_stats", {"channel": "1", "items": ["VPP"]})
            if result["measurements"]["VPP"] is not None:
                assert result["measurements"]["VPP"] < 0.2
            result2 = await call(
                scope, "get_stats", {"channel": "3", "items": ["FREQuency", "VPP"]}
            )
            near(result2["measurements"]["FREQuency"], 2000, relative=0.01)
            report["tests"].append({"name": "independent_outputs", "off": result, "on": result2})
            # Invalid requests must be MCP errors and preserve state.
            before = await call(generator, "get_state")
            invalid = await generator.call_tool(
                "configure_channel", {"channel": 1, "frequency_hz": 16e6}
            )
            assert invalid.isError
            assert await call(generator, "get_state") == before
            report["tests"].append({"name": "model_limit_no_mutation", "passed": True})
            report["passed"] = True
        except Exception as exc:
            report["passed"] = False
            report["error"] = str(exc)
            raise
        finally:
            await call(generator, "set_phase", {"phase_deg": 0})
            await call(generator, "stop_outputs")
            report["final_generator_state"] = await call(generator, "get_state")
            save(args.out / "hardware-verification.json", report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "tests": len(report["tests"]),
                "report": str(args.out / "hardware-verification.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Optional generator port; defaults to USB discovery")
    parser.add_argument("--scope-host", required=True, help="Hostname or IP address of the scope")
    parser.add_argument("--rigol-server", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts")
    asyncio.run(main(parser.parse_args()))
