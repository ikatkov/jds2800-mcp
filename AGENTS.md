# JDS2800 project reference

Before controlling the generator or changing device limits, read
[the packaged reference](src/jds2800_mcp/docs/JDS2800-reference.md).
It is also exposed by the MCP `get_manual` tool, the `jds2800://manual` resource,
and `./jds2800 manual` (JSON string; no hardware connection required).

The reference distinguishes manufacturer specifications, serial protocol details,
project guardrails, calculations, and measured behavior. Keep those distinctions
when updating it. Preserve source page numbers and unresolved manual discrepancies.
The bundled calibration was measured on a 15 MHz model; arbitrary/PULSE/CMOS waveforms are limited
to 6 MHz. The estimated +24 dBm into 50 ohms is conditional, not a measured rating.

Test wiring: generator CH1 goes to Rigol CH1; generator CH2 goes to Rigol CH3 via direct coax.
Use probe attenuation 1. The original functional checks used high-impedance loads;
the power calibration uses external 50-ohm terminations at scope CH1 and CH3.
Read device identity and state before mutations. Hardware synchronization can
make CH2 follow CH1; the server does not manage that system setting.

For dBm output, read [the power calibration](src/jds2800_mcp/docs/JDS2800-power-calibration.md)
or MCP `get_calibration`. Use `preview_power` / `set_power` (CLI `preview-power` /
`power`) for calibrated zero-offset sine into physical 50-ohm loads. SINE remains
the default. For square output, pass `waveform="SQUARE"` to all three tools and read
[the square guide](src/jds2800_mcp/docs/JDS2800-square-calibration.md). Square uses
its own measured per-channel profile at 50% duty, never the sine profile or a +3 dB
conversion. Its dBm metric is AC RMS including harmonics within the scope's analog
response, excluding DC; it is not fundamental-only or infinite-bandwidth total power.
CMOS/PULSE and different duty cycles have no calibrated dBm control. Both tables are
tied to serial 1816400000 and the measured coax cables, cover 1..15 MHz, and
do not permit extrapolation. Keep raw measurement evidence and uncertainty notes
when replacing it. A returned dBm estimate is not a fresh scope measurement.

For code changes, run the relevant tests and the checks listed in README.md.
Documentation/resource changes do not require enabling generator outputs.
