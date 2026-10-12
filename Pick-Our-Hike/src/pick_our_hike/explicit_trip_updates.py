"""Conservative handling of explicit trip facts; unfamiliar wording stays with the LLM."""
import re
from datetime import datetime


def explicit_trip_patch(text, saved):
    lower = text.lower()
    patch = {}
    recognized = []

    def mark(match):
        if match:
            recognized.append(match.span())
        return match

    date_match = re.search(r'\b([A-Za-z]+ \d{1,2},? \d{4}|\d{1,2}/\d{1,2}/\d{4})\b', text)
    if date_match:
        for fmt in ('%B %d, %Y', '%B %d %Y', '%m/%d/%Y'):
            try:
                patch['outing_date'] = datetime.strptime(date_match[1], fmt).date().isoformat()
                mark(date_match)
                break
            except ValueError:
                pass
    for field, pattern in (
        ('start_time', r'\b(?:leav\w*|depart\w*|start\w*)\s*(?:at|around)?\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)\b'),
        ('latest_return_time', r'\b(?:return\w*|(?:be )?back)\s*(?:at|by|around)?\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)\b'),
    ):
        match = re.search(pattern, lower)
        if match:
            clock = match[1] + match[2]
            patch[field] = datetime.strptime(clock, '%I:%M%p' if ':' in clock else '%I%p').strftime('%H:%M')
            mark(match)
    names = re.search(r'(?:\b|^)([A-Za-z]+(?:\s*,\s*[A-Za-z]+)*\s+and\s+[A-Za-z]+)\s+can\s+(?:each\s+)?hike', text)
    if names:
        patch['people'] = [{'name': n.strip()} for n in re.split(r'\s*,\s*|\s+and\s+', names[1])]
        mark(names)
    people = [dict(p) for p in patch.get('people', saved.get('people', []))]
    distance = re.search(r'\bhike\s+(?:(?:for|up to|only|at most|a maximum of)\s+)*(\d+(?:\.\d+)?)\s*(miles?|kilomet(?:er|re)s?|km)\b', lower)
    ascent = re.search(r'\b(\d+(?:\.\d+)?)\s*(feet|foot|ft|meters?|metres?|m)\s*(?:of\s+)?(?:ascent|uphill|elevation gain)\b', lower)
    unlimited = re.search(r'\bno\s+(?:ascent\s+or\s+(?:hike\s+)?distance|(?:hike\s+)?distance\s+or\s+ascent)\s+(?:limitations|limits|restrictions)\b', lower)
    if people and (distance or ascent or unlimited):
        for person in people:
            if distance:
                person['max_distance_km'] = float(distance[1]) * (1.609344 if distance[2].startswith('mile') else 1)
                person['distance_unlimited'] = False
                patch['distance_unit'] = 'miles' if distance[2].startswith('mile') else 'km'
                mark(distance)
            if ascent:
                person['max_ascent_m'] = float(ascent[1]) * (.3048 if ascent[2] in ('feet', 'foot', 'ft') else 1)
                person['ascent_unlimited'] = False
                patch['elevation_unit'] = 'ft' if ascent[2] in ('feet', 'foot', 'ft') else 'm'
                mark(ascent)
            if unlimited:
                person.update(max_distance_km=None, max_ascent_m=None, distance_unlimited=True, ascent_unlimited=True)
                mark(unlimited)
        patch['people'] = people
    drive = re.search(r'\b(?:drive|driving)\s+(?:(?:can be|up to|less than|under|at most|a maximum of)\s+)*(\d+(?:\.\d+)?|one|two|four)\s*(hours?|hrs?|minutes?|mins?)\s*(?:each way|one way)?', lower)
    if drive:
        number = {'one': 1, 'two': 2, 'four': 4}.get(drive[1])
        number = number if number is not None else float(drive[1])
        value = number * (60 if drive[2].startswith(('h',)) else 1)
        preferred = 'prefer' in lower
        patch.update(max_one_way_drive_minutes=None if preferred else value,
                     preferred_one_way_drive_minutes=value if preferred else None,
                     drive_preference_strict=preferred and ('less than' in drive[0] or 'under' in drive[0]))
        mark(drive)
    total = re.search(r'\b(?:takes?|lasts?)\s+(?:only\s+|at most\s+)?(\d+(?:\.\d+)?)\s*(hours?|minutes?)\s*(?:overall|total|in total)\b', lower)
    if total:
        patch['max_total_minutes'] = float(total[1]) * (60 if total[2].startswith('hour') else 1)
        mark(total)
    clear = re.search(r'\bno\s+total\s+(?:duration|time)\s+(?:restrictions|limits|limitations)\b', lower)
    if clear:
        patch['max_total_minutes'] = None
        mark(clear)
    no_dogs = re.search(r'\bno dogs?\b', lower)
    if no_dogs:
        patch['remove_dogs'] = [p['name'] for p in saved.get('dogs', [])]
        mark(no_dogs)
    dog = re.search(r'\b(?:bring|bringing)\s+(?:a|one)\s+dog\b', lower)
    if dog and not saved.get('dogs'):
        patch['dogs'] = [{'name': 'Dog 1'}]
        mark(dog)

    # Only bypass the model when all remaining words are conversational glue.
    # Unknown clauses, individual exceptions, or negations fall back to the LLM.
    remaining = list(lower)
    for start, end in recognized:
        remaining[start:end] = ' ' * (end - start)
    words = re.findall(r'[a-z0-9]+', ''.join(remaining))
    glue = set('i we plan a an the hike hiking on at by with and can each prefer preferred to for me give that it is want everything else remains same unchanged no dogs our us of please only each way'.split())
    return patch if patch and all(word in glue for word in words) else None

def explicit_dog_update(text, saved):
    """Separate fully understood dog clauses from wording still needing the LLM.

    Never infer dog capacity simply because a dog is added. Unknown clauses are
    retained intact. Existing dogs are retained unless removal is explicit.
    """
    patch = {}
    remaining = []
    dogs = {d['name'].casefold(): dict(d) for d in saved.get('dogs', [])}
    changed = False
    for clause in re.split(r'(?<=[.!?])\s+', text.strip()):
        value = clause.strip().rstrip('.!?').strip()
        if re.fullmatch(r'(?:we have |there are )?no dogs?', value, re.I):
            patch['remove_dogs'] = [d['name'] for d in dogs.values()]
            dogs = {}
            changed = True
            continue
        add = re.fullmatch(r'(?:I|we)\s+(?:(?:want to|will|would like to)\s+)?(?:bring|add|am bringing|are bringing)\s+(?:a|one|another|an additional)\s+dog(?:\s+(?:named|called)\s+([\w-]+))?', value, re.I)
        if add:
            name = add[1]
            if not name:
                index = 1
                while f'dog {index}' in dogs:
                    index += 1
                name = f'Dog {index}'
            dogs.setdefault(name.casefold(), {'name': name})
            changed = True
            continue
        limit = re.fullmatch(r'([\w -]+?)\s+can\s+hike\s+(?:up to |at most |only )?(\d+(?:\.\d+)?)\s*(miles?|km|kilomet(?:er|re)s?)(?:\s+with\s+(\d+(?:\.\d+)?)\s*(feet|ft|m|meters?|metres?)\s*(?:of\s+)?ascent)?', value, re.I)
        share = re.fullmatch(r'([\w -]+?)\s+can\s+(?:hike|do)\s+(?:the\s+)?same\s+as\s+(?:us|the hikers)', value, re.I)
        match = limit or share
        if match:
            key = match[1].casefold()
            if key in ('he', 'she', 'the dog', 'my dog', 'our dog') and len(dogs) == 1:
                key = next(iter(dogs))
            if key in dogs:
                dog = dogs[key]
                if limit:
                    dog['max_distance_km'] = float(limit[2]) * (1.609344 if limit[3].lower().startswith('mile') else 1)
                    dog['distance_unlimited'] = False
                    if limit[4]:
                        dog['max_ascent_m'] = float(limit[4]) * (.3048 if limit[5].lower() in ('feet','ft') else 1)
                        dog['ascent_unlimited'] = False
                else:
                    hikers = saved.get('people', [])
                    for field, flag in (('max_distance_km','distance_unlimited'), ('max_ascent_m','ascent_unlimited')):
                        if hikers and all(h.get(field) is not None or h.get(flag) for h in hikers):
                            limits = [h[field] for h in hikers if h.get(field) is not None and not h.get(flag)]
                            dog[field] = min(limits) if limits else None
                            dog[flag] = not limits
                changed = True
                continue
        remaining.append(clause)
    if changed:
        patch['dogs'] = list(dogs.values())
    return patch, ' '.join(remaining)

def clarification_patch(text, pending, saved):
    """Resolve a short answer only when one precise distance question is pending."""
    if len(pending) != 1 or pending[0].get('field') != 'max_distance_km':
        return None
    target = pending[0]
    if not any(p['name'] == target['name'] for p in saved.get(target['collection'], [])):
        return None
    value = text.strip().rstrip('.!').lower()
    row = {'name': target['name']}
    if re.fullmatch(r'(?:there is |there.s |it has )?no (?:distance )?limit(?:s)?|unlimited', value):
        row.update(max_distance_km=None, distance_unlimited=True)
    else:
        match = re.fullmatch(r'(?:up to |only )?(\d+(?:\.\d+)?)\s*(miles?|km|kilomet(?:er|re)s?)', value)
        if not match:
            return None
        row.update(max_distance_km=float(match[1]) * (1.609344 if match[2].startswith('mile') else 1), distance_unlimited=False)
    return {target['collection']: [row]}
