"""stdio MCP server; startup and discovery do not open the generator."""

import argparse
import json
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .api import API
from .driver import Generator
from .manual import MANUAL_URI
from .manual import get_manual as read_manual
from .power import (
    CALIBRATION_URI,
    POWER_GUIDE_URI,
    SQUARE_CALIBRATION_URI,
    SQUARE_POWER_GUIDE_URI,
    get_power_guide,
)
from .transport import Settings, ports


def create_server(generator=None):
    api = API(generator)
    app = FastMCP(
        "JDS2800",
        instructions="Control the connected JUNTEK JDS2800. Read get_manual or the "
        "jds2800://manual resource for specifications, load/power calculations, "
        "operating notes, and tested limitations before controlling the device. "
        "Hardware sync may make CH2 follow CH1; this server does not manage sync. "
        "For calibrated SINE or SQUARE output into 50 ohms use get_calibration, preview_power, "
        "and set_power with waveform specified (default SINE). Square power is AC RMS "
        "including harmonics within scope bandwidth, excluding DC; not fundamental-only power. "
        "Calibration is tied to the device serial and measured cables; "
        "it requires a physical 50-ohm load, and requests outside the table fail. "
        "Units are Hz, V peak-to-peak, "
        "V DC offset, percent duty, and degrees. Configure does not enable an off output "
        "unless enabled=true. It gates the target output during changes, validates limits, "
        "and verifies readback. Physical voltage depends on the load; direct coax into "
        "the Rigol uses probe=1; calibrated dBm requires external 50-ohm termination "
        "at its high-impedance input. get_device_info then get_state first. "
        "Connection is opened per operation; CLI and MCP share a process lock. "
        "stop_outputs stops actions and turns off both channels. Sweep mode must be "
        "returned explicitly to WAVE_CH1 or WAVE_CH2 before ordinary configuration.",
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
    writing = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)

    @app.resource(
        MANUAL_URI,
        name="JDS2800 reference",
        description="Manufacturer manual summary, protocol notes, and local hardware findings.",
        mime_type="text/markdown",
    )
    def manual_resource() -> str:
        return read_manual()

    @app.tool(annotations=read_only)
    def get_manual() -> str:
        """Read the bundled manual reference: model/frequency/voltage limits, 50-ohm
        power estimates, modes, synchronization, protocol notes, and tested behavior.
        Includes source page numbers and discrepancies. No serial port is opened.
        """
        return api.call("get_manual")

    @app.resource(
        CALIBRATION_URI,
        name="JDS2800 power calibration",
        description="Measured 50-ohm sine calibration metadata and covered frequency/power ranges.",
        mime_type="application/json",
    )
    def calibration_resource() -> str:
        return json.dumps(api.call("get_calibration"), indent=2)

    @app.resource(
        SQUARE_CALIBRATION_URI,
        name="JDS2800 square power calibration",
        description="Measured 50-ohm 50%-duty square AC RMS power, including harmonics.",
        mime_type="application/json",
    )
    def square_calibration_resource() -> str:
        return json.dumps(api.call("get_calibration", {"waveform": "SQUARE"}), indent=2)

    @app.resource(
        POWER_GUIDE_URI,
        name="JDS2800 dBm guide",
        description="Calibration conditions, measured tables, dBm examples, and uncertainty notes.",
        mime_type="text/markdown",
    )
    def power_guide_resource() -> str:
        return get_power_guide()

    @app.resource(
        SQUARE_POWER_GUIDE_URI,
        name="JDS2800 square dBm guide",
        description="Square AC RMS power definition, measured table, verification and bandwidth limits.",
        mime_type="text/markdown",
    )
    def square_power_guide_resource() -> str:
        return get_power_guide("SQUARE")

    @app.tool(annotations=read_only)
    def get_calibration(
        channel: Literal[1, 2] | None = None,
        include_points: bool = False,
        waveform: Literal["SINE", "SQUARE"] = "SINE",
    ) -> dict:
        """Read measured power calibration metadata/ranges without opening a port.
        include_points=true also returns the full amplitude/frequency measurement table.
        Select SINE (default) or SQUARE; separate measured tables are required.
        Applies to zero-offset, 50% duty into a physical 50-ohm load through measured cables.
        Square dBm is AC RMS including measured harmonics, excluding DC, not fundamental power.
        """
        return api.power.get_calibration(channel, include_points, waveform)

    @app.tool(annotations=read_only)
    def preview_power(
        channel: Literal[1, 2],
        frequency_hz: float,
        power_dbm: float,
        waveform: Literal["SINE", "SQUARE"] = "SINE",
    ) -> dict:
        """Check generator identity and calculate calibrated voltage for SINE or SQUARE power
        into 50 ohms. Interpolates measured levels/frequencies; no extrapolation or writes.
        Returns predicted power after 1 mV amplitude quantization, not a live measurement.
        Square dBm is AC RMS including measured harmonics, not fundamental-only power.
        """
        return api.power.preview_power(channel, frequency_hz, power_dbm, waveform)

    @app.tool(annotations=writing)
    def set_power(
        channel: Literal[1, 2],
        frequency_hz: float,
        power_dbm: float,
        enabled: bool | None = None,
        waveform: Literal["SINE", "SQUARE"] = "SINE",
    ) -> dict:
        """Set calibrated SINE or SQUARE power into a physical 50-ohm load using its own table.
        Sets the selected waveform (default SINE), DC offset=0, duty=50, frequency/amplitude.
        Square dBm is AC RMS including harmonics within scope bandwidth, excluding DC;
        it is not fundamental-only power. Requires wave
        mode and matching serial number. Preserves enabled state unless supplied.
        Predicted dBm includes measured cable loss; CMOS, other loads and duty cycles unsupported.
        Uses register readback; it does not remeasure the signal with the scope.
        """
        return api.power.set_power(channel, frequency_hz, power_dbm, enabled, waveform)

    @app.tool(annotations=read_only)
    def list_ports() -> list[dict]:
        """List USB serial ports without opening the generator."""
        return ports()

    @app.tool(annotations=read_only)
    def list_waveforms() -> list[dict]:
        """List built-in waveform names/IDs and the 60 arbitrary waveform slots."""
        return api.call("list_waveforms")

    @app.tool(annotations=read_only)
    def get_device_info() -> dict:
        """Read the model code, serial number, port and detected sine frequency limit."""
        return api.call("get_device_info")

    @app.tool(annotations=read_only)
    def get_state(channel: Literal[1, 2] | None = None) -> dict:
        """Read mode, phase and channel settings. Omit channel to read both."""
        return api.call("get_state", {"channel": channel})

    @app.tool(annotations=writing)
    def configure_channel(
        channel: Literal[1, 2],
        waveform: str | int | None = None,
        frequency_hz: float | None = None,
        amplitude_vpp: float | None = None,
        offset_v: float | None = None,
        duty_percent: float | None = None,
        enabled: bool | None = None,
    ) -> dict:
        """Set channel parameters in wave mode and verify them. Unspecified settings
        are preserved. Output is gated during changes; its previous enable state is
        restored unless enabled is supplied. Limits follow the detected model.
        On communication/readback failure the target output is requested off.
        SQUARE is physically 50% duty; use PULSE for adjustable duty.
        """
        return api.generator.configure(
            channel, waveform, frequency_hz, amplitude_vpp, offset_v, duty_percent, enabled
        )

    @app.tool(annotations=writing)
    def set_outputs(ch1: bool | None = None, ch2: bool | None = None) -> dict:
        """Enable or disable outputs independently, preserving unspecified output state."""
        return api.generator.outputs(ch1, ch2)

    @app.tool(annotations=writing)
    def set_phase(phase_deg: float) -> dict:
        """Set inter-channel phase, normalized to 0..359.9 degrees, with readback."""
        return api.generator.phase(phase_deg)

    @app.tool(annotations=writing)
    def set_mode(
        mode: Literal[
            "WAVE_CH1",
            "WAVE_CH2",
            "MEASURE",
            "COUNTER",
            "SWEEP_CH1",
            "SWEEP_CH2",
            "PULSE",
            "BURST",
            "SYSTEM",
        ],
    ) -> dict:
        """Stop current actions, select the operating mode and verify it."""
        return api.generator.mode(mode)

    @app.tool(annotations=writing)
    def configure_sweep(
        channel: Literal[1, 2],
        start_hz: float,
        end_hz: float,
        time_s: float,
        direction: Literal["RISE", "FALL", "RISE&FALL"] = "RISE",
        scale: Literal["LINEAR", "LOGARITHM"] = "LINEAR",
        start: bool = False,
    ) -> dict:
        """Switch to sweep mode, configure and read back limits. start=true starts
        the sweep. Output enable state is preserved; use set_outputs separately.
        """
        return api.generator.sweep(channel, start_hz, end_hz, time_s, direction, scale, start)

    @app.tool(annotations=writing)
    def stop_outputs() -> dict:
        """Stop sweep/counter/pulse/burst actions and disable both output channels."""
        return api.call("stop_outputs")

    @app.tool(annotations=read_only)
    def read_register(register: int) -> dict:
        """Read a protocol register 0..89 for diagnostics or measurement/counter data.
        Unsupported registers may time out; this does not select a mode.
        """
        return api.generator.read_register(register)

    @app.tool(annotations=read_only)
    def read_arbitrary(slot: int) -> dict:
        """Read all 2048 samples from an arbitrary waveform slot, numbered 1..60."""
        return api.generator.read_arbitrary(slot)

    @app.tool(annotations=writing)
    def upload_arbitrary(slot: int, samples: list[int]) -> dict:
        """Overwrite slot 1..60 with 2048 integer samples (0..4095) and verify readback.
        This changes device waveform storage; it does not select the slot or enable output.
        """
        return api.generator.upload_arbitrary(slot, samples)

    return app


def main():
    parser = argparse.ArgumentParser(description="JDS2800 stdio MCP server")
    parser.add_argument("--port", help="Serial device; defaults to JDS2800_PORT or auto-detection")
    parser.add_argument("--timeout", type=float, help="Serial reply timeout in seconds")
    args = parser.parse_args()
    env = Settings.from_env()
    settings = Settings(
        args.port or env.port,
        args.timeout if args.timeout is not None else env.timeout,
        env.lock_timeout,
    )
    create_server(Generator(settings)).run(transport="stdio")


if __name__ == "__main__":
    main()
