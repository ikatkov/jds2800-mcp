#!/usr/bin/env python3
"""Plot measured square/sine comparisons from completed calibration profiles (offline)."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parents[1]
square = json.loads((root / "src/jds2800_mcp/data/square-calibration.json").read_text())
sine = json.loads((root / "src/jds2800_mcp/data/calibration.json").read_text())
fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True, layout="constrained")
colors = {"1": "#1666a8", "2": "#ae4b18"}
for ch in ("1", "2"):
    sf, sp, delta = [], [], []
    sine_curves = {c["frequency_hz"]: c for c in sine["channels"][ch]["curves"]}
    for c in square["channels"][ch]["curves"]:
        sq = next(p for p in c["points"] if p["setting_vpp"] == 2)
        si = next(p for p in sine_curves[c["frequency_hz"]]["points"] if p["setting_vpp"] == 2)
        sf.append(c["frequency_hz"] / 1e6)
        sp.append(sq["measured_dbm"])
        delta.append(sq["measured_dbm"] - si["measured_dbm"])
    axes[0].plot(sf, sp, "o-", ms=4, color=colors[ch], label=f"Generator output {ch}")
    axes[1].plot(sf, delta, "o-", ms=4, color=colors[ch], label=f"Generator output {ch}")
axes[0].set_title("Measured square-wave AC power at a 2 Vpp generator setting", loc="left")
axes[0].set_ylabel("AC power into 50 Ω (dBm)")
axes[1].set_title("Square minus sine at the same generator setting", loc="left")
axes[1].set_ylabel("Power difference (dB)")
axes[1].axhline(
    3.0103, color="#666666", ls="--", lw=1, label="Ideal comparison: +3.01 dB at equal measured Vpp"
)
axes[1].set_xlabel("Generator frequency setting (MHz)")
for ax in axes:
    ax.grid(alpha=0.2)
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlim(0.7, 15.3)
fig.suptitle("JDS2800-15M · separate measured channel tables", fontsize=13)
fig.text(
    0.01,
    -0.02,
    "Numeric Rigol RMS/VAVG readings, 50 Ω loads. Scope bandwidth: 100 MHz.\nIncludes measured harmonics within scope response; excludes DC. Sine measurements were collected earlier.",
    fontsize=8,
)
for suffix in ("png", "svg"):
    fig.savefig(root / f"artifacts/square-power-calibration.{suffix}", dpi=160, bbox_inches="tight")
print("Rendered calibration comparison")
