"""
Mock OEM thermostat partner API (local Flask server).

In production, enrollment and telemetry would be fetched from a real partner endpoint
such as https://api.resideo.com/devices or https://nestenergy.googleapis.com/v1/devices.
This module replaces those calls for local development and pipeline testing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Flask, jsonify, request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENROLLMENT_CSV = PROJECT_ROOT / "data" / "raw" / "partner_enrollment_portal.csv"
DEVICE_COUNT = 7200
RNG = np.random.default_rng(42)

UTILITY_GEO = {
    "ComEd": {"state": "IL", "lat_center": 41.88, "lon_center": -87.62},
    "PPL": {"state": "PA", "lat_center": 40.27, "lon_center": -76.88},
    "PECO": {"state": "PA", "lat_center": 39.95, "lon_center": -75.16},
    "PSEG-LI": {"state": "NY", "lat_center": 40.79, "lon_center": -73.13},
    "AmerenIL": {"state": "IL", "lat_center": 39.78, "lon_center": -89.65},
}

FIRMWARE_BY_PREFIX = {
    "RSO": [4.2, "4.2.1", "5.0.0", "5.0.1"],
    "NEST": [3.1, "3.1.2", "3.2.0"],
    "ECO": [4.7, "4.7.3", "4.8.0"],
}

CONNECTIVITY_STATUSES = ["online", "offline", "unknown"]
MODES = ["heat", "cool", "auto"]
HISTORY_END = datetime(2025, 3, 1)

app = Flask(__name__)
DEVICES: dict[str, dict] = {}
DEVICE_INDEX: list[dict] = []


def csv_serial_to_api_device_id(serial: str) -> str:
    """API uses underscore IDs; enrollment CSV mostly uses dash separators."""
    return serial.replace("-", "_")


def device_prefix(device_id: str) -> str:
    return device_id.split("_", 1)[0]


def build_location(state: str, null_location: bool) -> dict | None:
    if null_location:
        return None
    lat_jitter = float(RNG.uniform(-0.8, 0.8))
    lon_jitter = float(RNG.uniform(-0.8, 0.8))
    geo = next(
        (g for g in UTILITY_GEO.values() if g["state"] == state),
        {"state": state, "lat_center": 40.0, "lon_center": -75.0},
    )
    return {
        "zip": f"{RNG.integers(10000, 99999)}",
        "state": state,
        "lat": round(geo["lat_center"] + lat_jitter, 4),
        "lon": round(geo["lon_center"] + lon_jitter, 4),
    }


def build_runtime_history(empty_history: bool) -> list[dict]:
    if empty_history:
        return []

    history: list[dict] = []
    for day_offset in range(30, 0, -1):
        day = HISTORY_END - timedelta(days=day_offset)
        history.append(
            {
                "date": day.strftime("%Y-%m-%d"),
                "runtime_minutes": int(RNG.integers(20, 720)),
                "setpoint_delta_f": round(float(RNG.uniform(-4.0, 4.0)), 1),
                "mode": str(RNG.choice(MODES)),
                "responded_to_event": bool(RNG.choice([True, False], p=[0.12, 0.88])),
            }
        )
    return history


def build_device_record(
    *,
    csv_serial: str,
    utility_zone: str,
    null_location: bool,
    empty_history: bool,
) -> dict:
    device_id = csv_serial_to_api_device_id(csv_serial)
    prefix = device_prefix(device_id)
    geo = UTILITY_GEO.get(utility_zone, {"state": "IL"})

    last_seen = int((HISTORY_END - timedelta(hours=int(RNG.integers(1, 72)))).timestamp())
    hardwired = bool(RNG.choice([True, False], p=[0.65, 0.35]))

    device = {
        "device_id": device_id,
        "firmware_version": RNG.choice(FIRMWARE_BY_PREFIX.get(prefix, ["4.2.1"])),
        "last_seen_timestamp": last_seen,
        "battery_level": None if hardwired else int(RNG.integers(5, 100)),
        "location": build_location(geo["state"], null_location),
        "connectivity_status": str(RNG.choice(CONNECTIVITY_STATUSES, p=[0.82, 0.12, 0.06])),
        "runtime_history": build_runtime_history(empty_history),
    }
    return device


def load_devices() -> None:
    df = pd.read_csv(ENROLLMENT_CSV, usecols=["device_serial", "utility_zone"])
    df = df.copy()
    df["api_device_id"] = df["device_serial"].map(csv_serial_to_api_device_id)
    df = df.drop_duplicates(subset=["api_device_id"]).reset_index(drop=True)

    if len(df) < DEVICE_COUNT:
        raise ValueError(
            f"Need at least {DEVICE_COUNT} unique API device IDs; "
            f"found {len(df)} in {ENROLLMENT_CSV}"
        )

    selected = df.sample(n=DEVICE_COUNT, random_state=42).reset_index(drop=True)
    null_location_mask = RNG.random(DEVICE_COUNT) < 0.05
    empty_history_mask = RNG.random(DEVICE_COUNT) < 0.08

    for i in range(DEVICE_COUNT):
        row = selected.iloc[i]
        device = build_device_record(
            csv_serial=str(row["device_serial"]),
            utility_zone=str(row["utility_zone"]),
            null_location=bool(null_location_mask[i]),
            empty_history=bool(empty_history_mask[i]),
        )
        DEVICES[device["device_id"]] = device

    DEVICE_INDEX.clear()
    for device in DEVICES.values():
        DEVICE_INDEX.append(
            {
                "device_id": device["device_id"],
                "firmware_version": device["firmware_version"],
                "last_seen_timestamp": device["last_seen_timestamp"],
                "connectivity_status": device["connectivity_status"],
            }
        )


def flatten_devices_to_dataframe(devices: dict[str, dict] | None = None) -> pd.DataFrame:
    source = devices if devices is not None else DEVICES
    flattened_rows: list[dict] = []
    for device in source.values():
        device_id = str(device["device_id"]).replace("_", "-")
        last_seen_dt = pd.to_datetime(device["last_seen_timestamp"], unit="s", utc=True).tz_convert(None)
        history = device.get("runtime_history") or []
        runtime_history_empty = len(history) == 0
        location = device.get("location") or {}
        base_row = {
            "device_id": device_id,
            "firmware_version": str(device.get("firmware_version")),
            "last_seen_timestamp": last_seen_dt,
            "battery_level": device.get("battery_level"),
            "connectivity_status": device.get("connectivity_status"),
            "location_zip": location.get("zip"),
            "location_state": location.get("state"),
            "location_lat": location.get("lat"),
            "location_lon": location.get("lon"),
            "runtime_history_empty": runtime_history_empty,
        }
        if runtime_history_empty:
            row = base_row.copy()
            row.update(
                {
                    "runtime_date": pd.NaT,
                    "runtime_minutes": pd.NA,
                    "setpoint_delta_f": pd.NA,
                    "mode": pd.NA,
                    "responded_to_event": pd.NA,
                }
            )
            flattened_rows.append(row)
        else:
            for entry in history:
                row = base_row.copy()
                row.update(
                    {
                        "runtime_date": pd.to_datetime(entry["date"]),
                        "runtime_minutes": entry.get("runtime_minutes"),
                        "setpoint_delta_f": entry.get("setpoint_delta_f"),
                        "mode": entry.get("mode"),
                        "responded_to_event": entry.get("responded_to_event"),
                    }
                )
                flattened_rows.append(row)
    return pd.DataFrame(flattened_rows)


def build_devices_dataframe() -> pd.DataFrame:
    DEVICES.clear()
    DEVICE_INDEX.clear()
    load_devices()
    return flatten_devices_to_dataframe()


@app.get("/api/devices")
def list_devices():
    return jsonify({"count": len(DEVICE_INDEX), "devices": DEVICE_INDEX})


@app.get("/api/devices/<device_id>")
def get_device(device_id: str):
    device = DEVICES.get(device_id)
    if device is None:
        return jsonify({"error": f"Device not found: {device_id}"}), 404
    return jsonify(device)


@app.post("/api/devices/bulk")
def bulk_devices():
    payload = request.get_json(silent=True) or {}
    device_ids = payload.get("device_ids", [])
    if not isinstance(device_ids, list):
        return jsonify({"error": "device_ids must be a list"}), 400

    found = []
    missing = []
    for device_id in device_ids:
        device = DEVICES.get(str(device_id))
        if device is None:
            missing.append(str(device_id))
        else:
            found.append(device)

    return jsonify(
        {
            "requested": len(device_ids),
            "found": len(found),
            "missing": missing,
            "devices": found,
        }
    )


def main() -> None:
    load_devices()
    print(
        f"Mock thermostat API loaded {len(DEVICES):,} devices from "
        f"{ENROLLMENT_CSV.name}",
        flush=True,
    )
    print("Starting server at http://localhost:5001", flush=True)
    app.run(host="127.0.0.1", port=5001, debug=False)


if __name__ == "__main__":
    main()
