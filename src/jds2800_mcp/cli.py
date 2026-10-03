"""JSON stdout, JSON error stderr and nonzero exit status for scripting."""

import argparse
import json
import sys
from pathlib import Path

from .api import API
from .driver import Generator
from .transport import Settings


def boolean(value):
    value = value.lower()
    if value in ("on", "true", "1"):
        return True
    if value in ("off", "false", "0"):
        return False
    raise argparse.ArgumentTypeError("Use on or off")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", help="Serial device; or set JDS2800_PORT")
    p.add_argument("--timeout", type=float)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("info", "ports", "waveforms", "manual", "stop"):
        sub.add_parser(name)
    calibration = sub.add_parser("calibration", help="Read 50-ohm power calibration metadata/table")
    calibration.add_argument("--channel", type=int, choices=(1, 2))
    calibration.add_argument("--include-points", action="store_true")
    calibration.add_argument("--waveform", choices=("SINE", "SQUARE"), default="SINE")
    for name in ("power", "preview-power"):
        power = sub.add_parser(
            name, help="Calibrated zero-offset SINE/SQUARE AC power into 50 ohms"
        )
        power.add_argument("channel", type=int, choices=(1, 2))
        power.add_argument("--frequency-hz", type=float, required=True)
        power.add_argument("--dbm", dest="power_dbm", type=float, required=True)
        power.add_argument("--waveform", choices=("SINE", "SQUARE"), default="SINE")
        if name == "power":
            power.add_argument("--enabled", type=boolean)
    state = sub.add_parser("state")
    state.add_argument("--channel", type=int, choices=(1, 2))
    conf = sub.add_parser("configure")
    conf.add_argument("channel", type=int, choices=(1, 2))
    conf.add_argument("--waveform")
    conf.add_argument("--frequency-hz", type=float)
    conf.add_argument("--amplitude-vpp", type=float)
    conf.add_argument("--offset-v", type=float)
    conf.add_argument("--duty-percent", type=float)
    conf.add_argument("--enabled", type=boolean)
    out = sub.add_parser("outputs")
    out.add_argument("--ch1", type=boolean)
    out.add_argument("--ch2", type=boolean)
    phase = sub.add_parser("phase")
    phase.add_argument("phase_deg", type=float)
    mode = sub.add_parser("mode")
    mode.add_argument("mode")
    call = sub.add_parser("call", help="Call any MCP operation directly with JSON arguments")
    call.add_argument("operation")
    call.add_argument("--args", default="{}", help="JSON object")
    batch = sub.add_parser(
        "batch", help="Run JSON operations sequentially, stopping on first error"
    )
    batch.add_argument("file", help="JSON array file, or - for stdin")
    return p


def run(api, args):
    values = vars(args).copy()
    command = values.pop("command")
    values.pop("port")
    values.pop("timeout")
    mapping = {
        "calibration": "get_calibration",
        "power": "set_power",
        "preview-power": "preview_power",
        "info": "get_device_info",
        "ports": "list_ports",
        "waveforms": "list_waveforms",
        "manual": "get_manual",
        "stop": "stop_outputs",
        "state": "get_state",
        "configure": "configure_channel",
        "outputs": "set_outputs",
        "phase": "set_phase",
        "mode": "set_mode",
    }
    if command == "call":
        return api.call(values["operation"], json.loads(values["args"]))
    if command == "batch":
        contents = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        operations = json.loads(contents)
        if not isinstance(operations, list) or not operations:
            raise ValueError("Batch must be a nonempty JSON array")
        for entry in operations:
            if (
                not isinstance(entry, dict)
                or set(entry) - {"operation", "arguments"}
                or entry.get("operation") not in api.operations
                or not isinstance(entry.get("arguments", {}), dict)
            ):
                raise ValueError("Each entry needs a known operation and optional arguments object")
        results = []
        # Entire batch holds one lease. Prior successful operations are not rolled
        # back if a later operation fails; report their results in the error.
        with api.generator.io.session():
            for index, entry in enumerate(operations):
                try:
                    results.append(api.call(entry["operation"], entry.get("arguments")))
                except Exception as exc:
                    raise BatchError(index, results, str(exc)) from exc
        return results
    if command == "configure" and (values.get("waveform") or "").isdigit():
        values["waveform"] = int(values["waveform"])
    return api.call(mapping[command], values)


class BatchError(RuntimeError):
    def __init__(self, index, completed, error):
        super().__init__(error)
        self.index, self.completed = index, completed


def main():
    args = parser().parse_args()
    try:
        env = Settings.from_env()
        settings = Settings(
            args.port or env.port,
            args.timeout if args.timeout is not None else env.timeout,
            env.lock_timeout,
        )
        result = run(API(Generator(settings)), args)
        print(json.dumps(result, indent=2, allow_nan=False))
    except Exception as exc:
        error = {"error": str(exc), "type": type(exc).__name__}
        if isinstance(exc, BatchError):
            error.update(failed_index=exc.index, completed=exc.completed)
        print(json.dumps(error, allow_nan=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
