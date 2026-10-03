"""Packaged reference, available without opening any serial port."""

from importlib.resources import files

MANUAL_URI = "jds2800://manual"


def get_manual() -> str:
    return files("jds2800_mcp").joinpath("docs", "JDS2800-reference.md").read_text(encoding="utf-8")
