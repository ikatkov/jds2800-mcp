"""Shared names and dispatch used by CLI batches and MCP."""

from .driver import Generator
from .manual import get_manual
from .power import PowerController
from .transport import ports


class API:
    def __init__(self, generator=None, calibration=None):
        self.generator = generator or Generator()
        self.power = PowerController(self.generator, calibration)
        self.operations = {
            "get_calibration": self.power.get_calibration,
            "preview_power": self.power.preview_power,
            "set_power": self.power.set_power,
            "get_manual": get_manual,
            "get_device_info": self.generator.info,
            "get_state": self.generator.state,
            "configure_channel": self.generator.configure,
            "set_outputs": self.generator.outputs,
            "set_phase": self.generator.phase,
            "set_mode": self.generator.mode,
            "configure_sweep": self.generator.sweep,
            "stop_outputs": self.generator.stop,
            "list_waveforms": self.generator.waveforms,
            "list_ports": ports,
            "read_register": self.generator.read_register,
            "read_arbitrary": self.generator.read_arbitrary,
            "upload_arbitrary": self.generator.upload_arbitrary,
        }

    def call(self, operation, arguments=None):
        if operation not in self.operations:
            raise ValueError(f"Unknown operation {operation!r}; choose {list(self.operations)}")
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
        return self.operations[operation](**(arguments or {}))
