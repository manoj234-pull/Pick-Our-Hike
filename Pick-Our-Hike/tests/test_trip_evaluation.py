from datetime import date, time

from pick_our_hike.route_facts import load_route_facts
from pick_our_hike.trip_evaluation import build_itinerary, evaluate_demo_trail
from pick_our_hike.trip_context_loader import load_demo_snapshot
from pick_our_hike.models import Dog, GroupRequest, Person


TRAILS = {key: key for key in load_route_facts()}
SNAPSHOT = load_demo_snapshot()["destinations"]


def request(**changes):
    values = dict(
        outing_date=date(2026, 10, 11),
        start_time=time(8),
        latest_return_time=time(17),
        people=[Person(name="Alex", max_distance_km=10, max_ascent_m=1000, pace_minutes_per_km=20)],
        max_one_way_drive_minutes=150,
        parking_minutes=15,
        break_minutes=20,
    )
    values.update(changes)
    return GroupRequest(**values)


def statuses(report):
    return {check.rule: check.status for check in report.checks}


def test_group_distance_and_ascent_use_every_member_limit():
    group = request(people=[
        Person(name="Alex", max_distance_km=10, max_ascent_m=1000, pace_minutes_per_km=18),
        Person(name="Sam", max_distance_km=3, max_ascent_m=40, pace_minutes_per_km=27),
    ])
    report = evaluate_demo_trail(group, TRAILS["cedar-meadow"], SNAPSHOT["cedar-meadow"])
    assert report.status == "fail"
    assert statuses(report)["distance:Sam"] == "fail"
    assert statuses(report)["ascent:Sam"] == "fail"
    assert report.hike_minutes_high > report.hike_minutes_low


def test_dog_prohibition_blocks_and_leashed_route_passes():
    group = request(dogs=[Dog(name="Scout", max_distance_km=10)])
    banned = evaluate_demo_trail(group, TRAILS["fern-hollow"], SNAPSHOT["fern-hollow"])
    allowed = evaluate_demo_trail(group, TRAILS["cedar-meadow"], SNAPSHOT["cedar-meadow"])
    assert statuses(banned)["dog_access"] == "fail"
    assert statuses(allowed)["dog_access"] == "pass"
    assert allowed.status == "pass"


def test_posted_hours_drive_budget_and_return_deadline():
    outside_hours = evaluate_demo_trail(request(start_time=time(18), latest_return_time=time(23)), TRAILS["fern-hollow"], SNAPSHOT["fern-hollow"])
    far = evaluate_demo_trail(request(max_one_way_drive_minutes=15), TRAILS["cedar-meadow"], SNAPSHOT["cedar-meadow"])
    late = evaluate_demo_trail(request(latest_return_time=time(10)), TRAILS["cedar-meadow"], SNAPSHOT["cedar-meadow"])
    assert statuses(outside_hours)["posted_hours"] == "fail"
    assert statuses(far)["drive_budget"] == "fail"
    assert statuses(late)["return_time"] == "fail"


def test_route_must_finish_before_fixed_park_closing_time():
    afternoon = request(start_time=time(17), latest_return_time=time(23))
    report = evaluate_demo_trail(afternoon, TRAILS["fern-hollow"], SNAPSHOT["fern-hollow"])
    assert statuses(report)["posted_hours"] == "fail"


def test_park_arrival_before_opening_does_not_pass_after_parking():
    from copy import deepcopy
    context = deepcopy(SNAPSHOT['fern-hollow'])
    context['drive']['outbound_minutes'] = 55
    report = evaluate_demo_trail(request(start_time=time(5)), TRAILS['fern-hollow'], context)
    assert statuses(report)['posted_hours'] == 'fail'


def test_itinerary_uses_slowest_pace_and_both_drives():
    group = request(people=[
        Person(name="Alex", max_distance_km=10, pace_minutes_per_km=15),
        Person(name="Sam", max_distance_km=10, pace_minutes_per_km=25),
    ])
    trail = TRAILS["cedar-meadow"]
    report = evaluate_demo_trail(group, trail, SNAPSHOT[trail])
    assert report.status == "pass"
    itinerary = build_itinerary(group, report, SNAPSHOT[trail])
    assert itinerary[-1]["time"] <= "17:00"
    assert itinerary[-1]["label"] == "Back at Redlands City Hall"
    assert report.total_minutes_high == (
        SNAPSHOT[trail]["drive"]["outbound_minutes"]
        + group.parking_minutes + report.hike_minutes_high
        + group.break_minutes + SNAPSHOT[trail]["drive"]["return_minutes"]
    )



def test_park_hours_explanation_uses_plain_language():
    report = evaluate_demo_trail(request(), 'cedar-meadow', SNAPSHOT['cedar-meadow'])
    check = next(c for c in report.checks if c.rule == 'posted_hours')
    assert 'needs_daylight_check' not in check.reason
    assert 'within the posted opening hours' in check.reason
    assert check.status == 'pass'
