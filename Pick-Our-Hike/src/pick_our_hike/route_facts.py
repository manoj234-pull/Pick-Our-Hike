"""Static route facts and their interpretation limits."""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path


DEFAULT_ROUTE_FACTS = Path(__file__).resolve().parents[2] / "data" / "demo" / "route-facts.json"


def load_route_data(path: Path = DEFAULT_ROUTE_FACTS) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    destinations = data["destinations"]
    if len(destinations) != 10:
        raise ValueError("Expected facts for ten destinations")
    for identifier, facts in destinations.items():
        route = facts["primary_route"]
        if route["distance_miles"] <= 0 or route["ascent_feet"] <= 0:
            raise ValueError(f"Invalid route metrics for {identifier}")
        if facts.get("data_kind") != "synthetic":
            raise ValueError(f"Expected synthetic route for {identifier}")
    return data


def load_route_facts(path: Path = DEFAULT_ROUTE_FACTS) -> dict:
    return load_route_data(path)['destinations']


def posted_hours_status(hours: dict, when: datetime) -> str:
    """Check only fixed posted hours; never infer a current closure or sunset."""
    if hours["kind"] == "seasonal_fixed":
        season = "winter" if when.month in hours["winter_months"] else "summer"
        start = time.fromisoformat(hours[f"{season}_open"])
        end = time.fromisoformat(hours[f"{season}_close"])
        return "within_posted_hours" if start <= when.time().replace(tzinfo=None) < end else "outside_posted_hours"
    if hours["kind"] in {"daylight", "sunset"}:
        return "needs_daylight_check"
    return "hours_not_confirmed"
