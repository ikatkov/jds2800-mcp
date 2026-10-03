"""Measure sine power through the JDS2800 and Rigol stdio MCP servers."""

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FREQUENCIES = [n * 1e6 for n in range(1, 16)] + [10.01e6]
AMPLITUDES = [0.04, 0.126, 0.2, 0.4, 0.6, 0.8, 1.265, 2.0, 3.0, 5.0]


async def connect(stack, command, args, env):
    reader, writer = await stack.enter_async_context(
        stdio_client(StdioServerParameters(command=str(command), args=args, env=env))
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
        if set(data) != {"result"}:
            return data
        data = data["result"]
    else:
        data = next(c.text for c in result.content if c.type == "text")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return data
    return data


def scope_scale(loaded_vpp):
    wanted = max(0.001, loaded_vpp / 5)
    decade = 10 ** math.floor(math.log10(wanted))
    return next(decade * n for n in (1, 2, 5, 10) if decade * n >= wanted)


async def write_scope(scope, commands):
    reply = await call(scope, "scpi", {"command": "\n".join(commands) + "\n*OPC?"})
    if str(reply).strip() != "1":
        raise RuntimeError(f"Scope did not acknowledge setup: {reply}")


async def measure(scope, channel, frequency_hz, repeats=3):
    items = ["VRMS", "VAVG", "FREQuency", "VPP"]
    query = ";".join(f":MEAS:ITEM? {item},CHAN{channel}" for item in items)
    measurements = []
    for _ in range(repeats):
        await write_scope(scope, [":MEAS:CLE ALL"])
        reply = await call(scope, "scpi", {"command": query})
        values = [float(v) for v in str(reply).split(";")]
        if len(values) != len(items) or any(not math.isfinite(v) or abs(v) > 1e30 for v in values):
            raise RuntimeError(f"Unmeasurable scope response: {reply}")
        reading = dict(zip(items, values, strict=True))
        if reading["VRMS"] <= 0 or reading["VPP"] <= 0:
            raise RuntimeError(f"Invalid voltage measurement: {reading}")
        # The scope's period-based frequency result is coarsely quantized at RF.
        # Identity/wiring is established at pilot levels; retain this as a gross
        # connection check, not a frequency calibration of the generator.
        if abs(reading["FREQuency"] / frequency_hz - 1) > 0.20:
            raise RuntimeError(f"Wrong frequency or insufficient signal: {reading}")
        squared = reading["VRMS"] ** 2 - reading["VAVG"] ** 2
        if squared <= 0:
            raise RuntimeError(f"Invalid AC RMS measurement: {reading}")
        reading["vrms_ac_v"] = math.sqrt(squared)
        reading["measured_dbm"] = 10 * math.log10(squared / 50 / 0.001)
        reading["vpp_sine_dbm"] = 10 * math.log10(reading["VPP"] ** 2 / (8 * 50) / 0.001)
        measurements.append(reading)
        await asyncio.sleep(0.1)
    return {
        "vrms_ac_v": statistics.median(r["vrms_ac_v"] for r in measurements),
        "measured_dbm": statistics.median(r["measured_dbm"] for r in measurements),
        "vpp_v": statistics.median(r["VPP"] for r in measurements),
        "dc_v": statistics.median(r["VAVG"] for r in measurements),
        "vpp_sine_dbm": statistics.median(r["vpp_sine_dbm"] for r in measurements),
        "frequency_measured_hz": statistics.median(r["FREQuency"] for r in measurements),
        "repeatability_db": max(r["measured_dbm"] for r in measurements)
        - min(r["measured_dbm"] for r in measurements),
        "readings": measurements,
    }


def portable_metadata(value):
    """Keep instrument measurements without recording connection addresses."""
    if isinstance(value, dict):
        return {
            key: portable_metadata(item)
            for key, item in value.items()
            if key not in ("port", "scope_host")
        }
    if isinstance(value, list):
        return [portable_metadata(item) for item in value]
    if isinstance(value, str):
        return "\n".join(line for line in value.split("\n") if not line.startswith("Host:"))
    return value


def save(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(portable_metadata(document), indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


async def collect(args):
    if not args.confirm_50ohm:
        raise ValueError(
            "Attach external 50-ohm terminations at scope CH1/CH3, then use --confirm-50ohm"
        )
    frequencies = sorted(args.frequencies or FREQUENCIES)
    amplitudes = sorted(args.amplitudes or AMPLITUDES)
    if len(set(frequencies)) != len(frequencies) or len(set(amplitudes)) != len(amplitudes):
        raise ValueError("Calibration frequencies and amplitudes must be unique")
    if not all(1e6 <= f <= 15e6 for f in frequencies):
        raise ValueError("Calibration frequencies must be in 1..15 MHz")
    if not all(0.02 <= a <= 5 for a in amplitudes):
        raise ValueError("Calibration amplitudes must be in 0.02..5 Vpp")
    measurement_plan = {
        "frequencies_hz": frequencies,
        "amplitudes_vpp": amplitudes,
        "acquisition": args.acquire_type,
        "repeats": args.repeats,
        "settle_seconds": args.settle,
    }
    document = {
        "schema_version": 1,
        "status": "incomplete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "load_ohms": 50,
        "load_description": "External 50-ohm terminations at scope CH1 and CH3; operator confirmed",
        "waveform": "SINE",
        "offset_v": 0,
        "measurement_plane": "Scope input after the existing direct coax cables; cable loss included",
        "method": f"Median of AC RMS = sqrt(VRMS^2 - VAVG^2); scope acquisition {args.acquire_type}",
        "measurement_plan": measurement_plan,
        "channels": {str(c): {"scope_channel": s, "curves": []} for c, s in ((1, 1), (2, 3))},
    }
    if args.resume and args.out.exists():
        document = json.loads(args.out.read_text())
        if document["load_ohms"] != 50 or document["status"] != "incomplete":
            raise ValueError("Resume requires an incomplete 50-ohm calibration")
        if document.get("measurement_plan") != measurement_plan:
            raise ValueError(
                "Resume requires the original measurement grid and acquisition settings"
            )
        document.pop("error", None)
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
        info = await call(generator, "get_device_info")
        if args.resume and document.get("device", {}).get("serial_number") != info["serial_number"]:
            raise ValueError("Cannot resume calibration on a different generator")
        document["device"] = info
        if document["device"]["device_type"] != 15:
            raise ValueError("This calibration procedure is for the attached 15 MHz unit")
        document["calibration_id"] = (
            f"jds2800-{document['device']['serial_number']}-50ohm-{document['created_at']}"
        )
        document["initial_state"] = await call(generator, "get_state")
        scope_info = await call(scope, "scope_info")
        if args.resume:
            previous_scope = document.get("scope_info", "").splitlines()
            if not previous_scope or previous_scope[0] != scope_info.splitlines()[0]:
                raise ValueError("Resume requires the original scope identity")
        document["scope_info"] = scope_info
        save(args.out, document)
        try:
            await call(generator, "stop_outputs")
            await call(generator, "set_mode", {"mode": "WAVE_CH1"})
            await write_scope(
                scope,
                [
                    ":CHAN1:DISP ON",
                    ":CHAN3:DISP ON",
                    ":CHAN2:DISP OFF",
                    ":CHAN4:DISP OFF",
                    ":CHAN1:PROB 1",
                    ":CHAN3:PROB 1",
                    ":CHAN1:COUP DC",
                    ":CHAN3:COUP DC",
                    ":CHAN1:OFFS 0",
                    ":CHAN3:OFFS 0",
                    ":CHAN1:BWL OFF",
                    ":CHAN3:BWL OFF",
                    ":TIM:MAIN:OFFS 0",
                    f":ACQ:TYPE {args.acquire_type}",
                    ":ACQ:AVER 16",
                    ":TRIG:EDG:LEV 0",
                    ":TRIG:EDG:SLOP POS",
                    ":TRIG:SWE AUTO",
                    ":RUN",
                ],
            )
            completed = sum(
                len(curve["points"])
                for ch in document["channels"].values()
                for curve in ch["curves"]
            )
            total = 2 * len(frequencies) * len(amplitudes)
            for channel, scope_channel in ((1, 1), (2, 3)):
                await call(generator, "stop_outputs")
                await write_scope(scope, [f":TRIG:EDG:SOUR CHAN{scope_channel}"])
                for frequency in frequencies:
                    curves = document["channels"][str(channel)]["curves"]
                    curve = next((c for c in curves if c["frequency_hz"] == frequency), None)
                    if curve is None:
                        curve = {"frequency_hz": frequency, "points": []}
                        curves.append(curve)
                    for amplitude in amplitudes:
                        if any(p["setting_vpp"] == amplitude for p in curve["points"]):
                            continue
                        scale = scope_scale(amplitude / 2)
                        await write_scope(
                            scope,
                            [
                                f":CHAN{scope_channel}:SCAL {scale}",
                                f":TIM:MAIN:SCAL {1 / frequency}",
                            ],
                        )
                        state = await call(
                            generator,
                            "configure_channel",
                            {
                                "channel": channel,
                                "waveform": "SINE",
                                "frequency_hz": frequency,
                                "amplitude_vpp": amplitude,
                                "offset_v": 0,
                                "duty_percent": 50,
                                "enabled": True,
                            },
                        )
                        await asyncio.sleep(args.settle)
                        point = await measure(scope, scope_channel, frequency, args.repeats)
                        if point["repeatability_db"] > 0.3:
                            await asyncio.sleep(1)
                            point = await measure(scope, scope_channel, frequency, args.repeats)
                        if point["repeatability_db"] > 0.3:
                            raise RuntimeError(f"Unstable measurement: {point}")
                        if not 0.2 < point["vpp_v"] / amplitude < 0.8:
                            raise RuntimeError(f"Unexpected loading/connection: {point}")
                        if (
                            curve["points"]
                            and point["measured_dbm"] <= curve["points"][-1]["measured_dbm"]
                        ):
                            raise RuntimeError("Measured power is not monotonic with amplitude")
                        point.update(setting_vpp=state["amplitude_vpp"], scope_scale_v_div=scale)
                        curve["points"].append(point)
                        completed += 1
                        save(args.out, document)
                        print(
                            json.dumps(
                                {
                                    "progress": f"{completed}/{total}",
                                    "channel": channel,
                                    "frequency_hz": frequency,
                                    "setting_vpp": amplitude,
                                    "measured_dbm": round(point["measured_dbm"], 3),
                                }
                            ),
                            flush=True,
                        )
            document["status"] = "measured"
        except BaseException as exc:
            document["error"] = str(exc)
            raise
        finally:
            try:
                await call(generator, "stop_outputs")
                document["final_state"] = await call(generator, "get_state")
            finally:
                save(args.out, document)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--scope-host", required=True, help="Hostname or IP address of the scope")
    parser.add_argument("--rigol-server", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-50ohm", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--frequencies", type=float, nargs="+")
    parser.add_argument("--amplitudes", type=float, nargs="+")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--settle", type=float, default=0.6)
    parser.add_argument("--acquire-type", choices=("NORM", "AVER"), default="NORM")
    args = parser.parse_args()
    if not 2 <= args.repeats <= 10 or not 0.2 <= args.settle <= 5:
        parser.error("Use 2..10 repeats and 0.2..5 seconds settling time")
    asyncio.run(collect(args))


if __name__ == "__main__":
    main()
