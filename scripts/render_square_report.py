#!/usr/bin/env python3
"""Render the measured square profile and verification into its bundled MCP guide."""

import argparse
import json
from pathlib import Path

from jds2800_mcp.power import Calibration


def render(profile_path, guide_path, characterization_path=None):
    doc = json.loads(profile_path.read_text())
    calibration = Calibration(doc)
    calibration.require_waveform("SQUARE")
    summary = calibration.summary()
    lines = [
        "# Measured JDS2800 square-wave power calibration",
        "",
        f"Device: JDS2800-15M, serial **{doc['device']['serial_number']}**. Measured October 3, 2026.",
        "Generator CH1 feeds Rigol CH1; generator CH2 feeds Rigol CH3, through the existing",
        "coax cables with external **50-ohm terminations at the scope inputs**. The operator",
        "confirmed both loads. Numeric scope voltage readings supply every power value.",
        "Scope: Rigol DS1104Z, serial DS1ZA225013504, 100 MHz analog bandwidth,",
        "500 MSa/s with two channels, DC coupling, probe factor 1, bandwidth limit OFF.",
        "",
        "## MCP use",
        "",
        'Call `get_calibration(waveform="SQUARE")` to inspect coverage, then use',
        "`preview_power` and `set_power` with the same waveform argument. Example:",
        "",
        "```json",
        '{"channel":1,"frequency_hz":10000000,"power_dbm":7,"waveform":"SQUARE","enabled":true}',
        "```",
        "",
        "The default waveform remains SINE. The square table is selected separately; the",
        "sine table is never converted or reused. Square output sets 50% duty and zero",
        "requested DC offset. Device serial, frequency and power coverage are checked",
        "before any writes. Output is gated while configuring and readback is verified.",
        "Output enable state is preserved unless `enabled` is supplied. The physical",
        "50-ohm load and measured cables are required. CMOS/PULSE/different duty cycles",
        "have no calibrated dBm control. Existing MCP clients must reconnect to refresh",
        "the tool schema and load the updated server code.",
        "",
        "Resources: `jds2800://calibration/square` and `jds2800://square-power-guide`.",
        "The bundled table is `data/square-calibration.json`. A measured replacement",
        "can be selected with `JDS2800_SQUARE_CALIBRATION`; the existing",
        "`JDS2800_CALIBRATION` variable remains exclusive to the sine profile.",
        "",
        "## What power means",
        "",
        "**AC RMS power including harmonics passed by the scope's analog response,",
        "with DC removed**. This is neither fundamental-only RF power nor an",
        "infinite-bandwidth measurement of ideal-square total power.",
        "",
        "At each point the scope returns numeric `VRMS`, `VAVG`, `VPP`, and frequency",
        "three times. Each repeated numeric reading uses the current acquisition;",
        "`:MEAS:CLE ALL` removes prior displayed measurement items before querying.",
        "The grid is never used to estimate voltage. The median measured power is:",
        "",
        "```text",
        "AC_RMS = sqrt(VRMS^2 - VAVG^2)",
        "P_AC_W = (VRMS^2 - VAVG^2) / 50",
        "P_AC_dBm = 10 * log10(P_AC_W / 0.001)",
        "P_total_with_DC_W = VRMS^2 / 50",
        "```",
        "",
        "The total-with-DC values in raw evidence have the same scope bandwidth limit.",
        "Do not substitute the sine Vpp formula, square Vpp formula, or a +3 dB offset",
        "for the measured RMS. Actual edge shape, overshoot and frequency response matter.",
        "The raw collector's `vpp_sine_dbm` is a sine-only diagnostic, not square power;",
        "it is omitted from the bundled square table.",
        "A returned `predicted_power_dbm` is a table prediction after 1 mV amplitude",
        "rounding, not a fresh scope measurement. `scope_verified_now` is false for ordinary calls.",
        "",
        "An ideal bipolar 50%-duty square has harmonic voltage proportional to 1/n",
        "for odd n, and harmonic power proportional to 1/n². The infinite sum converges:",
        "the fundamental contains 8/pi² = 81.06% of AC power. All higher harmonics",
        "together contain 18.94%, adding 0.912 dB above fundamental-only power.",
        "At equal measured Vpp, ideal square AC power is twice ideal sine power (+3.010 dB).",
        "These are analytical comparisons, not corrections applied to this measured table.",
        "",
        "The scope's nominal bandwidth is 100 MHz at -3 dB, not a brick-wall cutoff.",
        "It attenuates high harmonics. Finite generator edge speed also changes the spectrum.",
        "The optional RAW-capture analysis separates fundamental/harmonic content within",
        "the same scope response; it cannot establish power beyond that response.",
        "For an absolute broadband power specification, use a suitable characterized",
        "broadband power meter or calibrated spectrum measurement instead of declaring",
        "this scope calibration to be infinite-bandwidth total power.",
        "",
        "## Coverage and verification",
        "",
        "16 frequency knots per channel: 1–15 MHz at integer MHz plus 10.01 MHz.",
        "Ten amplitude settings per frequency: 0.04, 0.126, 0.2, 0.4, 0.6, 0.8,",
        "1.265, 2, 3, and 5 Vpp, giving **320 measured points and 960 numeric reading sets**.",
        "Acquisition uses NORM, not waveform averaging. RMS includes the actual measured",
        "noise/harmonics. Interpolation uses measured dBm versus log amplitude and log",
        "frequency, separately for each output. No level/frequency extrapolation is allowed.",
        "",
        "| Generator output | Frequency range | AC power range supported at every measured frequency |",
        "| --- | --- | --- |",
    ]
    for ch, info in summary["channels"].items():
        lo, hi = info["power_range_dbm_across_all_frequencies"]
        lines.append(f"| {ch} | 1–15 MHz | {lo:.3f} to {hi:.3f} dBm |")
    if "verification" in doc:
        v = doc["verification"]
        lines += [
            "",
            f"Independent hardware verification passed **{v['checks']} MCP checks** plus",
            f"**{v['additional_cli_scope_checks']} CLI/scope checks**, with maximum absolute",
            f"difference **{v['maximum_absolute_error_db']:.3f} dB** from requested power.",
            f"Acceptance tolerance was {v['tolerance_db']:.2f} dB, relative to this same scope.",
            f"Checked requests span {v['requested_power_range_dbm'][0]:g} to "
            f"{v['requested_power_range_dbm'][1]:+g} dBm, both channels, intermediate frequencies,",
            "the 10 MHz boundary, and both outputs enabled together. This is measured",
            "agreement for the checked cases, not a traceable absolute accuracy specification.",
        ]
    if characterization_path and characterization_path.exists():
        evidence = json.loads(characterization_path.read_text())
        if evidence.get("status") == "measured":
            lines += [
                "",
                "## Supplemental measured harmonic content",
                "",
                "These separate captures use a 2 Vpp generator setting. The AC-power",
                "column comes from numeric scope readings; fundamental power comes from",
                "a fit to measured RAW scope voltages. The remainder includes higher",
                "harmonics and measured noise within the same scope response.",
                "These captures do not replace the calibration table or establish",
                "power outside the scope's bandwidth.",
                "",
                "| Output | MHz | Square AC dBm | Fitted fundamental dBm | Fundamental fraction of measured AC |",
                "| --- | --- | --- | --- | --- |",
            ]
            for case in evidence["cases"]:
                if case["waveform"] != "SQUARE":
                    continue
                spectral = case["spectral_analysis"]
                lines.append(
                    f"| {case['generator_channel']} | {case['frequency_setting_hz'] / 1e6:g} | "
                    f"{case['median']['ac_power_dbm']:+.3f} | "
                    f"{spectral['fundamental_power_dbm']:+.3f} | "
                    f"{100 * spectral['fundamental_fraction_of_numeric_ac_power']:.2f}% |"
                )
            lines += [
                "",
                "## CMOS measurements",
                "",
                "CMOS was measured separately at 1, 3 and 6 MHz with three amplitude",
                "settings on each output. Both columns are computed from numeric scope",
                "voltage readings. Total power includes DC; AC power removes DC.",
                "These 18 cases characterize CMOS; they are not an interpolation table",
                "for calibrated CMOS dBm control. The MCP rejects CMOS power requests.",
                "",
                "| Output | MHz | Setting Vpp | Measured Vpp | Numeric RMS V | Numeric average V | AC dBm | Including DC dBm |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            for case in evidence["cases"]:
                if case["waveform"] != "CMOS":
                    continue
                m = case["median"]
                lines.append(
                    f"| {case['generator_channel']} | {case['frequency_setting_hz'] / 1e6:g} | "
                    f"{case['amplitude_setting_vpp']:g} | {m['VPP']:.6f} | "
                    f"{m['VRMS']:.6f} | {m['VAVG']:.6f} | "
                    f"{m['ac_power_dbm']:+.3f} | {m['total_power_dbm']:+.3f} |"
                )
    lines += [
        "",
        "## Numeric voltage readings at a 2 Vpp generator setting",
        "",
        "Both voltage columns below come from numeric scope readings, not grid estimates.",
        "The setting-for-7-dBm column is interpolated from the measured table.",
        "",
        "| Output | MHz | Measured Vpp (V) | Measured AC RMS (V) | Measured AC dBm | Setting for +7 dBm (Vpp) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for ch, data in doc["channels"].items():
        for curve in data["curves"]:
            p = next(p for p in curve["points"] if p["setting_vpp"] == 2)
            f = curve["frequency_hz"]
            setting = calibration.plan(int(ch), f, 7)["amplitude_vpp"]
            lines.append(
                f"| {ch} | {f / 1e6:g} | {p['vpp_v']:.6f} | {p['vrms_ac_v']:.6f} | {p['measured_dbm']:+.3f} | {setting:.3f} |"
            )
    for ch, data in doc["channels"].items():
        amplitudes = [p["setting_vpp"] for p in data["curves"][0]["points"]]
        lines += [
            "",
            f"## Output {ch}: measured AC power table",
            "",
            "Columns are generator amplitude settings. Entries are measured AC dBm into 50 ohms.",
            "",
            "| MHz | " + " | ".join(f"{a:g} Vpp" for a in amplitudes) + " |",
            "| " + " | ".join(["---"] * (len(amplitudes) + 1)) + " |",
        ]
        for curve in data["curves"]:
            lines.append(
                "| "
                + " | ".join(
                    [f"{curve['frequency_hz'] / 1e6:g}"]
                    + [f"{p['measured_dbm']:+.3f}" for p in curve["points"]]
                )
                + " |"
            )
    lines += [
        "",
        "## Evidence",
        "",
        "Raw numeric readings: `artifacts/square-power-calibration.json`.",
        "Independent requested-power checks: `artifacts/square-power-verification.json`.",
        "Supplemental SINE/SQUARE/CMOS numeric and RAW traces:",
        "`artifacts/waveform-characterization.json` and `artifacts/waveform-characterization-analyzed.json`.",
        "Reproduce supplemental acquisition with `scripts/characterize_waveforms.py`",
        "using the same scope connection arguments and `--confirm-50ohm`; `--resume`",
        "continues saved cases. Offline harmonic analysis uses",
        "`scripts/analyze_waveform_captures.py` and requires NumPy.",
        "The profile records evidence hashes. Connection addresses are excluded from",
        "portable evidence. Both outputs are disabled at the end of acquisition/verification.",
        "",
        "Repeat collection with `jds2800-calibrate --waveform SQUARE --confirm-50ohm`",
        "and the usual scope connection/output arguments. Partial runs support `--resume`.",
        "",
        "Scope specification source:",
        "[RIGOL DS1000Z datasheet](https://supportint.rigol.com/Public/Uploads/uploadfile/files/ftp/DS/%E6%89%8B%E5%86%8C/DS1000Z/EN/DS1000Z_Datasheet_EN.pdf).",
    ]
    guide_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=Path, default=Path("src/jds2800_mcp/data/square-calibration.json")
    )
    parser.add_argument(
        "--guide", type=Path, default=Path("src/jds2800_mcp/docs/JDS2800-square-calibration.md")
    )
    parser.add_argument(
        "--characterization",
        type=Path,
        default=Path("artifacts/waveform-characterization-analyzed.json"),
    )
    args = parser.parse_args()
    render(args.profile, args.guide, args.characterization)
