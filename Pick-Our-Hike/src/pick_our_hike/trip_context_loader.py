"""Load the dated, fictional scenario for the demo catalog."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[2] / "data" / "demo" / "offline_trip_context_2026-10-11.json"


def load_demo_snapshot(path: Path = DEFAULT_SNAPSHOT) -> dict:
    """Validate the minimal fields needed to present synthetic demo context."""
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("forecast_for_date") != "2026-10-11":
        raise ValueError("Unexpected demo forecast date")
    items = snapshot.get("destinations")
    if not isinstance(items, dict) or len(items) != 10:
        raise ValueError("Expected ten snapshot destinations")
    for identifier, item in items.items():
        weather = item.get("weather", {})
        drive = item.get("drive", {})
        park = item.get("park_facts", {})
        if weather.get("forecast_for_date") != snapshot["forecast_for_date"]:
            raise ValueError(f"Forecast date mismatch for {identifier}")
        if weather.get("source_name") != "Invented demo scenario":
            raise ValueError(f"Expected synthetic weather for {identifier}")
        if drive.get("basis") != "authored_demo_estimate_not_live_traffic" or any(drive.get(key, 0) <= 0 for key in ("outbound_miles", "outbound_minutes", "return_minutes")):
            raise ValueError(f"Invalid demo drive for {identifier}")
    return snapshot
