# JUNTEK JDS2800 reference for MCP agents

This is a selective, self-contained reference for controlling the generator.
Manufacturer specifications, protocol details, project guardrails, calculations,
and measured behavior are labeled separately. Do not treat register readback as
proof of a physical waveform or calculated power as a tested output rating.

For the subsequently measured **50-ohm sine power calibration**, see
`JDS2800-power-calibration.md`, MCP `get_calibration`, and resource
`jds2800://calibration`. Use `preview_power` / `set_power` or CLI `preview-power` /
`power` to request dBm over the measured 1–15 MHz range. Those controls use separate
channel tables and match the generator serial; the earlier maximum-power estimates
below remain conditional and are outside the measured power-control range.

## Source and provenance

- Manufacturer: Hangzhou Junce Instrument Co., Ltd., JUNTEK.
- Document: *JDS2800 series Dual-Channel Function/Arbitrary DDS Signal Generator
  Quick Start Guide*, Rev 1.0, June 2018, 18 pages.
- Supplied PDF: `JDS2800_EN_manual.pdf`.
- SHA-256: `50536021428d39f57cefd7bc7162a4fdd49561bcb1b6137f2530f03d05233695`.
- Extracted and visually checked against the PDF on October 3, 2026. Page numbers
  below are both PDF page numbers and printed page numbers.
- This Markdown is bundled with the server; the original PDF is not required
  at runtime and is not redistributed in this repository.

The manual describes operation and specifications. It does **not** contain the
actual serial command/register map. The protocol notes below come from the
vendored on1arf Python library, `artifacts/upstream-registers.txt`, and this
project's transport implementation. Hardware measurements are separate evidence.

## Start here: connected instrument and operating sequence

**Hardware observation, October 3, 2026:** the measured generator reported
model code **15**, serial **1816400000**, and a 15 MHz sine limit. Use automatic
USB discovery or explicitly select a port for the connected generator.

Generator **CH1 → Rigol scope CH1**; generator **CH2 → Rigol scope CH3**, using
direct coax. The documented scope is a DS1104Z, serial DS1ZA225013504. Use probe attenuation **1** and high-impedance scope inputs for
the existing verification setup. Those measurements did not use 50-ohm loads.

1. Read this reference through `get_manual` or resource `jds2800://manual`.
   CLI equivalent: `./jds2800 manual` returns a JSON string without opening a port.
2. Call `get_device_info`, then `get_state`; establish the model, operating mode,
   waveform, frequency, amplitude, offset, duty, and enabled state of each channel.
3. If independent channels are needed, check synchronization in the front-panel
   SYS menu. Selected CH2 parameters can follow CH1; this server does not read
   or change sync settings (manual p. 18).
4. Ordinary `configure_channel` requires `WAVE_CH1` or `WAVE_CH2`. If changing
   from another mode, explicitly call `set_mode`; that stops current actions.
5. Supply frequency in **Hz**, amplitude in **V peak-to-peak**, offset in **V**,
   duty in **percent**, and phase in **degrees**. Load impedance affects voltage.
6. Configuration validates before writing, gates the target output during changes,
   verifies readback, and restores its previous enabled state unless `enabled`
   is supplied. To keep an output off, specify `enabled=false`.
7. Verify the physical signal with the scope when waveform shape, voltage, duty,
   timing, phase, or power matters. Use `stop_outputs` to stop actions and disable
   both channels when the experiment calls for it.

The CLI and MCP use a shared per-port lock, including an entire CLI batch.
Legacy programs do not participate in that lock. After a communication failure,
read state before continuing; an attempted output-off command may not have
reached an unplugged device, and writes are not automatically replayed.

## Manufacturer frequency and waveform specifications

### Model and waveform frequency limits — pp. 4–6

The manual lists three models. A family's highest frequency is not every unit's
limit; the attached unit is the 15M variant.

| Waveform | JDS2800-15M | JDS2800-40M | JDS2800-60M |
| --- | --- | --- | --- |
| Sine | 0–15 MHz | 0–40 MHz | 0–60 MHz |
| Square / triangle | 0–15 MHz | 0–25 MHz | 0–25 MHz |
| Pulse / TTL digital / arbitrary | 0–6 MHz | 0–6 MHz | 0–6 MHz |
| Dedicated pulse width adjustment | 100 ns–4000 s | 40 ns–4000 s | 25 ns–4000 s |
| Square rise time | ≤25 ns | ≤10 ns | ≤10 ns |

The square/triangle limits share merged cells on p. 5. Pulse, TTL, and arbitrary
limits share merged cells on p. 6: **all three are limited to 6 MHz**.
For other non-sine built-ins without a separate frequency row, the server uses
the smaller of the model limit and 25 MHz; that extrapolation is a project limit,
not a separately specified manufacturer range for each waveform.

| Property | Specification |
| --- | --- |
| Minimum frequency increment | 0.01 µHz = 0.00000001 Hz = 1e-8 Hz |
| Frequency accuracy | ±20 ppm |
| Frequency stability | ±1 ppm over 3 hours; duplicated text in the source |
| Waveform length | 2048 points |
| Waveform sampling rate | 266 MSa/s |
| Vertical resolution | 14 bits |
| Arbitrary waveform storage | 60 slots |

Frequency increment, accuracy, and stability are different quantities. Tiny
programmable increments do not imply comparable absolute frequency accuracy.
The MCP accepts zero Hz and enforces a minimum nonzero value of 1e-8 Hz.

### Waveform types and quality — pp. 6–7

The manual lists sine, square, pulse, triangle, partial sine, CMOS, DC, half-wave,
full-wave, positive/negative staircase, noise, exponential rise/decay, multitone,
sinc, Lorenz, and 60 arbitrary waveforms. DC level is adjusted using offset.
Its translated waveform names differ from some API spellings; use the exact
names returned by `list_waveforms` (for example `EXP-RIZE`, not `EXP-RISE`).

| Property | Specification / stated test conditions |
| --- | --- |
| Sine harmonic suppression | ≥45 dBc below 1 MHz; ≥40 dBc from 1–20 MHz |
| Sine total harmonic distortion | <1%, at 20 Hz–20 kHz and 0 dBm |
| Square/pulse overshoot | ≤5% |
| Pulse duty adjustment | 0.1–99.9% |
| Partial-sine duty adjustment | 0.1–99.9% |
| Sawtooth linearity | ≥98%, at 0.01 Hz–10 kHz |

The distortion specification is **not** a claim about maximum-amplitude RF output.
The manual names pulse and partial sine for adjustable duty, not square.

**Measured behavior of this unit:** SQUARE stayed at 50% duty when its register
reported 30%; PULSE produced approximately 30%. The driver rejects an explicitly
requested non-50% SQUARE duty. Use PULSE for adjustable duty on either channel in
ordinary wave mode. The dedicated MOD pulse function is a separate CH1-only mode.

## Manufacturer voltage, offset, phase, and output specifications

### Amplitude — pp. 7–8

| Waveform / frequency | Amplitude range stated in manual |
| --- | --- |
| Sine, frequency ≤10 MHz | 2 mVpp–20 Vpp |
| Sine, 10–30 MHz | 2 mVpp–10 Vpp |
| Sine, ≥30 MHz | 2 mVpp–5 Vpp |
| Square / triangle, frequency ≤10 MHz | 2 mVpp–20 Vpp |
| Square / triangle, 10–25 MHz | 2 mVpp–5 Vpp |

The table overlaps at exactly 10 MHz and 30 MHz. The current implementation
allows 20 Vpp at ≤10 MHz and 10 Vpp at >10 to ≤30 MHz for sine, then 5 Vpp above
30 MHz. It caps every non-sine waveform at 5 Vpp above 10 MHz. The manual only
explicitly gives the non-sine high-frequency amplitude table for square/triangle;
the general non-sine cap is a project guardrail.

| Property | Specification |
| --- | --- |
| Amplitude resolution | 1 mV |
| Amplitude stability | ±0.5% over 5 hours |
| Amplitude flatness | ±5% below 10 MHz; ±10% above 10 MHz |
| Output impedance | 50 Ω ±10%, typical |

The manual does **not** identify the load under which its amplitude figures are
specified, and does not give a dBm output rating, guaranteed output current,
or a verified maximum power into 50 Ω. The short-circuit statement on p. 8
contains “within 60” with no unit; it is not a usable duration or continuous
short-circuit rating.

### DC offset — p. 8

| Output amplitude | Allowed offset |
| --- | --- |
| >2 V | −9.99 to +9.99 V |
| >0.2 to ≤2 V | −2.5 to +2.5 V |
| >0 to ≤0.2 V | −0.25 to +0.25 V |

Offset resolution is 0.01 V. In addition to these amplitude-dependent ranges,
the server requires `abs(offset_v) + amplitude_vpp / 2 <= 10 V` to keep the
requested extrema within ±10 V. That combined check is a **project guardrail**,
not a formula explicitly supplied by this manual.

### Phase and TTL/CMOS — pp. 8–9, 13

- Inter-channel phase: 0–359.9°, resolution 0.1°. The display identifies it as
  the phase difference between CH1 and CH2. The server normalizes negative angles
  modulo 360; −90° becomes 270°. Physical phase has not been scope-verified.
- TTL/CMOS: low level <0.3 V, high level 1–10 V, rise/fall time ≤20 ns.
  Do not interpret the term TTL as a fixed 5 V level for this instrument.

## Calculating power into a 50-ohm load — derived, not a manual rating

For a **zero-offset sine** measured across the load:

```text
Vrms = Vpp_load / (2 * sqrt(2))
P_watts = Vrms^2 / R = Vpp_load^2 / (8 * R)
P_dBm = 10 * log10(P_watts / 0.001)
```

If the configured voltage is the unloaded/high-impedance voltage and the output
acts as a linear 50 Ω source, a 50 Ω load halves that voltage:
`Vpp_load = Vpp_setting * 50 / (50 + 50) = Vpp_setting / 2`.
Our low-amplitude high-impedance scope checks are consistent with that voltage
convention. They do not prove behavior at the maximum amplitude into 50 Ω.

| Frequency band, subject to model limit | Maximum sine setting | Assumed loaded Vpp | Nominal sine power |
| --- | --- | --- | --- |
| ≤10 MHz | 20 Vpp | 10 Vpp | 0.250 W = +23.98 dBm |
| >10 to <30 MHz | 10 Vpp | 5 Vpp | 0.0625 W = +17.96 dBm |
| >30 MHz | 5 Vpp | 2.5 Vpp | 0.015625 W = +11.94 dBm |

For the attached **15 MHz unit**, the relevant nominal estimates are **+24 dBm
through 10 MHz** and **+18 dBm above 10 MHz through 15 MHz**. These estimates are
conditional on the unloaded-voltage convention and linear source behavior. They
have not been measured with a 50 Ω termination; source impedance tolerance,
amplitude flatness, and loading can change the result. The ambiguous 30 MHz
boundary does not affect this 15 MHz unit.

For a symmetric zero-offset square wave, total power is `Vpp_load^2 / (4 * R)`:
10 Vpp into 50 Ω would be 0.5 W or +26.99 dBm **including harmonics**. It is not
the same as sine power or power in the fundamental alone. With DC offset, total
load dissipation includes the additional `Vdc_load^2 / R` term. Neither example
establishes the generator's loaded output capability.

## Modes, external input, and stored settings

### External measurement and counter — pp. 9, 16

Use the **Ext.IN** BNC input. MEAS switches between measurement and counter.
Measurement displays frequency, period, positive/negative pulse width, and duty.
AC/DC coupling and a gate time of 0.01–10 seconds are selectable. The gate-time
entry is under a misleading “measurement accuracy” label; no numerical accuracy
specification is supplied there.

| Property | Specification |
| --- | --- |
| Frequency measurement | 1 Hz–100 MHz |
| Counter range | 0–4,294,967,295 |
| Counter operation | Manually start/stop; AC or DC coupling |
| Pulse width measurement | 0.01 µs resolution, maximum 20 s |
| Period measurement | 0.01 µs resolution, maximum 20 s |
| Ext.IN amplitude | Conflicting lower bounds: 2 Vpp on p. 9; 2 mVpp on p. 16; both give 20 Vpp upper bound |

The external-input sensitivity discrepancy is unresolved. Do not promise 2 mVpp
sensitivity. The voltage range is not a specification for arbitrary DC offset,
transient tolerance, or input impedance. External measurement/counter behavior
has not been tested in this project.

### Sweep — pp. 10, 16–17

- CH1 **or** CH2; linear or logarithmic frequency sweep.
- Duration: 0.1–999.9 s. Start/end frequencies are within the corresponding
  model's range, with 0.01 Hz given as the low endpoint on p. 10.
- Direction: forward, reverse, or round trip. API names are `RISE`, `FALL`,
  `RISE&FALL`; scale names are `LINEAR`, `LOGARITHM`.
- `configure_sweep` validates both endpoints against the selected waveform,
  amplitude, and model limits, selects `SWEEP_CH1` or `SWEEP_CH2`, stops prior
  actions, writes parameters, and verifies readback. `start=false` is the default.
- Output enable state is preserved; use `set_outputs` separately when necessary.
  Return explicitly to `WAVE_CH1` or `WAVE_CH2` before ordinary configuration.
- Parameter/mode readback was tested; actual swept frequency versus time was not.

### Dedicated pulse and burst — pp. 6, 10, 16–18

MOD offers a **CH1-only dedicated pulse mode**, with digitally set width, period,
offset, and amplitude; width/period units can be switched between ns and µs.
Its pulse-width range depends on model (see the frequency table above).

MOD also offers **CH1-only burst mode**. Trigger choices are manual, internal
CH2, external AC, and external DC. The manual says the burst train must fit
within the triggering period. Pulse count is **1–1,048,575 on p. 10**, but the
procedure says **1–108,575 on p. 17**. That conflicting limit has not been tested.
Pulse/burst procedures reuse “start sweep” wording, apparently a copy/paste error.

This server can select `PULSE`/`BURST` modes and read diagnostic registers, but
does not expose high-level dedicated pulse/burst parameter or trigger tools.
Ordinary `configure_channel(waveform="PULSE")` is available on both channels
and is different from selecting dedicated `PULSE` mode.

### Profiles, arbitrary slots, and synchronization — pp. 10, 18

- 100 parameter profiles: slots **00–99**. **Slot 00 is recalled at power-on**.
  Saving it changes the startup configuration. Profiles can be saved, recalled,
  or cleared through the front-panel system menu; no high-level profile tool is
  exposed by this server.
- 60 arbitrary waveform slots; the manual says 15 are displayed by default.
  SYS can change the displayed count from 1–60. This controls menu visibility,
  not the physical waveform length or the total storage capacity.
- Sync uses CH1 as master. Each of frequency, waveform, amplitude, duty, and
  offset can be selected to make CH2 follow CH1. Check SYS before assuming
  a CH1 change leaves CH2 parameters untouched.
- Sound can be enabled/disabled, brightness is 0–12, and display languages are
  English and Chinese. Language selection is remembered after initial startup.

## Front-panel controls and general specifications

**Manual pp. 12–15:** front BNCs, left to right, are **Ext.IN, CH1, CH2**; the
rear has DC power and USB communication connectors. The display has channel
parameters, waveform preview, output status, soft-key menu, and phase difference.

| Control | Behavior |
| --- | --- |
| WAVE | Main interface / waveform selection / cancel |
| MEAS | Measurement interface / return to main |
| MOD | Sweep / dedicated pulse / burst interface / return to main |
| SYS | System settings / return to main |
| OK in main interface | Toggle both channel outputs together |
| OK in other interfaces | Control the relevant action's on/off state |
| CH1 / CH2 | Select channel; press selected key again to toggle its output; long press makes it the main display |
| Left/right arrows and knob | Select digit and adjust value; in waveform selection, switch preset/arbitrary group |
| Long press FREQ soft key | Change frequency units: MHz, kHz, Hz, mHz, µHz |
| Long press duty/offset/phase soft key | Reset the selected parameter to its default |

**Manual pp. 5, 10–11:** dimensions approximately 147.7 × 107.7 × 34.9 mm;
2.4-inch TFT color display; DC supply **5 V ±0.5 V**; operating environment
**0–40 °C**, relative humidity **<80%**. Communication is USB-to-serial at
**115200 baud**. The manual says the command protocol is public but omits it.
The server's actual serial configuration is 115200 baud, 8 data bits, no parity,
1 stop bit, with bounded reply/write timeouts.

## Serial protocol notes — library/project evidence, not the manual

Prefer validated MCP/CLI operations for writes. `read_register` is diagnostic;
it accepts registers 0–89 without changing mode. Some unsupported registers can
time out. The server intentionally does not expose arbitrary register writes.

Current transport sends ASCII lines such as `:r00=0.\n` for a register read and
`:w25=2000.\n` for an amplitude write (2 Vpp). Standard read replies are
`:rNN=<integer or comma-separated integers>.\r\n`; write acknowledgement is
`:ok\r\n`. Consume an entire line, rather than reading a fixed byte count.
Arbitrary slot reads use `:bNN=0.\n`; writes use `:aNN=<samples>.\n`.

| Register | Meaning / encoding |
| --- | --- |
| 0 / 1 | Model code / serial number |
| 20 | Output enables `[ch1, ch2]`, each 0 or 1 |
| 21 / 22 | CH1 / CH2 waveform ID |
| 23 / 24 | CH1 / CH2 frequency pair `[value, unit]` |
| 25 / 26 | CH1 / CH2 amplitude in mVpp |
| 27 / 28 | CH1 / CH2 offset: `offset_v * 100 + 1000` |
| 29 / 30 | CH1 / CH2 duty in tenths of a percent |
| 31 | Inter-channel phase in tenths of a degree |
| 32 | Four action flags; interpretation depends on mode |
| 33 / 35 | Operating mode / related read-only mode register; write and read encodings differ |
| 36 / 37 / 38 | Measurement coupling / gate time / frequency-or-period mode |
| 39 | Mode-dependent reset/manual-trigger action when written; not a harmless setting |
| 40–44 | Sweep start, end, duration, direction, linear/log scale |
| 45–48 | Dedicated pulse width, period, offset, amplitude |
| 49 / 50 | Burst pulse count / trigger mode |
| 51–56 | System settings; upstream reports shifted read/write addresses |
| 70 / 71 / 72 | Profile save / recall / clear actions |
| 80 | Counter result |
| 81–86 | Measurement frequency representations, positive/negative width, period, duty |
| 87–89 | Upstream labels their meanings uncertain; do not invent units |

Frequency units 0/1/2 are Hz/kHz/MHz display choices, all using `value / 100`
as the frequency in Hz. Unit 3 means `value / 100 * 1e-3 Hz`; unit 4 means
`value / 100 * 1e-6 Hz`. The library limits these precision modes to 80 kHz and
80 Hz respectively. The upstream text has inconsistent unit numbers in its
prose; the implementation uses 3 for mHz and 4 for µHz. The server chooses a
precision mode as needed and reads back the quantized value.

| Mode | Register 33 read value | Register 33 write value |
| --- | --- | --- |
| WAVE_CH1 | 0 | 0 |
| WAVE_CH2 | 16 | 1 |
| SYSTEM | 32 | 2 |
| MEASURE | 64 | 4 |
| COUNTER | 72 | 5 |
| SWEEP_CH1 | 80 | 6 |
| SWEEP_CH2 | 88 | 7 |
| PULSE | 96 | 8 |
| BURST | 104 | 9 |

Built-in waveform IDs 0–16 correspond, in order, to SINE, SQUARE, PULSE,
TRIANGLE, PARTIALSINE, CMOS, DC, HALF-WAVE, FULL-WAVE, POS-LADDER, NEG-LADDER,
NOISE, EXP-RIZE, EXP-DECAY, MULTI-TONE, SINC, LORENZ. Arbitrary IDs **101–160**
select slots **1–60**. Each uploaded slot requires **2048 integers from 0–4095**,
and the server verifies all samples by reading them back. This 12-bit upload
value range is a protocol/library convention; do not replace it with 0–16383
because the manual describes a 14-bit waveform output.

Upstream reports that reading system registers 52–56 returns sound, brightness,
language, sync, and displayed arbitrary count, whereas writing those settings
uses 51–55. That firmware quirk has **not** been verified on this unit. Check the
vendored library and hardware before implementing system-setting mutations.

## Local validation and remaining uncertainties

The tests on October 3, 2026 used the actual stdio JDS2800 MCP and Rigol scope
MCP. Approximate measurements with high-impedance inputs and direct coax:

| Setup | Scope observation |
| --- | --- |
| CH1 sine, 1 kHz, 2 Vpp | About 1 kHz and 2.1 Vpp on scope CH1 |
| CH2 sine, 2 kHz, 1 Vpp | About 2 kHz and 1.08 Vpp on scope CH3 |
| CH1 triangle, 1 kHz, 2 Vpp, +1 V offset | About 1 kHz, 2.1 Vpp, 0.998 V average |
| CH2 pulse, 2 kHz, 1 Vpp, 30% duty | About 2 kHz, 1.14 Vpp, 30.4% duty |
| CH1 disabled while CH2 remained enabled | CH1 fell to noise; CH3 retained its signal |

The reproduced automation sequence used CH1 triangle at 1 kHz, 2 Vpp, +1 V offset with
CH1 on and CH2 off. That behavior was reproduced. Negative phase normalization,
sweep settings/mode, and reading all 2048 samples from arbitrary slot 1 were
verified by register readback. Both outputs were left off after hardware tests.

Evidence is in project-root `artifacts/hardware-verification.json`,
`artifacts/scope-triangle-pulse.png`, and `artifacts/arbitrary-slot1-readback.json`.
These are functional checks, not amplitude calibration. Actual phase, sweep
progression, arbitrary playback/upload, external-input sensitivity, dedicated
pulse/burst operation, system sync, and maximum output into 50 Ω remain untested.
The new 6 MHz arbitrary frequency guard is tested without writing to hardware.

The Python driver was selected over the Rust alternative because it worked
with the prior automation sequence and allowed a hardened serial transport. The Rust
driver's combined reads left framing bytes behind and failed; see README.md and
`artifacts/rust-offset-read.txt`. No persistent arbitrary slots were overwritten
in the hardware comparison.

## Discrepancies future agents must preserve

- **50 Ω power:** the manual gives impedance and voltage ranges, but not their
  load convention or a rated maximum power. +24 dBm is a conditional calculation.
- **Ext.IN lower amplitude:** 2 Vpp (p. 9) versus 2 mVpp (p. 16).
- **Burst maximum:** 1,048,575 (p. 10) versus 108,575 (p. 17).
- **Short-circuit protection:** p. 8 has a missing unit after “60”.
- **Amplitude boundaries:** ranges overlap at exactly 10 MHz and 30 MHz.
- **Square duty:** a writable duty register does not guarantee an adjustable
  square waveform; use the measured PULSE behavior on this unit.
- **Resolution versus accuracy:** 1e-8 Hz frequency increment and 14-bit waveform
  resolution do not establish absolute output accuracy or serial upload range.
- **Series variants:** this PDF lists 15/40/60 MHz models. The transport also
  recognizes codes 30/50 for related units, but their specifications are not
  established by this manual.
