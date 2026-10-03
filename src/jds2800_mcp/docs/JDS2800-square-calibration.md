# Measured JDS2800 square-wave power calibration

Device: JDS2800-15M, serial **1816400000**. Measured October 3, 2026.
Generator CH1 feeds Rigol CH1; generator CH2 feeds Rigol CH3, through the existing
coax cables with external **50-ohm terminations at the scope inputs**. The operator
confirmed both loads. Numeric scope voltage readings supply every power value.
Scope: Rigol DS1104Z, serial DS1ZA225013504, 100 MHz analog bandwidth,
500 MSa/s with two channels, DC coupling, probe factor 1, bandwidth limit OFF.

## MCP use

Call `get_calibration(waveform="SQUARE")` to inspect coverage, then use
`preview_power` and `set_power` with the same waveform argument. Example:

```json
{"channel":1,"frequency_hz":10000000,"power_dbm":7,"waveform":"SQUARE","enabled":true}
```

The default waveform remains SINE. The square table is selected separately; the
sine table is never converted or reused. Square output sets 50% duty and zero
requested DC offset. Device serial, frequency and power coverage are checked
before any writes. Output is gated while configuring and readback is verified.
Output enable state is preserved unless `enabled` is supplied. The physical
50-ohm load and measured cables are required. CMOS/PULSE/different duty cycles
have no calibrated dBm control. Existing MCP clients must reconnect to refresh
the tool schema and load the updated server code.

Resources: `jds2800://calibration/square` and `jds2800://square-power-guide`.
The bundled table is `data/square-calibration.json`. A measured replacement
can be selected with `JDS2800_SQUARE_CALIBRATION`; the existing
`JDS2800_CALIBRATION` variable remains exclusive to the sine profile.

## What power means

**AC RMS power including harmonics passed by the scope's analog response,
with DC removed**. This is neither fundamental-only RF power nor an
infinite-bandwidth measurement of ideal-square total power.

At each point the scope returns numeric `VRMS`, `VAVG`, `VPP`, and frequency
three times. Each repeated numeric reading uses the current acquisition;
`:MEAS:CLE ALL` removes prior displayed measurement items before querying.
The grid is never used to estimate voltage. The median measured power is:

```text
AC_RMS = sqrt(VRMS^2 - VAVG^2)
P_AC_W = (VRMS^2 - VAVG^2) / 50
P_AC_dBm = 10 * log10(P_AC_W / 0.001)
P_total_with_DC_W = VRMS^2 / 50
```

The total-with-DC values in raw evidence have the same scope bandwidth limit.
Do not substitute the sine Vpp formula, square Vpp formula, or a +3 dB offset
for the measured RMS. Actual edge shape, overshoot and frequency response matter.
The raw collector's `vpp_sine_dbm` is a sine-only diagnostic, not square power;
it is omitted from the bundled square table.
A returned `predicted_power_dbm` is a table prediction after 1 mV amplitude
rounding, not a fresh scope measurement. `scope_verified_now` is false for ordinary calls.

An ideal bipolar 50%-duty square has harmonic voltage proportional to 1/n
for odd n, and harmonic power proportional to 1/n². The infinite sum converges:
the fundamental contains 8/pi² = 81.06% of AC power. All higher harmonics
together contain 18.94%, adding 0.912 dB above fundamental-only power.
At equal measured Vpp, ideal square AC power is twice ideal sine power (+3.010 dB).
These are analytical comparisons, not corrections applied to this measured table.

The scope's nominal bandwidth is 100 MHz at -3 dB, not a brick-wall cutoff.
It attenuates high harmonics. Finite generator edge speed also changes the spectrum.
The optional RAW-capture analysis separates fundamental/harmonic content within
the same scope response; it cannot establish power beyond that response.
For an absolute broadband power specification, use a suitable characterized
broadband power meter or calibrated spectrum measurement instead of declaring
this scope calibration to be infinite-bandwidth total power.

## Coverage and verification

16 frequency knots per channel: 1–15 MHz at integer MHz plus 10.01 MHz.
Ten amplitude settings per frequency: 0.04, 0.126, 0.2, 0.4, 0.6, 0.8,
1.265, 2, 3, and 5 Vpp, giving **320 measured points and 960 numeric reading sets**.
Acquisition uses NORM, not waveform averaging. RMS includes the actual measured
noise/harmonics. Interpolation uses measured dBm versus log amplitude and log
frequency, separately for each output. No level/frequency extrapolation is allowed.

| Generator output | Frequency range | AC power range supported at every measured frequency |
| --- | --- | --- |
| 1 | 1–15 MHz | -27.001 to 13.822 dBm |
| 2 | 1–15 MHz | -27.031 to 13.534 dBm |

Independent hardware verification passed **92 MCP checks** plus
**2 CLI/scope checks**, with maximum absolute
difference **0.330 dB** from requested power.
Acceptance tolerance was 0.35 dB, relative to this same scope.
Checked requests span -26.5 to +13 dBm, both channels, intermediate frequencies,
the 10 MHz boundary, and both outputs enabled together. This is measured
agreement for the checked cases, not a traceable absolute accuracy specification.

## Supplemental measured harmonic content

These separate captures use a 2 Vpp generator setting. The AC-power
column comes from numeric scope readings; fundamental power comes from
a fit to measured RAW scope voltages. The remainder includes higher
harmonics and measured noise within the same scope response.
These captures do not replace the calibration table or establish
power outside the scope's bandwidth.

| Output | MHz | Square AC dBm | Fitted fundamental dBm | Fundamental fraction of measured AC |
| --- | --- | --- | --- | --- |
| 1 | 1 | +7.161 | +6.359 | 83.13% |
| 1 | 5 | +6.772 | +6.132 | 86.29% |
| 1 | 10 | +6.312 | +5.835 | 89.61% |
| 1 | 15 | +6.044 | +5.623 | 90.75% |
| 2 | 1 | +7.059 | +6.198 | 82.01% |
| 2 | 5 | +6.770 | +6.130 | 86.30% |
| 2 | 10 | +6.301 | +5.836 | 89.86% |
| 2 | 15 | +5.632 | +5.316 | 92.98% |

## CMOS measurements

CMOS was measured separately at 1, 3 and 6 MHz with three amplitude
settings on each output. Both columns are computed from numeric scope
voltage readings. Total power includes DC; AC power removes DC.
These 18 cases characterize CMOS; they are not an interpolation table
for calibrated CMOS dBm control. The MCP rejects CMOS power requests.

| Output | MHz | Setting Vpp | Measured Vpp | Numeric RMS V | Numeric average V | AC dBm | Including DC dBm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 0.520000 | 0.354271 | 0.251699 | +0.945 | +3.997 |
| 1 | 1 | 2 | 1.100000 | 0.724134 | 0.511472 | +7.206 | +10.207 |
| 1 | 1 | 4 | 2.240000 | 1.434941 | 1.007625 | +13.200 | +16.147 |
| 1 | 3 | 1 | 0.520000 | 0.349988 | 0.248562 | +0.843 | +3.891 |
| 1 | 3 | 2 | 1.100000 | 0.716892 | 0.508796 | +7.084 | +10.119 |
| 1 | 3 | 4 | 2.240000 | 1.415167 | 1.000602 | +13.019 | +16.026 |
| 1 | 6 | 1 | 0.528000 | 0.344672 | 0.249605 | +0.530 | +3.758 |
| 1 | 6 | 2 | 1.060000 | 0.711080 | 0.517408 | +6.775 | +10.049 |
| 1 | 6 | 4 | 2.120000 | 1.410098 | 1.027542 | +12.712 | +15.995 |
| 2 | 1 | 1 | 0.512000 | 0.346673 | 0.243592 | +0.853 | +3.809 |
| 2 | 1 | 2 | 1.080000 | 0.699885 | 0.487625 | +7.013 | +9.911 |
| 2 | 1 | 4 | 2.100000 | 1.408626 | 0.995753 | +12.998 | +15.986 |
| 2 | 3 | 1 | 0.512000 | 0.341627 | 0.240943 | +0.693 | +3.681 |
| 2 | 3 | 2 | 1.080000 | 0.692418 | 0.483411 | +6.917 | +9.818 |
| 2 | 3 | 4 | 2.080000 | 1.394454 | 0.987107 | +12.879 | +15.898 |
| 2 | 6 | 1 | 0.512000 | 0.336956 | 0.240582 | +0.466 | +3.562 |
| 2 | 6 | 2 | 1.080000 | 0.685139 | 0.486288 | +6.688 | +9.726 |
| 2 | 6 | 4 | 2.080000 | 1.364270 | 0.986639 | +12.493 | +15.708 |

## Numeric voltage readings at a 2 Vpp generator setting

Both voltage columns below come from numeric scope readings, not grid estimates.
The setting-for-7-dBm column is interpolated from the measured table.

| Output | MHz | Measured Vpp (V) | Measured AC RMS (V) | Measured AC dBm | Setting for +7 dBm (Vpp) |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 | 1.032000 | 0.497147 | +6.940 | 2.013 |
| 1 | 2 | 1.032000 | 0.492408 | +6.857 | 2.031 |
| 1 | 3 | 1.032000 | 0.491513 | +6.841 | 2.035 |
| 1 | 4 | 1.032000 | 0.487149 | +6.764 | 2.052 |
| 1 | 5 | 1.032000 | 0.483615 | +6.700 | 2.067 |
| 1 | 6 | 1.032000 | 0.478437 | +6.607 | 2.087 |
| 1 | 7 | 1.032000 | 0.474169 | +6.529 | 2.105 |
| 1 | 8 | 1.032000 | 0.469121 | +6.436 | 2.126 |
| 1 | 9 | 1.024000 | 0.465040 | +6.360 | 2.143 |
| 1 | 10 | 1.024000 | 0.460950 | +6.283 | 2.161 |
| 1 | 10.01 | 1.016000 | 0.460841 | +6.281 | 2.161 |
| 1 | 11 | 1.024000 | 0.454496 | +6.161 | 2.188 |
| 1 | 12 | 1.016000 | 0.450440 | +6.083 | 2.208 |
| 1 | 13 | 1.016000 | 0.446460 | +6.006 | 2.226 |
| 1 | 14 | 1.008000 | 0.441916 | +5.917 | 2.247 |
| 1 | 15 | 1.008000 | 0.437499 | +5.830 | 2.268 |
| 2 | 1 | 1.032000 | 0.494665 | +6.897 | 2.023 |
| 2 | 2 | 1.024000 | 0.490087 | +6.816 | 2.041 |
| 2 | 3 | 1.024000 | 0.487075 | +6.762 | 2.053 |
| 2 | 4 | 1.024000 | 0.482988 | +6.689 | 2.069 |
| 2 | 5 | 1.024000 | 0.479222 | +6.621 | 2.084 |
| 2 | 6 | 1.024000 | 0.475297 | +6.550 | 2.099 |
| 2 | 7 | 1.024000 | 0.471198 | +6.474 | 2.117 |
| 2 | 8 | 1.016000 | 0.458871 | +6.244 | 2.175 |
| 2 | 9 | 1.008000 | 0.456568 | +6.200 | 2.182 |
| 2 | 10 | 1.008000 | 0.452485 | +6.122 | 2.199 |
| 2 | 10.01 | 1.008000 | 0.452922 | +6.131 | 2.197 |
| 2 | 11 | 1.008000 | 0.446664 | +6.010 | 2.226 |
| 2 | 12 | 1.008000 | 0.441770 | +5.914 | 2.249 |
| 2 | 13 | 1.000000 | 0.437527 | +5.830 | 2.270 |
| 2 | 14 | 1.000000 | 0.432610 | +5.732 | 2.293 |
| 2 | 15 | 1.000000 | 0.427571 | +5.630 | 2.319 |

## Output 1: measured AC power table

Columns are generator amplitude settings. Entries are measured AC dBm into 50 ohms.

| MHz | 0.04 Vpp | 0.126 Vpp | 0.2 Vpp | 0.4 Vpp | 0.6 Vpp | 0.8 Vpp | 1.265 Vpp | 2 Vpp | 3 Vpp | 5 Vpp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -27.001 | -17.175 | -13.107 | -7.159 | -3.708 | -1.039 | +2.888 | +6.940 | +10.668 | +14.948 |
| 2 | -27.080 | -17.241 | -13.152 | -7.166 | -3.792 | -1.074 | +2.820 | +6.857 | +10.595 | +14.875 |
| 3 | -27.083 | -17.266 | -13.178 | -7.194 | -3.819 | -1.109 | +2.808 | +6.841 | +10.577 | +14.846 |
| 4 | -27.175 | -17.338 | -13.253 | -7.216 | -3.869 | -1.178 | +2.743 | +6.764 | +10.510 | +14.759 |
| 5 | -27.226 | -17.402 | -13.298 | -7.323 | -3.945 | -1.239 | +2.674 | +6.700 | +10.411 | +14.681 |
| 6 | -27.313 | -17.481 | -13.377 | -7.402 | -4.026 | -1.342 | +2.583 | +6.607 | +10.347 | +14.618 |
| 7 | -27.375 | -17.553 | -13.436 | -7.477 | -4.117 | -1.409 | +2.492 | +6.529 | +10.266 | +14.525 |
| 8 | -27.468 | -17.647 | -13.528 | -7.576 | -4.225 | -1.516 | +2.391 | +6.436 | +10.175 | +14.424 |
| 9 | -27.537 | -17.724 | -13.593 | -7.669 | -4.311 | -1.593 | +2.307 | +6.360 | +10.105 | +14.349 |
| 10 | -27.606 | -17.804 | -13.660 | -7.751 | -4.393 | -1.669 | +2.224 | +6.283 | +10.040 | +14.269 |
| 10.01 | -27.602 | -17.794 | -13.651 | -7.751 | -4.388 | -1.664 | +2.238 | +6.281 | +10.040 | +14.268 |
| 11 | -27.702 | -17.909 | -13.759 | -7.852 | -4.505 | -1.779 | +2.122 | +6.161 | +9.938 | +14.155 |
| 12 | -27.803 | -17.982 | -13.840 | -7.926 | -4.587 | -1.872 | +2.038 | +6.083 | +9.843 | +14.070 |
| 13 | -27.863 | -18.068 | -13.912 | -7.991 | -4.671 | -1.951 | +1.951 | +6.006 | +9.763 | +13.997 |
| 14 | -27.942 | -18.149 | -13.986 | -8.060 | -4.752 | -2.039 | +1.868 | +5.917 | +9.684 | +13.907 |
| 15 | -28.017 | -18.223 | -14.057 | -8.138 | -4.841 | -2.135 | +1.781 | +5.830 | +9.604 | +13.822 |

## Output 2: measured AC power table

Columns are generator amplitude settings. Entries are measured AC dBm into 50 ohms.

| MHz | 0.04 Vpp | 0.126 Vpp | 0.2 Vpp | 0.4 Vpp | 0.6 Vpp | 0.8 Vpp | 1.265 Vpp | 2 Vpp | 3 Vpp | 5 Vpp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -27.031 | -17.300 | -13.159 | -7.208 | -3.798 | -1.008 | +2.922 | +6.897 | +10.610 | +14.829 |
| 2 | -27.127 | -17.401 | -13.220 | -7.259 | -3.884 | -1.066 | +2.846 | +6.816 | +10.537 | +14.749 |
| 3 | -27.176 | -17.455 | -13.270 | -7.317 | -3.960 | -1.133 | +2.794 | +6.762 | +10.470 | +14.675 |
| 4 | -27.251 | -17.562 | -13.342 | -7.390 | -4.030 | -1.218 | +2.694 | +6.689 | +10.406 | +14.619 |
| 5 | -27.344 | -17.628 | -13.394 | -7.428 | -4.074 | -1.291 | +2.644 | +6.621 | +10.374 | +14.637 |
| 6 | -27.412 | -17.680 | -13.469 | -7.506 | -4.152 | -1.371 | +2.564 | +6.550 | +10.318 | +14.588 |
| 7 | -27.496 | -17.746 | -13.530 | -7.591 | -4.259 | -1.448 | +2.487 | +6.474 | +10.236 | +14.468 |
| 8 | -27.640 | -17.958 | -13.668 | -7.794 | -4.537 | -1.607 | +2.313 | +6.244 | +9.905 | +14.003 |
| 9 | -27.697 | -17.985 | -13.717 | -7.834 | -4.556 | -1.683 | +2.258 | +6.200 | +9.929 | +14.078 |
| 10 | -27.773 | -18.074 | -13.795 | -7.899 | -4.617 | -1.761 | +2.176 | +6.122 | +9.875 | +14.040 |
| 10.01 | -27.773 | -18.081 | -13.796 | -7.903 | -4.619 | -1.754 | +2.171 | +6.131 | +9.874 | +14.031 |
| 11 | -27.877 | -18.185 | -13.908 | -8.016 | -4.736 | -1.875 | +2.051 | +6.010 | +9.762 | +13.915 |
| 12 | -27.972 | -18.284 | -13.981 | -8.096 | -4.833 | -1.971 | +1.953 | +5.914 | +9.663 | +13.824 |
| 13 | -28.058 | -18.370 | -14.061 | -8.176 | -4.900 | -2.058 | +1.873 | +5.830 | +9.573 | +13.730 |
| 14 | -28.158 | -18.469 | -14.139 | -8.252 | -4.999 | -2.157 | +1.782 | +5.732 | +9.489 | +13.635 |
| 15 | -28.239 | -18.570 | -14.223 | -8.348 | -5.099 | -2.249 | +1.683 | +5.630 | +9.387 | +13.534 |

## Evidence

Raw numeric readings: `artifacts/square-power-calibration.json`.
Independent requested-power checks: `artifacts/square-power-verification.json`.
Supplemental SINE/SQUARE/CMOS numeric and RAW traces:
`artifacts/waveform-characterization.json` and `artifacts/waveform-characterization-analyzed.json`.
Reproduce supplemental acquisition with `scripts/characterize_waveforms.py`
using the same scope connection arguments and `--confirm-50ohm`; `--resume`
continues saved cases. Offline harmonic analysis uses
`scripts/analyze_waveform_captures.py` and requires NumPy.
The profile records evidence hashes. Connection addresses are excluded from
portable evidence. Both outputs are disabled at the end of acquisition/verification.

Repeat collection with `jds2800-calibrate --waveform SQUARE --confirm-50ohm`
and the usual scope connection/output arguments. Partial runs support `--resume`.

Scope specification source:
[RIGOL DS1000Z datasheet](https://supportint.rigol.com/Public/Uploads/uploadfile/files/ftp/DS/%E6%89%8B%E5%86%8C/DS1000Z/EN/DS1000Z_Datasheet_EN.pdf).
