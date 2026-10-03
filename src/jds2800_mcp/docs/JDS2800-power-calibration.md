# Measured JDS2800 sine power calibration

Device: **JDS2800-15M, serial 1816400000**. Measured October 3, 2026.
Generator CH1 feeds Rigol CH1; generator CH2 feeds Rigol CH3 through the existing
coax cables. External **50-ohm terminations were attached at both scope inputs**,
confirmed by the operator. Scope: DS1104Z, serial DS1ZA225013504, probe factor 1,
DC coupling, bandwidth limit off. Its inputs remain high impedance behind the
external terminations.

## Set output in dBm

```sh
cd jds2800-mcp
./jds2800 calibration
./jds2800 preview-power 1 --frequency-hz 5500000 --dbm 0
./jds2800 power 1 --frequency-hz 5500000 --dbm 0 --enabled on
./jds2800 power 2 --frequency-hz 14500000 --dbm -10 --enabled on
./jds2800 stop
```

MCP equivalents: `get_calibration`, `preview_power`, and `set_power`.
Resource `jds2800://calibration` exposes metadata/ranges; `jds2800://power-guide`
exposes this guide. `get_calibration(include_points=true)` returns the complete
measured table without opening the serial port. The profile is bundled with the
Python package; an override can be supplied using `JDS2800_CALIBRATION`.

`set_power` chooses SINE, zero offset, 50% duty, and the requested frequency.
It matches the device serial, converts power to voltage using that channel's
measurements, rounds to the generator's 1 mV amplitude steps, configures with
output gating, and verifies register readback. Output enable state is preserved
unless explicitly supplied. Wave mode is required. A returned power value is a
calibrated prediction; the scope is not consulted on each normal control call.
The receiving end must present a physical 50-ohm load for the calibration to apply.

## Coverage and method

There are **16 frequency points per channel**: 1 through 15 MHz in 1 MHz steps,
plus **10.01 MHz** just above the manufacturer's amplitude-range boundary.
Ten amplitude settings at each frequency produce **320 calibration points**;
each point has three repeated scope readings. No device waveform storage was changed.

At each point, AC RMS is calculated as `sqrt(VRMS^2 - VAVG^2)` to remove the
measured DC component. Power is `10*log10(Vrms_ac^2 / 50 / 0.001)` dBm.
The stored point uses the median of three readings, with their spread retained.
The original 256 points used 16-acquisition scope averaging at scales with clear
signals. The 64 refinement points at 0.6 and 3 Vpp use normal acquisition.
Each refinement and verification reading clears previous measurements with
`:MEAS:CLE ALL`, then queries fresh numeric VRMS, VAVG, frequency, and Vpp.
Vpp also supplies a sine cross-check: `10*log10(Vpp^2 / (8*50) / 0.001)`.
The scope grid is not used to calculate voltage or power; changing its display
scale only keeps the signal within the acquisition range. Clearing measurement
items does not reset acquisition averaging history. The clear command removes
displayed measurement items; the following `:MEAS:ITEM?` queries read current
numeric values. See the [Rigol programming guide, PDF page 133](https://www.batronix.com/pdf/Rigol/ProgrammingGuide/MSO1000Z_DS1000Z_ProgrammingGuide_EN.pdf#page=133).

Independent checks use **normal acquisition**, because averaging was observed to
smear certain RF/scale combinations when the trigger did not remain stable.
See `artifacts/calibration-transition-check.json` for that reproduction.
Do not accept an unmeasurable frequency or an averaged trace that has collapsed
as evidence of low generator output.

Interpolation is piecewise linear in measured dBm versus log10 of the voltage
setting, with each amplitude knot interpolated in log frequency. It is inverted
to select the setting for requested power. **No frequency or power extrapolation**
is performed. The precise supported range depends on channel and frequency.

This measures AC power of the sine waveform including residual noise/harmonics;
it does not isolate the fundamental using a spectrum analyzer. Accuracy is relative
to the scope, termination resistance, and existing cables, with cable loss included.
Changing cables, loads, or measuring equipment can invalidate the correction.
This is not a traceable absolute RF power calibration, and does not establish the
instrument's maximum available power. Square/pulse/noise waveforms are not covered.

| Channel | Frequency range | Power range supported at every measured frequency |
| --- | --- | --- |
| 1 | 1–15 MHz | -29.859 to 11.445 dBm |
| 2 | 1–15 MHz | -29.984 to 11.213 dBm |

Independent verification passed **72 checks** from -25 to +10 dBm,
with a maximum absolute difference of **0.195 dB**
from requested power. These checks include intermediate frequencies, the 10 MHz
boundary, both outputs together, and the scripting CLI while MCP is running.
This observed agreement is relative to this scope and applies to the checked cases;
it is not a certified absolute accuracy specification.

## Voltage measurements and settings near 0 dBm

The voltage and measured-power columns were measured at a fixed generator setting
of **1.265 Vpp**. The setting columns are interpolated for 0 dBm into 50 ohms.

| MHz | CH1 measured Vpp | CH1 AC RMS (V) | CH1 dBm | CH1 0 dBm setting (Vpp) | CH2 measured Vpp | CH2 AC RMS (V) | CH2 dBm | CH2 0 dBm setting (Vpp) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.640000 | 0.224940 | +0.052 | 1.257 | 0.640000 | 0.222809 | -0.031 | 1.270 |
| 2 | 0.640000 | 0.224028 | +0.016 | 1.263 | 0.632000 | 0.222433 | -0.046 | 1.272 |
| 3 | 0.640000 | 0.223527 | -0.003 | 1.265 | 0.632000 | 0.221704 | -0.074 | 1.276 |
| 4 | 0.632000 | 0.222744 | -0.034 | 1.270 | 0.632000 | 0.221594 | -0.079 | 1.277 |
| 5 | 0.640000 | 0.223021 | -0.023 | 1.268 | 0.632000 | 0.221432 | -0.085 | 1.277 |
| 6 | 0.632000 | 0.220433 | -0.124 | 1.283 | 0.632000 | 0.219786 | -0.150 | 1.287 |
| 7 | 0.624000 | 0.221145 | -0.096 | 1.279 | 0.632000 | 0.220743 | -0.112 | 1.281 |
| 8 | 0.624000 | 0.217967 | -0.222 | 1.297 | 0.616000 | 0.215549 | -0.319 | 1.313 |
| 9 | 0.624000 | 0.217767 | -0.230 | 1.298 | 0.616000 | 0.215998 | -0.301 | 1.310 |
| 10 | 0.616000 | 0.216724 | -0.272 | 1.304 | 0.616000 | 0.215324 | -0.328 | 1.314 |
| 10.01 | 0.616000 | 0.216957 | -0.262 | 1.303 | 0.616000 | 0.215434 | -0.323 | 1.313 |
| 11 | 0.608000 | 0.214166 | -0.375 | 1.320 | 0.616000 | 0.212378 | -0.448 | 1.332 |
| 12 | 0.608000 | 0.212594 | -0.439 | 1.329 | 0.600000 | 0.211306 | -0.491 | 1.339 |
| 13 | 0.608000 | 0.212249 | -0.453 | 1.331 | 0.600000 | 0.210473 | -0.526 | 1.344 |
| 14 | 0.592000 | 0.211025 | -0.503 | 1.339 | 0.600000 | 0.209721 | -0.557 | 1.349 |
| 15 | 0.592000 | 0.208670 | -0.600 | 1.354 | 0.592000 | 0.207120 | -0.665 | 1.366 |

## Channel 1: measured power table

Column headings are generator voltage settings in Vpp. Values are measured
AC power in dBm across the 50-ohm load.

| Frequency (MHz) | 0.04 Vpp | 0.126 Vpp | 0.2 Vpp | 0.4 Vpp | 0.6 Vpp | 0.8 Vpp | 1.265 Vpp | 2 Vpp | 3 Vpp | 5 Vpp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -29.859 | -20.030 | -15.962 | -9.979 | -6.568 | -3.837 | +0.052 | +4.092 | +7.825 | +12.090 |
| 2 | -29.884 | -20.056 | -15.985 | -10.006 | -6.598 | -3.870 | +0.016 | +4.066 | +7.799 | +12.072 |
| 3 | -29.912 | -20.089 | -16.008 | -10.037 | -6.609 | -3.890 | -0.003 | +4.039 | +7.793 | +12.037 |
| 4 | -29.929 | -20.106 | -16.018 | -10.027 | -6.610 | -3.898 | -0.034 | +4.033 | +7.780 | +12.009 |
| 5 | -29.942 | -20.127 | -16.014 | -10.056 | -6.641 | -3.908 | -0.023 | +4.026 | +7.745 | +12.025 |
| 6 | -30.040 | -20.214 | -16.088 | -10.079 | -6.726 | -4.012 | -0.124 | +3.940 | +7.669 | +11.945 |
| 7 | -30.002 | -20.181 | -16.060 | -10.113 | -6.692 | -3.975 | -0.096 | +3.959 | +7.653 | +11.943 |
| 8 | -30.117 | -20.309 | -16.164 | -10.163 | -6.811 | -4.100 | -0.222 | +3.846 | +7.568 | +11.828 |
| 9 | -30.153 | -20.324 | -16.172 | -10.212 | -6.829 | -4.104 | -0.230 | +3.823 | +7.561 | +11.809 |
| 10 | -30.197 | -20.372 | -16.208 | -10.256 | -6.850 | -4.159 | -0.272 | +3.785 | +7.523 | +11.770 |
| 10.01 | -30.196 | -20.366 | -16.208 | -10.245 | -6.875 | -4.163 | -0.262 | +3.773 | +7.505 | +11.766 |
| 11 | -30.313 | -20.497 | -16.310 | -10.316 | -6.979 | -4.277 | -0.375 | +3.669 | +7.406 | +11.657 |
| 12 | -30.373 | -20.539 | -16.355 | -10.354 | -7.039 | -4.325 | -0.439 | +3.619 | +7.359 | +11.592 |
| 13 | -30.396 | -20.574 | -16.363 | -10.420 | -7.053 | -4.355 | -0.453 | +3.603 | +7.350 | +11.582 |
| 14 | -30.437 | -20.610 | -16.391 | -10.474 | -7.091 | -4.396 | -0.503 | +3.555 | +7.313 | +11.544 |
| 15 | -30.518 | -20.715 | -16.472 | -10.550 | -7.178 | -4.494 | -0.600 | +3.456 | +7.219 | +11.445 |

## Channel 2: measured power table

Column headings are generator voltage settings in Vpp. Values are measured
AC power in dBm across the 50-ohm load.

| Frequency (MHz) | 0.04 Vpp | 0.126 Vpp | 0.2 Vpp | 0.4 Vpp | 0.6 Vpp | 0.8 Vpp | 1.265 Vpp | 2 Vpp | 3 Vpp | 5 Vpp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -29.984 | -20.241 | -16.087 | -10.118 | -6.772 | -3.933 | -0.031 | +3.962 | +7.678 | +11.912 |
| 2 | -30.012 | -20.285 | -16.121 | -10.159 | -6.801 | -3.954 | -0.046 | +3.932 | +7.657 | +11.855 |
| 3 | -30.053 | -20.311 | -16.142 | -10.188 | -6.821 | -4.001 | -0.074 | +3.899 | +7.638 | +11.853 |
| 4 | -30.078 | -20.356 | -16.164 | -10.207 | -6.826 | -4.019 | -0.079 | +3.876 | +7.625 | +11.856 |
| 5 | -30.096 | -20.363 | -16.160 | -10.181 | -6.809 | -4.018 | -0.085 | +3.897 | +7.654 | +11.944 |
| 6 | -30.147 | -20.385 | -16.213 | -10.212 | -6.830 | -4.071 | -0.150 | +3.855 | +7.615 | +11.922 |
| 7 | -30.137 | -20.384 | -16.176 | -10.198 | -6.827 | -4.042 | -0.112 | +3.894 | +7.647 | +11.916 |
| 8 | -30.310 | -20.598 | -16.316 | -10.419 | -7.135 | -4.207 | -0.319 | +3.628 | +7.302 | +11.397 |
| 9 | -30.300 | -20.590 | -16.313 | -10.391 | -7.075 | -4.207 | -0.301 | +3.661 | +7.386 | +11.537 |
| 10 | -30.334 | -20.608 | -16.328 | -10.398 | -7.069 | -4.248 | -0.328 | +3.650 | +7.372 | +11.560 |
| 10.01 | -30.327 | -20.601 | -16.340 | -10.406 | -7.090 | -4.261 | -0.323 | +3.643 | +7.360 | +11.555 |
| 11 | -30.447 | -20.719 | -16.438 | -10.506 | -7.184 | -4.365 | -0.448 | +3.518 | +7.259 | +11.444 |
| 12 | -30.502 | -20.779 | -16.488 | -10.561 | -7.237 | -4.432 | -0.491 | +3.471 | +7.211 | +11.374 |
| 13 | -30.535 | -20.811 | -16.490 | -10.569 | -7.257 | -4.445 | -0.526 | +3.452 | +7.181 | +11.351 |
| 14 | -30.571 | -20.864 | -16.516 | -10.612 | -7.307 | -4.483 | -0.557 | +3.410 | +7.165 | +11.320 |
| 15 | -30.666 | -20.947 | -16.588 | -10.697 | -7.390 | -4.584 | -0.665 | +3.304 | +7.069 | +11.213 |

## Evidence and repeatability

The complete measured voltage/power CSV is `artifacts/power-calibration.csv`.
Machine-readable bundled data are `src/jds2800_mcp/data/calibration.json`.
Raw repeated readings and instrument settings are retained in
`artifacts/power-calibration-measurements.json` and
`artifacts/power-refinement-measurements.json`; their SHA-256 hashes are recorded
in the bundled profile. Public evidence omits connection addresses and private
paths; numeric measurements are unchanged, with original hashes retained for
provenance. The original verification before refinement is preserved
in `artifacts/power-verification-before-refinement.json`. The frequency response plot is `artifacts/power-calibration.png`.
Independent verification results are in `artifacts/power-verification.json`.

The reusable acquisition command is:

```sh
uv run jds2800-calibrate --scope-host "$RIGOL_HOST" --rigol-server "$RIGOL_SERVER" \
  --out artifacts/new-power-calibration.json --confirm-50ohm
```

It defaults to normal acquisition, records partial progress, and disables both
outputs on completion or a handled failure. `--acquire-type AVER` selects the
averaging method used for this initial grid, but requires checking trigger stability.
The supplied scope server is used through MCP; the power-control server has no
runtime dependency on the scope or adjacent checkouts.
