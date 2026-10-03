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
`power`) for calibrated zero-offset sine into physical 50-ohm loads. The table is
tied to serial 1816400000 and the measured coax cables, covers 1..15 MHz, and
does not permit extrapolation. Keep raw measurement evidence and uncertainty notes
when replacing it. A returned dBm estimate is not a fresh scope measurement.

For code changes, run the relevant tests and the checks listed in README.md.
Documentation/resource changes do not require enabling generator outputs.
