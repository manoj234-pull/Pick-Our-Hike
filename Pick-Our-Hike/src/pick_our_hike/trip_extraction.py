"""LLM-facing schema and deterministic unit conversion for trip updates."""
from datetime import date, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator


class ExtractionModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


class Quantity(ExtractionModel):
    value: float = Field(ge=0)
    unit: Literal['miles', 'km', 'ft', 'm', 'hours', 'minutes', 'min/mile', 'min/km']


class PersonDelta(ExtractionModel):
    name: str
    changed_fields: list[Literal['max_distance', 'max_ascent', 'distance_unlimited', 'ascent_unlimited', 'pace']] = Field(default_factory=list, max_length=5)
    max_distance: Quantity | None = None
    max_ascent: Quantity | None = None
    distance_unlimited: bool | None = None
    ascent_unlimited: bool | None = None
    pace: Quantity | None = None


class DogDelta(ExtractionModel):
    name: str
    changed_fields: list[Literal['max_distance', 'max_ascent', 'distance_unlimited', 'ascent_unlimited', 'share_hiker_limits']] = Field(default_factory=list, max_length=5)
    max_distance: Quantity | None = None
    max_ascent: Quantity | None = None
    distance_unlimited: bool | None = None
    ascent_unlimited: bool | None = None
    share_hiker_limits: bool | None = None


class ExtractedTripPatch(ExtractionModel):
    """Only facts changed or explicitly cleared in the latest user turn."""
    changed_fields: list[Literal['outing_date', 'start_time', 'latest_return_time', 'people', 'dogs', 'remove_people', 'remove_dogs', 'max_total', 'max_one_way_drive', 'preferred_one_way_drive', 'drive_preference_strict', 'parking', 'breaks', 'clear_fields', 'shared_hiker_distance', 'shared_hiker_ascent', 'all_hikers_distance_unlimited', 'all_hikers_ascent_unlimited']] = Field(default_factory=list, max_length=18)
    outing_date: date | None = None
    start_time: Annotated[time, WithJsonSchema({'type': 'string', 'description': 'Local time HH:MM, no timezone'})] | None = None
    latest_return_time: Annotated[time, WithJsonSchema({'type': 'string', 'description': 'Local time HH:MM, no timezone'})] | None = None
    people: list[PersonDelta] | None = None
    dogs: list[DogDelta] | None = None
    remove_people: list[str] = Field(default_factory=list)
    remove_dogs: list[str] = Field(default_factory=list)
    max_total: Quantity | None = None
    max_one_way_drive: Quantity | None = None
    preferred_one_way_drive: Quantity | None = None
    drive_preference_strict: bool | None = None
    parking: Quantity | None = None
    breaks: Quantity | None = None
    shared_hiker_distance: Quantity | None = None
    shared_hiker_ascent: Quantity | None = None
    all_hikers_distance_unlimited: bool | None = None
    all_hikers_ascent_unlimited: bool | None = None
    clear_fields: list[Literal['max_total_minutes', 'max_one_way_drive_minutes', 'preferred_one_way_drive_minutes']] = Field(default_factory=list, max_length=3)

    @field_validator('changed_fields', 'clear_fields')
    @classmethod
    def unique_entries(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('List each changed field only once')
        return values


_FACTORS = {
    'distance': {'km': 1.0, 'miles': 1.609344},
    'elevation': {'m': 1.0, 'ft': 0.3048},
    'duration': {'minutes': 1.0, 'hours': 60.0},
    'pace': {'min/km': 1.0, 'min/mile': 1 / 1.609344},
}


def _as_canonical(quantity, dimension):
    if quantity is None:
        return None
    if isinstance(quantity, dict):
        value, unit = quantity['value'], quantity['unit']
    else:
        value, unit = quantity.value, quantity.unit
    factors = _FACTORS[dimension]
    if unit not in factors:
        raise ValueError(f'Incompatible unit {unit} for {dimension}')
    return value * factors[unit]


def apply_extracted_patch(raw, saved_trip=None):
    """Validate model output and translate it into canonical TripPatch fields."""
    patch = ExtractedTripPatch.model_validate(raw).model_dump(mode='python', exclude_unset=True)
    converted = {}
    selected = set(patch.get('changed_fields', []))
    for key in ('outing_date', 'start_time', 'latest_return_time', 'remove_people', 'remove_dogs', 'drive_preference_strict'):
        if key in selected and key in patch and patch[key] is not None:
            value = patch[key]
            converted[key] = value.isoformat(timespec='minutes') if isinstance(value, time) else value.isoformat() if isinstance(value, date) else value

    for source, target in [('max_total', 'max_total_minutes'), ('max_one_way_drive', 'max_one_way_drive_minutes'),
                           ('preferred_one_way_drive', 'preferred_one_way_drive_minutes'), ('parking', 'parking_minutes'),
                           ('breaks', 'break_minutes')]:
        if source in selected and source in patch and patch[source] is not None:
            converted[target] = _as_canonical(patch[source], 'duration')

    shared = {'people': {}, 'dogs': {}}
    for source, field, dimension, collection, display_key in (
        ('shared_hiker_distance', 'max_distance_km', 'distance', 'people', 'distance_unit'),
        ('shared_hiker_ascent', 'max_ascent_m', 'elevation', 'people', 'elevation_unit'),
    ):
        if source in selected and patch.get(source) is not None:
            quantity = patch[source]
            shared[collection][field] = _as_canonical(quantity, dimension)
            converted[display_key] = quantity['unit']
    for source, field in (('all_hikers_distance_unlimited', 'distance_unlimited'),
                          ('all_hikers_ascent_unlimited', 'ascent_unlimited')):
        if source in selected and patch.get(source) is True:
            shared['people'][field] = True

    dog_share_names = set()
    for collection in ('people', 'dogs'):
        if collection not in selected:
            continue
        for member in patch.get(collection) or []:
            changed = set(member.get('changed_fields', []))
            if 'max_distance' in changed and member.get('max_distance') and member['max_distance']['unit'] in ('miles', 'km'):
                converted['distance_unit'] = member['max_distance']['unit']
            if 'max_ascent' in changed and member.get('max_ascent') and member['max_ascent']['unit'] in ('ft', 'm'):
                converted['elevation_unit'] = member['max_ascent']['unit']

    for source, target, dimension in [('people', 'people', None), ('dogs', 'dogs', None)]:
        if source not in selected or source not in patch or patch[source] is None:
            continue
        rows = []
        for member in patch[source]:
            row = {'name': member.pop('name')}
            changed = set(member.pop('changed_fields', []))
            if source == 'dogs' and 'share_hiker_limits' in changed and member.get('share_hiker_limits') is True:
                dog_share_names.add(row['name'].casefold())
            if 'max_distance' in changed and member.get('max_distance') is not None:
                row['max_distance_km'] = _as_canonical(member.pop('max_distance'), 'distance')
            if 'max_ascent' in changed and member.get('max_ascent') is not None:
                row['max_ascent_m'] = _as_canonical(member.pop('max_ascent'), 'elevation')
            if 'pace' in changed and member.get('pace') is not None:
                row['pace_minutes_per_km'] = _as_canonical(member.pop('pace'), 'pace')
            member = {key: value for key, value in member.items() if key in changed and key != 'share_hiker_limits' and value is not None}
            row.update(member)
            rows.append(row)
        converted[target] = rows

    # Apply shared group limits mechanically to each current/new member. A specific
    # per-member change in the same message is overlaid afterward and takes precedence.
    saved_trip = saved_trip or {}
    for collection in ('people', 'dogs'):
        if collection not in selected and not shared[collection]:
            continue
        members = {row['name'].casefold(): dict(row) for row in saved_trip.get(collection, [])}
        for row in converted.get(collection, []):
            members.setdefault(row['name'].casefold(), {'name': row['name']})
        for field, value in shared[collection].items():
            for row in members.values():
                row[field] = value
        for row in members.values():
            for limit, flag in (('max_distance_km', 'distance_unlimited'), ('max_ascent_m', 'ascent_unlimited')):
                if shared[collection].get(flag) is True:
                    row[limit] = None
                elif limit in shared[collection] and row.get(flag):
                    row[flag] = False
        for row in converted.get(collection, []):
            key = row['name'].casefold()
            merged = {**members.get(key, {'name': row['name']}), **row}
            for limit, flag in (('max_distance_km', 'distance_unlimited'), ('max_ascent_m', 'ascent_unlimited')):
                if row.get(flag) is True:
                    merged[limit] = None
            members[key] = merged
        converted[collection] = list(members.values())

    # A dog's shared capability is the most restrictive stated capability in the
    # hiking party. If a hiker's distance cap is unknown, leave the dog's distance
    # unset so normal Pydantic readiness asks the user instead of guessing.
    if dog_share_names:
        hikers = {row['name'].casefold(): row for row in saved_trip.get('people', [])}
        for row in converted.get('people', []):
            hikers[row['name'].casefold()] = {**hikers.get(row['name'].casefold(), {}), **row}
        distance_known = bool(hikers) and all(row.get('max_distance_km') is not None or row.get('distance_unlimited') for row in hikers.values())
        finite_distances = [row['max_distance_km'] for row in hikers.values() if row.get('max_distance_km') is not None]
        finite_ascents = [row['max_ascent_m'] for row in hikers.values() if row.get('max_ascent_m') is not None]
        dogs = converted.get('dogs', [])
        for dog in dogs:
            if dog['name'].casefold() not in dog_share_names:
                continue
            if distance_known and finite_distances:
                dog['max_distance_km'] = min(finite_distances)
                dog['distance_unlimited'] = False
            elif distance_known:
                dog['distance_unlimited'] = True
            if finite_ascents:
                dog['max_ascent_m'] = min(finite_ascents)
                dog['ascent_unlimited'] = False
            elif hikers:
                dog['ascent_unlimited'] = True

    if 'clear_fields' in selected:
        for field in patch.get('clear_fields', []):
            converted[field] = None

    from pick_our_hike.models import TripPatch
    return TripPatch.model_validate(converted).model_dump(mode='json', exclude_unset=True)


def extraction_instructions(saved_trip, latest_message):
    """Keep turn interpretation in the model; Python only validates and converts."""
    import json
    return (
        'You extract the user\'s latest hiking-trip update into the supplied structured schema. '
        'Respond with a compact JSON object. Allowed root keys: changed_fields, outing_date (YYYY-MM-DD), '
        'start_time (HH:MM), latest_return_time (HH:MM), people, dogs, remove_people, remove_dogs, '
        'max_total, max_one_way_drive, preferred_one_way_drive, drive_preference_strict, parking, breaks, '
        'shared_hiker_distance, shared_hiker_ascent, all_hikers_distance_unlimited, all_hikers_ascent_unlimited, clear_fields. '
        'Quantities are objects with value and unit (miles, km, ft, m, hours, minutes, min/mile, min/km). '
        'People and dogs are arrays of objects with name and changed_fields; optional member fields are '
        'max_distance, max_ascent (quantities), distance_unlimited, ascent_unlimited (booleans); '
        'people can have pace (quantity), dogs can have share_hiker_limits (boolean). '
        'clear_fields contains only max_total_minutes, max_one_way_drive_minutes, preferred_one_way_drive_minutes. '
        'Omit all unused keys. Never repeat a key or a list entry. '
        'Return only the changes explicitly stated or clearly implied by the latest message. '
        'First list those keys in changed_fields. Python applies only keys in that list; do not list an unchanged key. '
        'For each person or dog, also list that row\'s changed_fields. Keep both lists short and unique. '
        'Never add parking or break changes unless the latest message explicitly mentions them. '
        'Use the saved trip to resolve references such as everyone, same as before, the dog, or everything else remains the same. '
        'Adding a dog changes the dog roster only: never infer its hiking capacity from the hikers unless explicitly told it shares their limits. '
        'Keep existing dogs when another is added. A previous no-dogs statement describes the previous roster, not a permanent prohibition. '
        'If a dog pronoun could refer to multiple dogs, do not guess which one changes. '
        'Do not repeat unchanged fields. Do not invent facts, names, limits, or default values. '
        'A newly named person or dog may be added; use Hiker 1 / Dog 1 only when the user gives a count but no names. '
        'When the user gives one distance or ascent limit to all hikers, use shared_hiker_distance or shared_hiker_ascent once instead of repeating it per person; Python applies it to every saved or newly named hiker. '
        'When the user says a dog can do the same as the hikers, set that dog\'s share_hiker_limits true; Python copies the most restrictive stated group capacity. Do not infer this unless the user says it. '
        'A shared limit applies only to the intended group. '
        'Preserve the user\'s number and unit in every Quantity. Distinguish one-way driving preference from a firm cap, '
        'and distinguish either from total outing duration. "Less than" means strict preference only when described as preferred; '
        'a hard maximum is a cap. When a new drive allowance replaces a saved one-way drive preference or cap, update the new drive field and clear the replaced field using clear_fields; do not keep both constraints. '
        'If a cap is explicitly removed, use clear_fields. If the latest message is ambiguous, '
        'return no speculative changes; the planner will ask for clarification. Names omitted from a group roster are not removals '
        'unless the user clearly changes the roster. For an explicit no-dogs request, remove existing dogs by name.\n\n'
        'Saved trip:\n' + json.dumps(saved_trip, ensure_ascii=False) +
        '\n\nLatest user message:\n' + latest_message
    )
