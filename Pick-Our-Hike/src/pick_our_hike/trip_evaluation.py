"""Deterministic planning against synthetic route metrics and demo travel data."""

from __future__ import annotations

from datetime import datetime, timedelta

from pick_our_hike.models import Check, Evaluation, GroupRequest
from pick_our_hike.route_facts import load_route_facts, posted_hours_status


METRES_PER_MILE = 1609.344
METRES_PER_FOOT = 0.3048


def _available_minutes(request: GroupRequest) -> int:
    start = datetime.combine(request.outing_date, request.start_time)
    end = datetime.combine(request.outing_date, request.latest_return_time)
    return int((end - start).total_seconds() // 60)


def evaluate_demo_trail(request: GroupRequest, trail_id: str, context: dict) -> Evaluation:
    """Check group limits using named-route metrics and illustrative drives.

    All route facts are fictional; this demo does not
    certify current trail access or weather safety.
    """
    facts = load_route_facts()[trail_id]
    route = facts["primary_route"]
    distance_km = route["distance_miles"] * METRES_PER_MILE / 1000
    ascent_m = route["ascent_feet"] * METRES_PER_FOOT
    checks: list[Check] = []
    if facts.get('access_note'):
        checks.append(Check(rule='access_warning', status='unknown', reason=facts['access_note']))
    for person in request.people:
        if person.max_distance_km is not None:
            checks.append(Check(
                rule=f"distance:{person.name}",
                status="pass" if distance_km <= person.max_distance_km else "fail",
                reason=f"{distance_km:.1f} km on synthetic {route['name']}; {person.name}'s limit is {person.max_distance_km:.1f} km",
            ))
        if person.max_ascent_m is not None:
            checks.append(Check(
                rule=f"ascent:{person.name}",
                status="pass" if ascent_m <= person.max_ascent_m else "fail",
                reason=f"{ascent_m:.0f} m route ascent; {person.name}'s limit is {person.max_ascent_m:.0f} m",
            ))

    for dog in request.dogs:
        if dog.max_distance_km is not None:
            checks.append(Check(
                rule="dog_distance" if len(request.dogs) == 1 else f"dog_distance:{dog.name}",
                status="pass" if distance_km <= dog.max_distance_km else "fail",
                reason=f"{distance_km:.1f} km synthetic route; {dog.name}'s limit is {dog.max_distance_km:.1f} km",
            ))
        if dog.max_ascent_m is not None:
            checks.append(Check(
                rule="dog_ascent" if len(request.dogs) == 1 else f"dog_ascent:{dog.name}",
                status="pass" if ascent_m <= dog.max_ascent_m else "fail",
                reason=f"{ascent_m:.0f} m route ascent; {dog.name}'s limit is {dog.max_ascent_m:.0f} m",
            ))
        dog_status = {'prohibited': 'fail', 'allowed_leashed': 'pass', 'allowed': 'pass'}.get(facts['dog_access'], 'unknown')
        checks.append(Check(
            rule="dog_access",
            status=dog_status,
            reason=f"Static route rule: {facts['dog_rule']}",
        ))

    slowest_pace = max(person.pace_minutes_per_km for person in request.people)
    hike_low = round(distance_km * slowest_pace + ascent_m / 100 * 12)
    hike_high = round(hike_low * 1.35)
    arrival = datetime.combine(request.outing_date, request.start_time) + timedelta(minutes=context["drive"]["outbound_minutes"])
    departure = arrival + timedelta(minutes=request.parking_minutes + hike_high + request.break_minutes)
    arrival_hours = posted_hours_status(facts["posted_hours"], arrival)
    finish_hours = posted_hours_status(facts["posted_hours"], departure)
    hours_explanations = {
        'within_posted_hours': 'within the posted opening hours',
        'outside_posted_hours': 'outside the posted opening hours',
        'needs_daylight_check': 'confirm daylight hours for your trip date before travelling',
        'hours_not_confirmed': 'opening hours have not been confirmed',
    }
    checks.append(Check(
        rule="posted_hours",
        status="fail" if "outside_posted_hours" in {arrival_hours, finish_hours} else ("pass" if {arrival_hours, finish_hours} == {"within_posted_hours"} else "unknown"),
        reason=f"{facts['posted_hours']['label']}; park arrival: {hours_explanations[arrival_hours]}; departure after breaks: {hours_explanations[finish_hours]}. This is not a live closure check.",
    ))

    drive = context["drive"]
    outbound, returning = drive["outbound_minutes"], drive["return_minutes"]
    if request.max_one_way_drive_minutes is not None:
        checks.append(Check(rule="drive_budget",
            status="pass" if max(outbound, returning) <= request.max_one_way_drive_minutes else "fail",
            reason=f"Drives: {outbound} min out, {returning} min back; maximum {request.max_one_way_drive_minutes:g} min each way"))
    preference_checks = []
    if request.preferred_one_way_drive_minutes is not None:
        duration = max(outbound, returning)
        preferred = request.preferred_one_way_drive_minutes
        fits = duration < preferred if request.drive_preference_strict else duration <= preferred
        preference_checks.append(Check(rule="preferred_drive", status="pass" if fits else "fail",
            reason=f"Drives: {outbound} min out, {returning} min back; preferred {'under' if request.drive_preference_strict else 'up to'} {preferred:g} min each way"))

    total = outbound + request.parking_minutes + hike_high + request.break_minutes + returning
    available = _available_minutes(request)
    checks.append(Check(
        rule="return_time",
        status="pass" if total <= available else "fail",
        reason=f"Return deadline: conservative demo outing {total} min including both drives, parking and breaks; {available} min available",
    ))

    if request.max_total_minutes is not None:
        checks.append(Check(rule='total_duration',
            status='pass' if total <= request.max_total_minutes else 'fail',
            reason=f'Total outing including both drives, hiking, parking and breaks: {total:g} min; your overall limit: {request.max_total_minutes:g} min'))
    statuses = {check.status for check in checks}
    overall = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
    return Evaluation(
        trail_id=trail_id,
        status=overall,
        checks=checks,
        preference_checks=preference_checks,
        hike_minutes_low=hike_low,
        hike_minutes_high=hike_high,
        total_minutes_high=total,
    )


def build_itinerary(request: GroupRequest, evaluation: Evaluation, context: dict) -> list[dict[str, str]]:
    """Create a conservative same-day schedule from a passing evaluation."""
    if evaluation.status == "fail":
        raise ValueError("A route violating confirmed requirements cannot produce an itinerary")
    drive = context["drive"]
    current = datetime.combine(request.outing_date, request.start_time)
    steps = [{"time": current.strftime("%H:%M"), "label": "Leave Redlands City Hall"}]
    for minutes, label in (
        (drive["outbound_minutes"], f"Arrive near {context['arrival']}"),
        (request.parking_minutes, "Start the hike after parking"),
        (evaluation.hike_minutes_high, "Finish the hike (conservative estimate)"),
        (request.break_minutes, "Finish breaks and depart"),
        (drive["return_minutes"], "Back at Redlands City Hall"),
    ):
        current += timedelta(minutes=minutes)
        steps.append({"time": current.strftime("%H:%M"), "label": label})
    return steps
