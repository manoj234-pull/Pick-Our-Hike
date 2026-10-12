from datetime import datetime
from zoneinfo import ZoneInfo

from pick_our_hike.route_facts import load_route_facts, posted_hours_status


def test_every_demo_destination_has_synthetic_primary_route_and_dog_rule():
    facts = load_route_facts()
    assert len(facts) == 10
    for destination in facts.values():
        route = destination["primary_route"]
        assert route["distance_miles"] > 0
        assert route["ascent_feet"] > 0
        assert destination["data_kind"] == "synthetic"
        assert destination["dog_access"] in {"allowed_leashed", "prohibited"}
        assert "dog_source_url" not in destination


def test_demo_opening_hours_apply_in_winter_and_summer():
    hours = load_route_facts()["fern-hollow"]["posted_hours"]
    assert posted_hours_status(hours, datetime(2026, 10, 12, 9, tzinfo=ZoneInfo("America/Los_Angeles"))) == "within_posted_hours"
    assert posted_hours_status(hours, datetime(2026, 10, 12, 21, tzinfo=ZoneInfo("America/Los_Angeles"))) == "outside_posted_hours"
    assert posted_hours_status(hours, datetime(2026, 7, 12, 18, tzinfo=ZoneInfo("America/Los_Angeles"))) == "within_posted_hours"


def test_dawn_to_dusk_does_not_invent_sunset():
    hours = {"kind": "daylight"}
    assert posted_hours_status(hours, datetime(2026, 10, 12, 12, tzinfo=ZoneInfo("America/Los_Angeles"))) == "needs_daylight_check"
