#!/usr/bin/env python3
"""Check dBm controls at frequencies/levels absent from the calibration grid.

Uses both stdio MCP servers and confirmed external 50-ohm loads. Leaves outputs off.
"""

import argparse
import asyncio
import base64
import json
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

from jds2800_mcp.calibrate import call, connect, measure, save, scope_scale, write_scope


async def check_cli(gen, scope, args, env, report):
    # Exercise the actual scripting launcher while the MCP server is alive.
    cli = await asyncio.create_subprocess_exec(
        str(Path(__file__).resolve().parents[1] / "jds2800"),
        *(["--port", args.port] if args.port else []),
        "power",
        "1",
        "--frequency-hz",
        "14500000",
        "--dbm",
        "10",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await cli.communicate()
    if cli.returncode:
        raise RuntimeError(stderr.decode())
    report["cli_result"] = json.loads(stdout)
    await asyncio.sleep(1)
    report["cli_measurements"] = []
    for channel, scope_channel in ((1, 1), (2, 3)):
        reading = await measure(scope, scope_channel, 14.5e6)
        error = reading["measured_dbm"] - 10
        report["cli_measurements"].append(
            {
                "channel": channel,
                "frequency_hz": 14.5e6,
                "requested_dbm": 10,
                "error_db": error,
                "measurement": reading,
            }
        )
        if abs(error) > args.tolerance_db or reading["repeatability_db"] > 0.3:
            raise RuntimeError(f"Post-CLI scope check failed: {error:.3f} dB")
    screenshot = await scope.call_tool("get_screenshot", {})
    if not screenshot.isError:
        for block in screenshot.content:
            if block.type == "image":
                args.out.with_suffix(".png").write_bytes(base64.b64decode(block.data))


async def verify(args):
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "passed": False,
        "tests": [],
        "tolerance_db": args.tolerance_db,
        "measurement_method": "Clear prior measurements; query numeric VRMS/VAVG/frequency/Vpp three times",
    }
    env = dict(os.environ) | {"JDS2800_CALIBRATION": str(args.calibration.resolve())}
    async with AsyncExitStack() as stack:
        gen = await connect(
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
        report["calibration"] = await call(gen, "get_calibration")
        try:
            # Averaging can smear RF traces at some scale/trigger combinations.
            # Validate independently with normal acquisition and repeated readings.
            await write_scope(scope, [":ACQ:TYPE NORM", ":TRIG:EDG:COUP DC"])
            report["acquisition"] = "NORM"
            await call(gen, "stop_outputs")
            await call(gen, "set_mode", {"mode": "WAVE_CH1"})
            for channel, scope_channel in ((1, 1), (2, 3)):
                await call(gen, "stop_outputs")
                await write_scope(scope, [f":TRIG:EDG:SOUR CHAN{scope_channel}"])
                cases = [
                    (f * 1e6, p)
                    for f in (1.5, 5.5, 9.5, 10.5, 14.5)
                    for p in (-25, -16, -7, 0, 7, 10)
                ]
                cases += [(f * 1e6, 0) for f in (1, 10, 10.005, 15)]
                for frequency, power in cases:
                    plan = await call(
                        gen,
                        "preview_power",
                        {
                            "channel": channel,
                            "frequency_hz": frequency,
                            "power_dbm": power,
                        },
                    )
                    await write_scope(
                        scope,
                        [
                            f":CHAN{scope_channel}:SCAL {scope_scale(plan['amplitude_vpp'] / 2)}",
                            f":TIM:MAIN:SCAL {1 / frequency}",
                        ],
                    )
                    settings = await call(
                        gen,
                        "set_power",
                        {
                            "channel": channel,
                            "frequency_hz": frequency,
                            "power_dbm": power,
                            "enabled": True,
                        },
                    )
                    await asyncio.sleep(0.8)
                    reading = await measure(scope, scope_channel, frequency)
                    if reading["repeatability_db"] > 0.3:
                        raise RuntimeError("Unstable scope reading during verification")
                    error = reading["measured_dbm"] - power
                    result = {
                        "channel": channel,
                        "frequency_hz": frequency,
                        "requested_dbm": power,
                        "error_db": error,
                        "settings": settings,
                        "measurement": reading,
                    }
                    report["tests"].append(result)
                    save(args.out, report)
                    print(
                        json.dumps(
                            {
                                "test": len(report["tests"]),
                                "channel": channel,
                                "frequency_hz": frequency,
                                "power_dbm": power,
                                "error_db": round(error, 3),
                            }
                        ),
                        flush=True,
                    )
                    if abs(error) > args.tolerance_db:
                        raise RuntimeError(f"Power verification failed: {error:.3f} dB error")
            # Both loaded outputs together, including the highest verified level.
            for frequency, power in ((5.5e6, 0), (14.5e6, 10)):
                for channel in (1, 2):
                    plan = await call(
                        gen,
                        "preview_power",
                        {
                            "channel": channel,
                            "frequency_hz": frequency,
                            "power_dbm": power,
                        },
                    )
                    scope_channel = 1 if channel == 1 else 3
                    await write_scope(
                        scope,
                        [
                            f":CHAN{scope_channel}:SCAL {scope_scale(plan['amplitude_vpp'] / 2)}",
                            f":TIM:MAIN:SCAL {1 / frequency}",
                        ],
                    )
                    await call(
                        gen,
                        "set_power",
                        {
                            "channel": channel,
                            "frequency_hz": frequency,
                            "power_dbm": power,
                            "enabled": True,
                        },
                    )
                await asyncio.sleep(1)
                for channel, scope_channel in ((1, 1), (2, 3)):
                    reading = await measure(scope, scope_channel, frequency)
                    if reading["repeatability_db"] > 0.3:
                        raise RuntimeError("Unstable scope reading with both outputs enabled")
                    error = reading["measured_dbm"] - power
                    report["tests"].append(
                        {
                            "channel": channel,
                            "frequency_hz": frequency,
                            "requested_dbm": power,
                            "both_outputs": True,
                            "error_db": error,
                            "measurement": reading,
                        }
                    )
                    if abs(error) > args.tolerance_db:
                        raise RuntimeError(f"Simultaneous-output check failed: {error:.3f} dB")
            await check_cli(gen, scope, args, env, report)
            report["passed"] = True
            report["maximum_absolute_error_db"] = max(
                abs(t["error_db"]) for t in report["tests"] + report["cli_measurements"]
            )
        except BaseException as exc:
            report["error"] = str(exc)
            raise
        finally:
            try:
                await call(gen, "stop_outputs")
                report["final_state"] = await call(gen, "get_state")
            finally:
                save(args.out, report)
    print(
        json.dumps(
            {
                "passed": True,
                "tests": len(report["tests"]),
                "maximum_absolute_error_db": report["maximum_absolute_error_db"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Optional generator port; defaults to USB discovery")
    parser.add_argument("--scope-host", required=True, help="Hostname or IP address of the scope")
    parser.add_argument("--rigol-server", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tolerance-db", type=float, default=0.35)
    asyncio.run(verify(parser.parse_args()))
