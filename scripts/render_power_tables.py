#!/usr/bin/env python3
"""Regenerate measured Markdown tables and CSV, preserving the power guide context."""

import argparse
import csv
import json
import math
from pathlib import Path

from jds2800_mcp.power import Calibration


def render(profile_path, guide_path, csv_path):
    document = json.loads(profile_path.read_text())
    calibration = Calibration(document)
    channels = document["channels"]
    guide = guide_path.read_text()
    preamble = guide.split("| Channel | Frequency range |", 1)[0]
    evidence = guide.split("## Evidence and repeatability", 1)[1]
    lines = [
        preamble.rstrip(),
        "",
        "| Channel | Frequency range | Power range supported at every measured frequency |",
        "| --- | --- | --- |",
    ]
    for channel, summary in calibration.summary()["channels"].items():
        low, high = summary["power_range_dbm_across_all_frequencies"]
        lines.append(f"| {channel} | 1–15 MHz | {low:.3f} to {high:.3f} dBm |")
    if "verification" in document:
        verification = document["verification"]
        lines += [
            "",
            f"Independent verification passed **{verification['checks']} checks** from -25 to +10 dBm,",
            f"with a maximum absolute difference of **{verification['maximum_absolute_error_db']:.3f} dB**",
            "from requested power. These checks include intermediate frequencies, the 10 MHz",
            "boundary, both outputs together, and the scripting CLI while MCP is running.",
            "This observed agreement is relative to this scope and applies to the checked cases;",
        ]
        lines += ["it is not a certified absolute accuracy specification."]
    lines += [
        "",
        "## Voltage measurements and settings near 0 dBm",
        "",
        "The voltage and measured-power columns were measured at a fixed generator setting",
        "of **1.265 Vpp**. The setting columns are interpolated for 0 dBm into 50 ohms.",
        "",
        "| MHz | CH1 measured Vpp | CH1 AC RMS (V) | CH1 dBm | CH1 0 dBm setting (Vpp) | CH2 measured Vpp | CH2 AC RMS (V) | CH2 dBm | CH2 0 dBm setting (Vpp) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, curve in enumerate(channels["1"]["curves"]):
        frequency = curve["frequency_hz"]
        row = [f"{frequency / 1e6:g}"]
        for channel in (1, 2):
            other = channels[str(channel)]["curves"][index]
            if other["frequency_hz"] != frequency:
                raise ValueError("Channels have different frequency grids")
            point = next(p for p in other["points"] if p["setting_vpp"] == 1.265)
            plan = calibration.plan(channel, frequency, 0)
            row += [
                f"{point['vpp_v']:.6f}",
                f"{point['vrms_ac_v']:.6f}",
                f"{point['measured_dbm']:+.3f}",
                f"{plan['amplitude_vpp']:.3f}",
            ]
        lines.append("| " + " | ".join(row) + " |")
    for channel in ("1", "2"):
        curves = channels[channel]["curves"]
        amplitudes = [p["setting_vpp"] for p in curves[0]["points"]]
        lines += [
            "",
            f"## Channel {channel}: measured power table",
            "",
            "Column headings are generator voltage settings in Vpp. Values are measured",
            "AC power in dBm across the 50-ohm load.",
            "",
            "| Frequency (MHz) | " + " | ".join(f"{a:g} Vpp" for a in amplitudes) + " |",
            "| " + " | ".join(["---"] * (len(amplitudes) + 1)) + " |",
        ]
        for curve in curves:
            row = [f"{curve['frequency_hz'] / 1e6:g}"] + [
                f"{p['measured_dbm']:+.3f}" for p in curve["points"]
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Evidence and repeatability" + evidence]
    guide_path.write_text("\n".join(lines).rstrip() + "\n")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "generator_channel",
                "scope_channel",
                "frequency_hz",
                "setting_vpp",
                "measured_ac_vrms",
                "measured_vpp",
                "dc_v",
                "measured_dbm_into_50ohm",
                "vpp_sine_dbm",
                "repeatability_db",
                "acquisition",
            ]
        )
        for channel, data in channels.items():
            for curve in data["curves"]:
                for point in curve["points"]:
                    writer.writerow(
                        [
                            channel,
                            data["scope_channel"],
                            curve["frequency_hz"],
                            point["setting_vpp"],
                            point["vrms_ac_v"],
                            point["vpp_v"],
                            point["dc_v"],
                            point["measured_dbm"],
                            10 * math.log10(point["vpp_v"] ** 2 / 0.4),
                            point["repeatability_db"],
                            point["acquisition"],
                        ]
                    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=Path, default=Path("src/jds2800_mcp/data/calibration.json")
    )
    parser.add_argument(
        "--guide", type=Path, default=Path("src/jds2800_mcp/docs/JDS2800-power-calibration.md")
    )
    parser.add_argument("--csv", type=Path, default=Path("artifacts/power-calibration.csv"))
    args = parser.parse_args()
    render(args.profile, args.guide, args.csv)
