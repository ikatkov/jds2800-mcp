# JDS2800 MCP

MCP server and JSON scripting CLI for a JUNTEK JDS2800 over USB serial.

Uses the existing [Kristoff Bonne Python driver](https://github.com/on1arf/jds6600_python)
with per-operation serial ownership, line framing, parameter checks and verified
readback. The legacy source and MIT license are vendored, so the server does not
require another checkout or computer. Built with the
[official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), pinned
to version 1.30.0. Supports macOS and Linux with Python 3.11 or newer.

## Install and run

```sh
git clone https://github.com/ikatkov/jds2800-mcp.git
cd jds2800-mcp
uv sync --locked
./jds2800 info
./jds2800 state
```

Run these commands from the checkout. The `jds2800` and `run-mcp` launchers
use the virtual environment created by `uv sync`. An installed package
also provides `jds2800` and `jds2800-mcp` console commands.

No port setting is required. The driver tries available USB serial ports,
prioritizing JDS descriptions and CH340 adapters. It identifies a compatible
generator by reading its model, serial number and channel states, without changing
output settings. Probes have short timeouts and use the same serial lock as normal
operations. Bluetooth/headset and debug-console ports are excluded.

If no generator answers, the CLI exits with status 2 and an error listing the
ports it tried. If multiple generators answer, it asks you to select one explicitly
using `--port` or `JDS2800_PORT`. An explicit port always overrides discovery.

## Manual reference for agents

Read [JDS2800-reference.md](src/jds2800_mcp/docs/JDS2800-reference.md) before
controlling the instrument. It summarizes the supplied manufacturer's 18-page
English manual (Rev 1.0, June 2018), with page references, specifications,
operating procedures, documented ambiguities, 50-ohm power calculations, and
separately labeled protocol details and measured hardware findings.

The same Markdown is bundled in the Python package and available without a
generator connection through the MCP `get_manual` tool or the `jds2800://manual`
resource (`text/markdown`). Server instructions direct agents to it. The CLI
`./jds2800 manual` returns it as a JSON string; `./jds2800 call get_manual` also works.

## MCP connection

Install the console commands so an MCP client can launch the server from any
directory:

```sh
uv tool install .
```

Copy [.mcp.example.json](.mcp.example.json) into the client's MCP settings:

```json
{
  "mcpServers": {
    "jds2800": {
      "command": "jds2800-mcp"
    }
  }
}
```

Ensure the installed console command is on the client's PATH. For development,
`./run-mcp` launches the checkout's environment; configure the client with the
path to your own checkout rather than a path from someone else's machine.

Server startup and tool discovery do not open the generator or enable outputs.
The server implements 17 tools:

| Tool | Purpose |
| --- | --- |
| `get_manual` | Bundled specifications, operating notes and verified limitations |
| `get_calibration` | Per-channel measured 50-ohm sine power table and valid ranges |
| `preview_power` | Check device identity and calculate voltage for requested dBm |
| `set_power` | Configure calibrated sine power into a physical 50-ohm load |
| `list_ports` | Find USB serial ports without opening them |
| `list_waveforms` | Built-in names/IDs and arbitrary slots |
| `get_device_info` | Model code, serial, port and frequency limit |
| `get_state` | Read both channels or one channel, mode and phase |
| `configure_channel` | Frequency, waveform, amplitude, offset, duty and enable |
| `set_outputs` | Independently enable/disable either output |
| `set_phase` | Inter-channel phase; negative values normalized modulo 360 |
| `set_mode` | Explicitly select mode and stop active actions |
| `configure_sweep` | Sweep parameters, readback, optional start |
| `stop_outputs` | Stop actions and disable both outputs |
| `read_register` | Read protocol registers, including counter/measurement data |
| `read_arbitrary` | Read 2048 samples from a stored waveform |
| `upload_arbitrary` | Overwrite a stored waveform and verify all samples |

## Scripting CLI

Successful commands print one JSON value to stdout. Failures print JSON to stderr
and exit with status 2. Help/argument parsing uses the standard argparse interface.
The port is discovered automatically. To override it, supply `--port` before
the subcommand or set `JDS2800_PORT`.

```sh
# 1 kHz triangle, 2 Vpp, +1 V offset on channel 1.
./jds2800 configure 1 --waveform TRIANGLE --frequency-hz 1000 \
  --amplitude-vpp 2 --offset-v 1 --enabled on

# 2 kHz, 1 Vpp, 30% duty on channel 2.
./jds2800 configure 2 --waveform PULSE --frequency-hz 2000 \
  --amplitude-vpp 1 --offset-v 0 --duty-percent 30 --enabled on

./jds2800 outputs --ch1 off
./jds2800 phase -90
./jds2800 stop

# Every MCP tool is also available through `call`.
./jds2800 call get_state --args '{"channel":2}'
./jds2800 call configure_sweep --args \
  '{"channel":1,"start_hz":1000,"end_hz":2000,"time_s":1,"start":false}'
./jds2800 mode WAVE_CH1

# Multiple operations, one serial lease. This example enables both outputs.
./jds2800 batch examples/dual-channel.json
./jds2800 stop
```

`batch` also accepts `-` to read a JSON array from stdin. Entries contain an
`operation` (the MCP tool name) and an optional `arguments` object. Operations run
sequentially and stop on the first failure. Earlier operations are not rolled
back; the error includes their results and the failing entry's zero-based index.

## Device behavior and units

- Frequency is in Hz, amplitude in **V peak-to-peak**, offset in V, duty in percent,
  and phase in degrees. Frequency readback uses the actual quantized device value.
- The connected unit reports model code **15**, serial **1816400000**. Its sine
  limit is 15 MHz. The driver detects the limit instead of assuming the original
  JDS6600 library's 60 MHz maximum.
- Pulse/CMOS/arbitrary frequency is limited to 6 MHz. Other non-sine waveforms are limited
  to the smaller of the model limit and 25 MHz.
- Amplitude and offset limits are checked together. Maximum amplitude decreases
  above 10 MHz and 30 MHz; non-sine amplitude is conservatively capped at 5 Vpp
  above 10 MHz. The allowed offset range also depends on amplitude.
  The actual load affects physical voltage. The tested wiring used direct coax
  into the scope's high-impedance inputs, with probe attenuation **1×**.
- Device synchronization can make selected CH2 parameters follow CH1 (manual
  p. 18). This server does not read or change synchronization settings; check the
  front-panel SYS menu before relying on independent channel parameters.
- **SQUARE is physically 50% duty on this unit.** The duty register can say 30%
  while the square wave stays at 50%. Use **PULSE** for adjustable duty. Requests
  to set a non-50% SQUARE duty are rejected before writing.
- Channel configuration requires `WAVE_CH1` or `WAVE_CH2` mode. It validates the
  complete target configuration, temporarily disables the target channel, writes
  and reads back all its parameters, then restores its previous enable state
  unless `enabled` was supplied. It preserves the other channel's enable state.
- A failed configuration requests the target channel off and reports an error.
  Unplugging can prevent that request from reaching the device. There are no
  automatic write retries or claims of rollback; read state before continuing.
- Each operation releases the serial connection after completion. CLI commands
  can coexist with a running MCP server. A shared file lock serializes operations
  across processes, including a complete batch. External legacy programs do not
  participate in this lock and should not run against the same port concurrently.
- `configure_sweep` selects sweep mode and stops prior actions. It preserves
  output enable state; `start=true` starts the action. Return explicitly to wave
  mode before ordinary configuration. Arbitrary uploads overwrite device storage;
  they do not select the slot or enable output.

## Calibrated sine output in dBm

The bundled [power calibration](src/jds2800_mcp/docs/JDS2800-power-calibration.md)
is for this **15 MHz generator, serial 1816400000**, with separate tables for
CH1 and CH2. It uses external 50-ohm terminations at Rigol CH1/CH3 through the
existing direct coax cables. These loads must be present at the receiving end
when using dBm settings. Scope-referenced power includes the measured cable loss.

```sh
./jds2800 calibration
./jds2800 preview-power 1 --frequency-hz 5500000 --dbm 0
./jds2800 power 1 --frequency-hz 5500000 --dbm 0 --enabled on
./jds2800 power 2 --frequency-hz 14500000 --dbm -10 --enabled on
./jds2800 stop
```

`set_power` / `power` explicitly sets **SINE, zero DC offset, 50% duty**, frequency,
and calibrated amplitude. It preserves output enable state unless `enabled` is
supplied. It requires wave mode, verifies the generator serial and register
readback, and refuses requests outside the measured frequency/level ranges.
It does not remeasure power on every call. The returned `predicted_power_dbm`
accounts for the generator's 1 mV amplitude increments.

Calibration covers **1–15 MHz**, at every integer MHz plus 10.01 MHz, with ten
amplitude settings per frequency on each channel: **320 points**, each measured
three times. The table supports approximately **-29 to +11 dBm across the full
frequency range**, with precise per-frequency bounds reported by `get_calibration`.
The ordinary voltage controls retain the manufacturer's larger amplitude range;
the power controls require measured coverage. No frequency or level extrapolation
is performed. Interpolation is linear in dBm versus log amplitude and log frequency.

MCP `get_calibration(include_points=true)` returns the full measured table.
The resource `jds2800://calibration` returns metadata and supported ranges.
An alternate calibration file can be selected using `JDS2800_CALIBRATION`;
it must match the actual device and use the same sine/zero-offset/50-ohm convention.
The table is bundled in the installed package. Published evidence omits private
paths and connection addresses while preserving numeric readings and provenance.

The bundled profile applies only to serial **1816400000**; other units require
their own measured profile, selected with `JDS2800_CALIBRATION`. Calibration
collection currently targets 15 MHz units.

To repeat calibration, attach both external 50-ohm loads, supply the scope server
and address as described below, and run:

```sh
uv run jds2800-calibrate --scope-host "$RIGOL_HOST" --rigol-server "$RIGOL_SERVER" \
  --out artifacts/new-power-calibration.json --confirm-50ohm
```

This procedure changes channel settings, uses the Rigol MCP server, saves partial
measurements as it runs, and disables both outputs on completion or a handled
failure. `--resume` continues an incomplete run with the same measurement grid.
The checked-in data are validated against independent frequency/level requests
by `scripts/verify_power.py`. This is a scope-referenced correction; absolute
accuracy still depends on the scope, terminations, cables, and operating conditions.
The RMS measurement includes harmonics and noise rather than isolating the RF
fundamental. Sine power calibration does not apply to square/pulse/noise outputs.

Scope readings come from numeric measurement queries. The collector clears previous
measurements before each reading, retains Vpp, and derives AC power from RMS with
the measured DC component removed. The display scale only keeps signals in range.
The original 256 points used 16-acquisition averaging; 64 refinement points and
the independent checks use normal acquisition. See the guide for the raw evidence.

Independent verification passed **72 checks** from -25 to +10 dBm, including
intermediate frequencies, the 10 MHz boundary, and both outputs together. The
largest difference from requested power was **0.195 dB relative to this scope**.
See [the results](artifacts/power-verification.json). Both outputs were left off.

## What was tested

On **October 3, 2026**, both connected channels were verified through the actual
stdio JDS2800 MCP server and the existing Rigol scope MCP server. Wiring:
generator CH1 → scope CH1; generator CH2 → scope CH3. Scope: DS1104Z,
serial DS1ZA225013504. See the measured values and screenshot in
[artifacts/hardware-verification.json](artifacts/hardware-verification.json) and
[artifacts/scope-triangle-pulse.png](artifacts/scope-triangle-pulse.png).

The hardware test covers both sine outputs, the original triangle/offset setup,
30% pulse duty, independent output switching, negative-phase register readback,
model-limit rejection without mutation, and CLI access while MCP is alive.
The scope readings verify control behavior; this is not a calibration of absolute
amplitude. Both generator outputs are off at the end of the test.

Sweep parameter/mode readback and reading all 2048 samples from arbitrary slot 1
were also checked on the device. Sweep progression, physical inter-channel phase,
arbitrary **uploads**, and external counter/measurement inputs have not been
verified on the scope. The tests do not overwrite stored arbitrary waveforms.

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts

# Handshake and discovery without hardware.
uv run python scripts/check_mcp.py

# Read the device through MCP without changing its settings.
uv run python scripts/check_mcp.py --hardware

# Changes both channels for testing, captures scope data, then disables outputs.
uv run python scripts/verify_hardware.py --rigol-server "$RIGOL_SERVER" \
  --scope-host "$RIGOL_HOST"
```

Supply `RIGOL_SERVER` as the path to a compatible Rigol stdio MCP server script
and `RIGOL_HOST` as the scope hostname or IP address. The hardware checks use
the active Python environment and USB discovery unless `--port` is supplied.
The scope server must be able to run in that environment. Scope setup writes
are followed by `*OPC?` through its `scpi` MCP tool to wait for completion.

## Library comparison

Two drivers were exercised against the same 15 MHz instrument:

| Driver | Observed result | Assessment for this server |
| --- | --- | --- |
| Python `on1arf/jds6600_python` v0.1.0 | Read both channels and changed frequency, waveform, amplitude, offset and enables | Compact API, same language as MCP, and compatible with the reproduced automation sequence |
| Rust `signal-gen-cjds66` v0.1.10 | Read identity, frequency/amplitude, and changed settings in individual commands | Partly compatible, but combined reads failed with exit status 19 |

The Rust reproduction `--gg --gn` successfully read CH1's offset, then failed on
CH2 with a missing-equals error. Its fixed-size `read()` calls do not consume a
complete variable-length CRLF reply or check the number of bytes returned. A
leftover byte is parsed as the next response. See
[artifacts/rust-offset-read.txt](artifacts/rust-offset-read.txt) and
[artifacts/rust-frequency-write.txt](artifacts/rust-frequency-write.txt).

The Python library is the better starting point, but its original class-level
serial handle and loose validation also needed improvement. This server bypasses
that constructor, replaces the transport, verifies readback, prevents negative
waveform indexes, and fixes the original negative-phase conversion. The vendored
Python driver makes ordinary operation independent of the comparison drivers.

## Configuration

| Setting | Default |
| --- | --- |
| `JDS2800_PORT` / `--port` | Probe USB serial ports and select a single matching JDS generator |
| `JDS2800_TIMEOUT` / `--timeout` | 1 second per serial reply/write |
| `JDS2800_LOCK_TIMEOUT` | 5 seconds waiting for another operation |

Protocol reference: [upstream register map](https://github.com/on1arf/jds6600_python/blob/master/registers.txt).
Hardware ranges follow the supplied manufacturer's manual, summarized in
[the bundled reference](src/jds2800_mcp/docs/JDS2800-reference.md), which records
the document edition, page references, and checksum.
MIT license; the vendored library retains its original copyright and license.
