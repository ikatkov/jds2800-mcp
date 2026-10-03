#!/usr/bin/env python3
"""Fit measured RAW scope voltages to DC and harmonic components (offline, NumPy).

No instrument control. Numeric scope RMS readings remain the source of calibrated
power; this supplemental analysis separates measured fundamental/harmonic content.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np


def rising_crossings(t, y, level, hysteresis):
    """Use measured voltage hysteresis to reject noise near the crossing level."""
    crossings = []
    armed = False
    for index in range(len(y) - 1):
        if y[index] < level - hysteresis:
            armed = True
        if armed and y[index] < level <= y[index + 1]:
            crossings.append(
                t[index]
                + (level - y[index]) / (y[index + 1] - y[index]) * (t[index + 1] - t[index])
            )
            armed = False
    return np.asarray(crossings)


def analyze(path):
    doc = json.loads(path.read_text())
    for case in doc["cases"]:
        raw = case["raw_capture"]
        t, y = np.loadtxt(path.parent / raw["csv_path"], delimiter=",", skiprows=1).T
        # Crossings determine frequency in the scope's own timebase. This is not
        # a calibrated absolute frequency measurement.
        low, high = np.percentile(y, [5, 95])
        level = (low + high) / 2
        crossings = rising_crossings(t, y, level, (high - low) * 0.2)
        if len(crossings) < 20:
            raise ValueError("Insufficient measured periods")
        period = np.polyfit(np.arange(len(crossings)), crossings, 1)[0]
        frequency = float(1 / period)
        if abs(frequency / case["frequency_setting_hz"] - 1) > 0.01:
            raise ValueError(
                f"Unexpected raw-capture frequency {frequency:g} Hz: "
                f"CH{case['generator_channel']} {case['waveform']} "
                f"at {case['frequency_setting_hz']:g} Hz"
            )
        # Clip to integer periods to avoid DC/leakage in RMS comparison. A joint
        # least-squares fit handles residual noninteger sample-window leakage.
        start = crossings[5]
        finish = crossings[-6]
        use = (t >= start) & (t < finish)
        t, y = t[use] - start, y[use]
        nyquist = 1 / (2 * raw["x_increment_s"])
        harmonic_limit = min(15, int(90e6 / frequency), int(0.9 * nyquist / frequency))
        columns = [np.ones_like(t)]
        for order in range(1, harmonic_limit + 1):
            angle = 2 * np.pi * order * frequency * t
            columns.extend((np.sin(angle), np.cos(angle)))
        design = np.column_stack(columns)
        coefs = np.linalg.lstsq(design, y, rcond=None)[0]
        harmonics = []
        for order in range(1, harmonic_limit + 1):
            rms = float(np.hypot(coefs[2 * order - 1], coefs[2 * order]) / np.sqrt(2))
            harmonics.append(
                {
                    "order": order,
                    "frequency_hz_scope_timebase": frequency * order,
                    "vrms_v": rms,
                    "power_dbm_into_50ohm": 10 * math.log10(rms**2 / 0.05),
                }
            )
        numeric_ac_power = 0.001 * 10 ** (case["median"]["ac_power_dbm"] / 10)
        fundamental_w = harmonics[0]["vrms_v"] ** 2 / 50
        raw_rms = float(np.std(y))
        case["spectral_analysis"] = {
            "frequency_hz_scope_timebase": frequency,
            "frequency_method": "Linear fit to rising mid-voltage crossings with 20%-span arming hysteresis",
            "method": "Joint least-squares fit of DC plus harmonics up to 90 MHz / 15th order",
            "bandwidth_note": "Scope analog response is nominally 100 MHz; high harmonics are attenuated. No ideal-wave correction applied.",
            "fitted_dc_v": float(coefs[0]),
            "raw_ac_vrms_v": raw_rms,
            "raw_ac_power_dbm": 10 * math.log10(raw_rms**2 / 0.05),
            "numeric_vs_raw_rms_db": 20 * math.log10(raw_rms)
            - 10 * math.log10(numeric_ac_power * 50),
            "fundamental_power_dbm": harmonics[0]["power_dbm_into_50ohm"],
            "fundamental_fraction_of_numeric_ac_power": fundamental_w / numeric_ac_power,
            "harmonics": harmonics,
            "residual_vrms_v": float(np.std(y - design @ coefs)),
        }
    out = path.with_name(path.stem + "-analyzed.json")
    out.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"cases": len(doc["cases"]), "output": str(out)}))
    return doc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    analyze(parser.parse_args().input)
