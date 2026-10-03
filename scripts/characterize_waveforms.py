#!/usr/bin/env python3
"""Characterize SINE/SQUARE/CMOS using numeric scope readings and RAW traces via MCP.

This produces evidence, not an installable CMOS power calibration. Physical 50-ohm
loads at Rigol CH1/CH3 are required. Outputs are disabled on completion/failure.
"""

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

from jds2800_mcp.calibrate import call, connect, save, scope_scale, write_scope

ITEMS = [
    "VRMS",
    "VAVG",
    "VPP",
    "FREQuency",
    "VMAX",
    "VMIN",
    "VTOP",
    "VBASe",
    "VAMP",
    "PDUTy",
    "RTIMe",
    "FTIMe",
]


async def collect(args):
    if not args.confirm_50ohm:
        raise ValueError("Physical 50-ohm loads at scope CH1/CH3 must be confirmed")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete",
        "load_ohms": 50,
        "measurement_plane": "Scope inputs after existing coax cables; external 50-ohm loads confirmed",
        "voltage_source": "Numeric :MEAS:ITEM? VRMS/VAVG/VPP queries, never screen grid estimates",
        "acquisition": "NORM, DC coupling, probe 1, bandwidth limit OFF, 60000-point RAW captures",
        "cases": [],
    }
    if args.resume and args.out.exists():
        report = json.loads(args.out.read_text())
        if report.get("load_ohms") != 50:
            raise ValueError("Resumed report has a different load")
        report.pop("error", None)
        report.pop("final_state", None)
        report["status"] = "incomplete"
        report.setdefault("resumed_at", []).append(datetime.now(timezone.utc).isoformat())
    env = dict(os.environ)
    async with AsyncExitStack() as stack:
        gen = await connect(stack, sys.executable, ["-m", "jds2800_mcp.server"], env)
        scope = await connect(
            stack,
            sys.executable,
            [str(args.rigol_server)],
            env
            | {
                "RIGOL_HOST": args.scope_host,
                "RIGOL_OUT_DIR": str(args.out.parent / "waveform-captures"),
            },
        )
        device = await call(gen, "get_device_info")
        if (
            args.resume
            and "device" in report
            and any(
                report["device"][key] != device[key] for key in ("serial_number", "device_type")
            )
        ):
            raise ValueError("Resumed report is for a different generator")
        report["device"] = device
        report["initial_state"] = await call(gen, "get_state")
        scope_info = await call(scope, "scope_info")
        if args.resume and "scope_initial_info" in report:
            if report["scope_initial_info"].splitlines()[0] != scope_info.splitlines()[0]:
                raise ValueError("Resumed report is for a different scope")
        report["scope_initial_info"] = scope_info
        try:
            await call(gen, "stop_outputs")
            await call(gen, "set_mode", {"mode": "WAVE_CH1"})
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
                    ":CHAN1:BWL OFF",
                    ":CHAN3:BWL OFF",
                    ":CHAN1:OFFS 0",
                    ":CHAN3:OFFS 0",
                    ":TIM:MAIN:OFFS 0",
                    ":ACQ:TYPE NORM",
                    ":TRIG:COUP DC",
                    ":TRIG:EDG:SLOP POS",
                    ":TRIG:SWE AUTO",
                    ":RUN",
                ],
            )
            report["memory"] = await call(scope, "set_acquire", {"mem_depth": "60000"})
            cases = [(wave, f * 1e6, 2.0) for wave in ("SINE", "SQUARE") for f in (1, 5, 10, 15)]
            cases += [("CMOS", f * 1e6, a) for f in (1, 3, 6) for a in (1.0, 2.0, 4.0)]
            for channel, sch in ((1, 1), (2, 3)):
                await call(gen, "stop_outputs")
                for waveform, frequency, amplitude in cases:
                    if any(
                        c["generator_channel"] == channel
                        and c["waveform"] == waveform
                        and c["frequency_setting_hz"] == frequency
                        and c["amplitude_setting_vpp"] == amplitude
                        for c in report["cases"]
                    ):
                        continue
                    scale = 2.0 if waveform == "CMOS" else scope_scale(amplitude / 2)
                    initial_offset = -2.5 if waveform == "CMOS" else 0
                    await write_scope(
                        scope,
                        [
                            f":CHAN{sch}:SCAL {scale}",
                            f":CHAN{sch}:OFFS {initial_offset}",
                            f":TRIG:EDG:SOUR CHAN{sch}",
                            ":TRIG:EDG:LEV 0",
                            f":TIM:MAIN:SCAL {1 / frequency}",
                            ":RUN",
                        ],
                    )
                    state = await call(
                        gen,
                        "configure_channel",
                        {
                            "channel": channel,
                            "waveform": waveform,
                            "frequency_hz": frequency,
                            "amplitude_vpp": amplitude,
                            "offset_v": 0,
                            "duty_percent": 50,
                            "enabled": True,
                        },
                    )
                    await asyncio.sleep(0.8)
                    # Use measured extrema to center unipolar CMOS and catch clipping.
                    bounds = await call(
                        scope, "get_stats", {"channel": str(sch), "items": ["VMAX", "VMIN", "VAVG"]}
                    )
                    b = bounds["measurements"]
                    if b["VMAX"] is None or b["VMIN"] is None:
                        raise RuntimeError(f"Missing measured bounds: {b}")
                    center = (b["VMAX"] + b["VMIN"]) / 2
                    scale = scope_scale(b["VMAX"] - b["VMIN"])
                    # Wait for acknowledgement before closing the scope connection.
                    # Clear the broad pilot offset before reducing vertical scale.
                    await write_scope(
                        scope,
                        [
                            f":CHAN{sch}:OFFS 0",
                            f":CHAN{sch}:SCAL {scale}",
                            f":CHAN{sch}:OFFS {-center}",
                            f":TRIG:EDG:SOUR CHAN{sch}",
                            f":TRIG:EDG:LEV {center}",
                            ":TRIG:EDG:SLOP POS",
                            ":TRIG:SWE AUTO",
                        ],
                    )
                    await asyncio.sleep(0.5)
                    readings = []
                    for _ in range(3):
                        await write_scope(scope, [":MEAS:CLE ALL"])
                        stats = await call(
                            scope, "get_stats", {"channel": str(sch), "items": ITEMS}
                        )
                        r = stats["measurements"]
                        if r["VMAX"] >= center + 3.7 * scale or r["VMIN"] <= center - 3.7 * scale:
                            raise RuntimeError(f"Clipped waveform: {r}")
                        for name in ("VRMS", "VAVG", "VPP", "FREQuency"):
                            if r[name] is None or not math.isfinite(r[name]):
                                raise RuntimeError(f"Unmeasurable voltage/frequency: {r}")
                        if abs(r["FREQuency"] / frequency - 1) > 0.2:
                            raise RuntimeError(f"Wrong frequency: {r}")
                        ac2 = r["VRMS"] ** 2 - r["VAVG"] ** 2
                        if ac2 <= 0:
                            raise RuntimeError(f"Invalid AC RMS: {r}")
                        r["ac_power_dbm"] = 10 * math.log10(ac2 / 0.05)
                        r["total_power_dbm"] = 10 * math.log10(r["VRMS"] ** 2 / 0.05)
                        readings.append(r)
                        await asyncio.sleep(0.1)
                    raw = await call(
                        scope,
                        "get_waveform",
                        {
                            "channel": str(sch),
                            "mode": "RAW",
                            "single": True,
                            "save_csv": True,
                            "preview_points": 0,
                        },
                    )
                    raw["csv_path"] = Path(raw["csv_path"]).relative_to(args.out.parent).as_posix()
                    case = {
                        "generator_channel": channel,
                        "scope_channel": sch,
                        "waveform": waveform,
                        "frequency_setting_hz": frequency,
                        "amplitude_setting_vpp": amplitude,
                        "state_readback": state,
                        "measured_at": datetime.now(timezone.utc).isoformat(),
                        "scope_scale_v_div": scale,
                        "scope_offset_v": -center,
                        "scope_info": await call(scope, "scope_info"),
                        "readings": readings,
                        "median": {
                            key: statistics.median(r[key] for r in readings if r[key] is not None)
                            if any(r[key] is not None for r in readings)
                            else None
                            for key in readings[0]
                        },
                        "raw_capture": raw,
                    }
                    case["repeatability_db"] = max(r["ac_power_dbm"] for r in readings) - min(
                        r["ac_power_dbm"] for r in readings
                    )
                    report["cases"].append(case)
                    save(args.out, report)
                    print(
                        json.dumps(
                            {
                                "case": len(report["cases"]),
                                "channel": channel,
                                "waveform": waveform,
                                "frequency_hz": frequency,
                                "amplitude_vpp": amplitude,
                                "ac_power_dbm": case["median"]["ac_power_dbm"],
                            }
                        ),
                        flush=True,
                    )
                    await write_scope(scope, [":RUN"])
            report["status"] = "measured"
        except BaseException as exc:
            report["error"] = str(exc)
            raise
        finally:
            try:
                await call(gen, "stop_outputs")
                report["final_state"] = await call(gen, "get_state")
            finally:
                save(args.out, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-host", required=True)
    parser.add_argument("--rigol-server", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--confirm-50ohm", action="store_true")
    parser.add_argument("--resume", action="store_true")
    asyncio.run(collect(parser.parse_args()))
