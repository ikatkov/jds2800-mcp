#!/usr/bin/env python3
"""Combine completed scope measurement runs into a validated, portable power profile."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from jds2800_mcp.calibrate import save
from jds2800_mcp.power import Calibration


def evidence_path(path):
    """Use repository-relative names when possible, never a machine-specific path."""
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def build(sources, output, verification=None):
    documents = [json.loads(path.read_text()) for path in sources]
    profile = copy.deepcopy(documents[0])
    if "RIGOL TECHNOLOGIES,DS1104Z," in profile["scope_info"]:
        profile["scope_analog_bandwidth_hz"] = 100e6
    profile["power_definition"] = (
        "AC RMS power calculated from numeric scope VRMS and VAVG into 50 ohms. "
        "Includes harmonics passed by the scope analog response; excludes DC. "
        "Not fundamental-only power or infinite-bandwidth total power."
    )
    profile["channels"] = {str(c): {"scope_channel": s, "curves": []} for c, s in ((1, 1), (2, 3))}
    profile["raw_measurements_sources"] = []
    methods = []
    for path, document in zip(sources, documents, strict=True):
        if document["status"] != "measured":
            raise ValueError(f"Incomplete measurement run: {path}")
        for key in (
            "device",
            "load_ohms",
            "waveform",
            "offset_v",
            "measurement_plane",
        ):
            if document[key] != documents[0][key]:
                raise ValueError(f"Measurement conditions differ for {key}: {path}")
        if document["scope_info"].splitlines()[0] != documents[0]["scope_info"].splitlines()[0]:
            raise ValueError(f"Scope identity differs: {path}")
        for key in ("duty_percent", "power_metric"):
            if document.get(key) != documents[0].get(key):
                raise ValueError(f"Measurement conditions differ for {key}: {path}")
        acquisition = document.get("measurement_plan", {}).get("acquisition", "AVER16")
        methods.append(acquisition)
        profile["raw_measurements_sources"].append(
            {
                "file": evidence_path(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "original_sha256": document.get("publication_redaction", {}).get(
                    "original_sha256", hashlib.sha256(path.read_bytes()).hexdigest()
                ),
                "acquisition": acquisition,
            }
        )
        for channel in ("1", "2"):
            for measured_curve in document["channels"][channel]["curves"]:
                curves = profile["channels"][channel]["curves"]
                curve = next(
                    (c for c in curves if c["frequency_hz"] == measured_curve["frequency_hz"]), None
                )
                if curve is None:
                    curve = {"frequency_hz": measured_curve["frequency_hz"], "points": []}
                    curves.append(curve)
                for raw in measured_curve["points"]:
                    if any(p["setting_vpp"] == raw["setting_vpp"] for p in curve["points"]):
                        raise ValueError("Duplicate frequency/amplitude measurement")
                    point = {k: v for k, v in raw.items() if k != "readings"}
                    if profile["waveform"] == "SQUARE":
                        # The sine Vpp cross-check is a diagnostic in raw evidence,
                        # not a valid square power value to expose in its profile.
                        point.pop("vpp_sine_dbm", None)
                    point["acquisition"] = acquisition
                    curve["points"].append(point)
    for channel in profile["channels"].values():
        channel["curves"].sort(key=lambda c: c["frequency_hz"])
        for curve in channel["curves"]:
            curve["points"].sort(key=lambda p: p["setting_vpp"])
    for key in (
        "initial_state",
        "final_state",
        "measurement_plan",
        "error",
        "verification",
        "publication_redaction",
    ):
        profile.pop(key, None)
    if any("publication_redaction" in document for document in documents):
        profile["publication_note"] = (
            "Connection metadata removed from public evidence; numeric measurements unchanged. "
            "Original evidence hashes retain the calibration identity."
        )
    source_digest = hashlib.sha256(
        "".join(s["original_sha256"] for s in profile["raw_measurements_sources"]).encode()
    ).hexdigest()[:12]
    waveform_tag = "-square" if profile["waveform"] == "SQUARE" else ""
    profile["calibration_id"] = (
        f"jds2800-{profile['device']['serial_number']}{waveform_tag}-50ohm-{source_digest}"
    )
    profile["method"] = (
        "Median of three numeric scope readings; AC RMS = sqrt(VRMS^2 - VAVG^2). "
        f"Acquisition by source: {', '.join(methods)}. Numeric Vpp retained."
    )
    if verification:
        report = json.loads(verification.read_text())
        if not report["passed"]:
            raise ValueError("Verification did not pass")
        if report["calibration"]["calibration_id"] != profile["calibration_id"]:
            raise ValueError("Verification refers to a different profile")
        profile["verification"] = {
            "passed": True,
            "created_at": report["created_at"],
            "checks": len(report["tests"]),
            "additional_cli_scope_checks": len(report.get("cli_measurements", [])),
            "maximum_absolute_error_db": report["maximum_absolute_error_db"],
            "tolerance_db": report["tolerance_db"],
            "measurement_method": report["measurement_method"],
            "requested_power_range_dbm": [
                min(t["requested_dbm"] for t in report["tests"]),
                max(t["requested_dbm"] for t in report["tests"]),
            ],
            "frequency_range_hz": [
                min(t["frequency_hz"] for t in report["tests"]),
                max(t["frequency_hz"] for t in report["tests"]),
            ],
            "acquisition": report["acquisition"],
            "file": evidence_path(verification),
            "sha256": hashlib.sha256(verification.read_bytes()).hexdigest(),
            "scope_referenced_only": True,
        }
    calibration = Calibration(profile)
    save(output, profile)
    return calibration.summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verification", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.sources, args.out, args.verification), indent=2))
