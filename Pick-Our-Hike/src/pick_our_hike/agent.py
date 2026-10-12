"""One conversational agent; tools provide state, facts, arithmetic and approval gates."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import perf_counter
from functools import wraps
from math import isfinite
from typing import Literal
import os

from pydantic import ValidationError
from pick_our_hike.models import TripPatch, GroupRequest, Evaluation
from pick_our_hike.trip_context_loader import load_demo_snapshot
from pick_our_hike.route_facts import load_route_facts, load_route_data
from pick_our_hike.trip_evaluation import evaluate_demo_trail, build_itinerary


def issues(exc):
    if isinstance(exc, ValidationError):
        return [{'field': '.'.join(map(str, e['loc'])), 'problem': e['msg']}
                for e in exc.errors()]
    return [{'problem': str(exc)}]


def merge_patch(draft, changes):
    """Apply explicit typed operations, not interpretations of user wording."""
    patch = TripPatch.model_validate(changes).model_dump(mode='json', exclude_unset=True)
    result = deepcopy(draft)
    for collection in ('people', 'dogs'):
        removed = {name.casefold() for name in patch.pop('remove_' + collection, [])}
        updates = patch.pop(collection, None)
        if updates is not None or removed:
            rows = {row['name'].casefold(): row for row in result.get(collection, [])}
            for row in updates or []:
                key = row['name'].casefold()
                for limit, flag in [('max_distance_km', 'distance_unlimited'), ('max_ascent_m', 'ascent_unlimited')]:
                    if row.get(limit) is not None:
                        row[flag] = False
                    elif row.get(flag) is True:
                        row[limit] = None
                rows[key] = {**rows.get(key, {}), **row}
            result[collection] = [row for key, row in rows.items() if key not in removed]
    result.update(patch)
    TripPatch.model_validate(result)
    return result


def difference(before, after, path=''):
    changes = []
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        location = f'{path}.{key}' if path else key
        if isinstance(a, dict) and isinstance(b, dict):
            changes.extend(difference(a, b, location))
        elif a != b:
            changes.append({'field': location, 'before': a, 'after': b})
    return changes


@dataclass
class Proposal:
    id: str
    trail_id: str
    request: GroupRequest
    evaluation: Evaluation
    reason: str
    changes: list[dict]
    revision: int
    comparison: dict = field(default_factory=dict)


@dataclass
class PlannerSession:
    draft: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    proposals: dict = field(default_factory=dict)
    accepted: Proposal | None = None
    revision: int = 0
    events: list = field(default_factory=list)
    tool_activity: list = field(default_factory=list)
    clarification: str | None = None
    pending_fields: list = field(default_factory=list)
    reply: str | None = None
    _lock: object = field(default_factory=RLock, repr=False)

    def update_trip(self, changes):
        with self._lock:
            try:
                updated = merge_patch(self.draft, changes)
            except (ValidationError, ValueError, TypeError) as exc:
                return {'ok': False, 'issues': issues(exc), 'saved_draft': self.draft}
            self.clarification = None
            if updated != self.draft:
                self.draft = updated
                self.revision += 1
                self.accepted = None
                self.proposals.clear()
            return {'ok': True, 'saved_draft': deepcopy(self.draft)}

    def readiness_issues(self):
        """Return schema evidence only. The LLM decides how to ask the user."""
        try:
            GroupRequest.model_validate(self.draft)
        except ValidationError as exc:
            return issues(exc)
        return []

    def compare_catalog(self, trail_id=None):
        """Verify matching claims; do not rank or select trails for the model."""
        reports = {key: self.evaluate(key) for key in load_route_facts()}
        matches = []
        for key, report in reports.items():
            if report['ok'] and report['evaluation']['status'] != 'fail' and all(
                check['status'] == 'pass' for check in report['evaluation']['preference_checks']):
                matches.append(key)
        original = reports.get(trail_id, {})
        evaluation = original.get('evaluation', {})
        unmet = [check['reason'] for check in evaluation.get('checks', []) + evaluation.get('preference_checks', [])
                 if check['status'] == 'fail']
        return {'evaluated_count': len(reports), 'matching_ids': matches,
                'complete': all(r['ok'] for r in reports.values()), 'unmet_requirements': unmet,
                'notice': 'Matches cover known numerical limits and preferences; unknown access remains unverified.'}

    def catalog(self):
        data = load_route_data()
        facts = data['destinations']
        snapshot = load_demo_snapshot()
        return {'meetup': snapshot['meetup'], 'data_notice': data['scope'],
                'comparison': self.compare_catalog(),
                'data_kind': data['data_kind'],
                'trails': [{'id': key, 'name': item['primary_route']['name'],
                            'distance_miles': item['primary_route']['distance_miles'],
                            'ascent_feet': item['primary_route']['ascent_feet'],
                            'route_type': item['primary_route']['type'],
                            'distance_basis': item['primary_route']['distance_basis'],
                            'start': item['primary_route']['start'],
                            'posted_hours': item['posted_hours']['label'],
                            'access_note': item.get('access_note', 'Fictional demo; no real access status.'),
                            'alert_summary': item['alerts']['summary'],
                            'notice_summaries': [notice['summary'] for notice in item['alerts']['notices']],
                            'dogs': item['dog_rule'], 'drive': snapshot['destinations'][key]['drive']}
                           for key, item in facts.items()]}

    def inspect(self, trail_id):
        data = load_route_data()
        facts = data['destinations']
        if trail_id not in facts:
            return {'ok': False, 'issues': [{'problem': 'Trail is not in the catalog'}]}
        return {'ok': True, 'facts': facts[trail_id],
                'data_kind': data['data_kind'],
                'snapshot': load_demo_snapshot()['destinations'][trail_id]}

    def evaluate(self, trail_id, changes=None):
        with self._lock:
            try:
                request = GroupRequest.model_validate(merge_patch(self.draft, changes or {}))
                if trail_id not in load_route_facts():
                    raise ValueError('Trail is not in the catalog')
                context = load_demo_snapshot()['destinations'][trail_id]
                evaluation = evaluate_demo_trail(request, trail_id, context)
                return {'ok': True, 'request': request.model_dump(mode='json'),
                        'evaluation': evaluation.model_dump(mode='json'),
                        'itinerary': build_itinerary(request, evaluation, context) if evaluation.status != 'fail' else [],
                        'assumptions': 'Unspecified pace: 20 min/km; parking: 15 min; breaks: 20 min. Hiking time includes an illustrative ascent allowance and 35% time margin.'}
            except (ValidationError, ValueError, TypeError) as exc:
                return {'ok': False, 'issues': issues(exc), 'saved_draft': deepcopy(self.draft)}

    def propose(self, trail_id, changes, reason):
        with self._lock:
            report = self.evaluate(trail_id, changes)
            if not report['ok']:
                return report
            evaluation = Evaluation.model_validate(report['evaluation'])
            if evaluation.status == 'fail':
                return {'ok': False, 'issues': [{'problem': 'Proposed trip violates these requirements; ask about a change or inspect another trail'}],
                        'evaluation': report['evaluation']}
            try:
                base = GroupRequest.model_validate(self.draft).model_dump(mode='json')
            except ValidationError:
                base = deepcopy(self.draft)
            identifier = f'{self.revision}-{len(self.proposals) + 1}'
            proposal = Proposal(identifier, trail_id, GroupRequest.model_validate(report['request']),
                                evaluation, reason, difference(base, report['request']), self.revision, self.compare_catalog(trail_id))
            self.proposals[identifier] = proposal
            return {'ok': True, 'proposal_id': identifier, 'approval_required': True,
                    'changes': proposal.changes, 'comparison': proposal.comparison, **report}

    def accept(self, identifier):
        """UI only: deliberately NOT exposed as an LLM tool."""
        with self._lock:
            proposal = self.proposals.get(identifier)
            if proposal is None or proposal.revision != self.revision:
                return {'ok': False, 'message': 'The trip changed. Please ask for an updated proposal.'}
            report = evaluate_demo_trail(proposal.request, proposal.trail_id, load_demo_snapshot()['destinations'][proposal.trail_id])
            if report.status == 'fail':
                return {'ok': False, 'message': 'This plan no longer meets the requirements. Please ask for an updated proposal.'}
            self.draft = proposal.request.model_dump(mode='json')
            self.revision += 1
            self.accepted = proposal
            self.proposals.clear()
            from langchain_core.messages import HumanMessage
            self.messages.append(HumanMessage(content='I approved the displayed changes for ' + load_route_facts()[proposal.trail_id]['primary_route']['name'] + '.', additional_kwargs={'ui_event': True}))
            return {'ok': True}


def agent_tools(session):
    from langchain.tools import tool
    import json

    def recorded(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            entry = {'tool': fn.__name__, 'arguments': json.loads(json.dumps(kwargs,
                     default=lambda value: value.model_dump(mode='json', exclude_unset=True)))}
            session.tool_activity.append(entry)
            try:
                result = fn(*args, **kwargs)
                entry['result'] = deepcopy(result)
                return result
            except Exception as exc:
                entry['error'] = f'{type(exc).__name__}: {exc}'
                raise
        return call

    @tool
    @recorded
    def set_schedule(date: str | None = None, departure: str | None = None,
                     return_by: str | None = None, clock_format: Literal['12h', '24h'] | None = None) -> dict:
        """Change only supplied schedule fields. Date YYYY-MM-DD, times HH:MM local.
        Preserve omitted fields. Read the user's language to decide what changes.
        """
        return session.update_trip({key: value for key, value in
            [('outing_date', date), ('start_time', departure), ('latest_return_time', return_by),
             ('clock_format', clock_format)] if value is not None})

    @tool
    @recorded
    def set_participants(group: Literal['hikers', 'dogs'], names: list[str]) -> dict:
        """Set the complete roster ONLY for the specified group. Other group unchanged.
        Keep existing names unless the user changes them. Empty dogs means no dogs.
        For an explicitly unnamed participant, choose Hiker 1 / Dog 1 labels.
        Preserves limits for existing names; new members have unknown limits.
        """
        key = 'people' if group == 'hikers' else 'dogs'
        wanted = {name.casefold() for name in names}
        return session.update_trip({key: [{'name': name} for name in names],
            'remove_' + key: [row['name'] for row in session.draft.get(key, []) if row['name'].casefold() not in wanted]})

    @tool
    @recorded
    def set_limit(limit: Literal['distance', 'ascent', 'pace', 'preferred_drive', 'maximum_drive', 'overall_time', 'parking', 'breaks'],
                  value: float, unit: Literal['miles', 'km', 'ft', 'm', 'hours', 'minutes', 'min/mile', 'min/km'],
                  group: Literal['hikers', 'dogs'] = 'hikers', names: list[str] | None = None,
                  strict: bool = False) -> dict:
        """Set one explicitly requested limit, copying its original number and unit.
        Distance/ascent/pace affect named existing members, or all of the chosen
        group when names is omitted. Drive/overall/parking/breaks affect the trip.
        strict=true means less than for a driving preference. No other fields change.
        """
        dimensions = {'distance': {'miles': 1.609344, 'km': 1}, 'ascent': {'ft': .3048, 'm': 1},
            'pace': {'min/mile': 1 / 1.609344, 'min/km': 1}}
        factors = dimensions.get(limit, {'hours': 60, 'minutes': 1})
        if unit not in factors or not isfinite(value) or value < 0:
            return {'ok': False, 'issues': [{'problem': 'Supply a finite nonnegative value with a compatible unit.'}]}
        amount = value * factors[unit]
        if limit in dimensions:
            key = 'people' if group == 'hikers' else 'dogs'
            existing = {row['name'].casefold(): row['name'] for row in session.draft.get(key, [])}
            targets = names if names is not None else list(existing.values())
            if not targets or any(name.casefold() not in existing for name in targets):
                return {'ok': False, 'issues': [{'problem': 'Set the participant roster first; use existing names.'}]}
            if limit == 'pace' and group == 'dogs':
                return {'ok': False, 'issues': [{'problem': 'Walking pace is stored for hikers; dogs have distance/ascent limits.'}]}
            field = {'distance': 'max_distance_km', 'ascent': 'max_ascent_m', 'pace': 'pace_minutes_per_km'}[limit]
            patch = {key: [{'name': existing[name.casefold()], field: amount} for name in targets]}
            if limit in ('distance', 'ascent'):
                patch['distance_unit' if limit == 'distance' else 'elevation_unit'] = unit
        else:
            field = {'preferred_drive': 'preferred_one_way_drive_minutes', 'maximum_drive': 'max_one_way_drive_minutes',
                     'overall_time': 'max_total_minutes', 'parking': 'parking_minutes', 'breaks': 'break_minutes'}[limit]
            patch = {field: amount}
            if limit == 'preferred_drive':
                patch['drive_preference_strict'] = strict
        return session.update_trip(patch)

    @tool
    @recorded
    def remove_limit(limit: Literal['distance', 'ascent', 'preferred_drive', 'maximum_drive', 'overall_time'],
                     group: Literal['hikers', 'dogs'] = 'hikers', names: list[str] | None = None) -> dict:
        """Remove ONLY the named cap when the user asks. Other limits remain unchanged.
        For distance/ascent use existing member names, or omit names for all of that
        group. Removing overall_time preserves the departure and return deadline.
        """
        if limit in ('distance', 'ascent'):
            key = 'people' if group == 'hikers' else 'dogs'
            existing = {row['name'].casefold(): row['name'] for row in session.draft.get(key, [])}
            targets = names if names is not None else list(existing.values())
            if not targets or any(name.casefold() not in existing for name in targets):
                return {'ok': False, 'issues': [{'problem': 'Use existing participants; no roster changes are made by this tool.'}]}
            return session.update_trip({key: [{'name': existing[name.casefold()], limit + '_unlimited': True} for name in targets]})
        field = {'preferred_drive': 'preferred_one_way_drive_minutes', 'maximum_drive': 'max_one_way_drive_minutes',
                 'overall_time': 'max_total_minutes'}[limit]
        return session.update_trip({field: None})

    @tool
    @recorded
    def start_new_trip() -> dict:
        """Clear saved trip and proposals ONLY when the user requests starting over.
        Ordinary follow-up edits do not need this tool. Conversation remains available.
        """
        session.draft = {}
        session.revision += 1
        session.proposals.clear()
        session.accepted = None
        return {'ok': True, 'saved_draft': {}}

    @tool
    @recorded
    def list_trails() -> dict:
        """Read all available trails and demo drives. Nothing is ranked or hidden by a shortlist."""
        return session.catalog()

    @tool
    @recorded
    def inspect_trail(trail_id: str) -> dict:
        """Read route metrics, detailed dog rules, scoped alerts, visitor notes and quick source links.
        Includes recorded dates and static weather. These are saved facts, not live checks.
        """
        return session.inspect(trail_id)

    @tool
    @recorded
    def evaluate_trip(trail_id: str, changes: TripPatch | None = None) -> dict:
        """Calculate fit and schedule for a trail using the saved trip and optional hypothetical changes.
        Does not change the trip. Hard requirements and soft preferences are reported separately.
        Missing fields return validation evidence; explain it naturally or ask the user.
        """
        return session.evaluate(trail_id, changes.model_dump(mode='json', exclude_unset=True) if changes else {})

    @tool
    @recorded
    def propose_plan(trail_id: str, reason: str, changes: TripPatch | None = None) -> dict:
        """Create a reviewable proposal after choosing a trail. Hypothetical changes require approval.
        All changes and known uncertainties are displayed to the user. No fixed compromise bounds.
        Cannot bypass park rules or approve the plan; the human must click Accept.
        """
        return session.propose(trail_id, changes.model_dump(mode='json', exclude_unset=True) if changes else {}, reason)

    @tool(return_direct=True)
    @recorded
    def ask_for_details(question: str) -> dict:
        """Present a concise, natural clarification written by the LLM.
        Use saved details and validation evidence; ask only what is missing or ambiguous.
        Do not expose schema fields or tool errors. Do not ask for optional names.
        """
        question = question.strip()
        if not question:
            return {'ok': False, 'issues': [{'problem': 'Supply a nonempty clarification question.'}]}
        session.clarification = question
        return {'ok': True, 'question': question}

    @tool(return_direct=True)
    @recorded
    def present_results(message: str, outcome: Literal['matches', 'alternative', 'no_matches'],
                        proposal_ids: list[str]) -> dict:
        """Deliver your own plain-language explanation, grounded in checked results.
        Reference successful proposal IDs for matches/alternatives. For no_matches,
        supply an empty list. Do not expose IDs in the message. No automatic wording.
        """
        if not message.strip():
            return {'ok': False, 'issues': [{'problem': 'A user-facing explanation is required.'}]}
        comparison = session.compare_catalog()
        selected = [session.proposals.get(key) for key in proposal_ids]
        if outcome == 'no_matches':
            valid = comparison['complete'] and not comparison['matching_ids'] and not proposal_ids
        else:
            valid = bool(selected) and all(p is not None and p.revision == session.revision for p in selected)
            if valid and outcome == 'matches':
                valid = all(not p.changes and p.trail_id in comparison['matching_ids'] for p in selected)
        if not valid:
            return {'ok': False, 'issues': [{'problem': 'The claimed outcome is not supported by checked results.'}],
                    'comparison': comparison}
        session.reply = message.strip()
        return {'ok': True, 'message': session.reply}

    @tool
    @recorded
    def convert_quantity(value: float, from_unit: str, to_unit: str) -> dict:
        """Convert a stated quantity exactly. Units: km, miles, m, ft, minutes, hours, min/km, min/mile, C, F."""
        if not isfinite(value):
            return {'ok': False, 'issues': [{'problem': 'Quantity must be finite'}]}
        units = {'km': ('distance', 1), 'miles': ('distance', 1.609344), 'm': ('length', 1), 'ft': ('length', .3048),
                 'minutes': ('duration', 1), 'hours': ('duration', 60), 'min/km': ('pace', 1), 'min/mile': ('pace', 1 / 1.609344)}
        if from_unit in ('C', 'F') and to_unit in ('C', 'F'):
            return {'value': value if from_unit == to_unit else (value * 9 / 5 + 32 if from_unit == 'C' else (value - 32) * 5 / 9), 'unit': to_unit}
        if from_unit not in units or to_unit not in units or units[from_unit][0] != units[to_unit][0]:
            return {'ok': False, 'issues': [{'problem': 'Use compatible supported units'}]}
        return {'value': value * units[from_unit][1] / units[to_unit][1], 'unit': to_unit}

    return [set_schedule, set_participants, set_limit, remove_limit, start_new_trip, list_trails, inspect_trail, evaluate_trip, propose_plan, convert_quantity, ask_for_details, present_results]


def agent_context(session):
    import json
    prompt = Path(__file__).with_name('prompts').joinpath('agent.txt').read_text(encoding='utf-8')
    return (prompt + '\nCurrent validated trip: ' + json.dumps(session.draft) +
            '\nPydantic readiness evidence (not user-facing wording): ' + json.dumps(session.readiness_issues()))


def planning_tools(session):
    """The planner cannot reinterpret or mutate trip inputs after extraction."""
    allowed = {'list_trails', 'inspect_trail', 'evaluate_trip', 'propose_plan',
               'ask_for_details', 'present_results', 'convert_quantity'}
    return [tool for tool in agent_tools(session) if tool.name in allowed]


def extract_and_apply_trip_update(session, text, extractor, base_instructions):
    """Give one schema/validation repair chance before asking the user to clarify."""
    import json
    from langchain_core.messages import SystemMessage
    from langchain_core.exceptions import OutputParserException
    from pydantic import ValidationError
    from pick_our_hike.trip_extraction import apply_extracted_patch

    feedback = None
    for attempt in range(2):
        instruction = base_instructions
        if feedback:
            instruction += ('\n\nYour previous structured update did not pass validation. Re-read only the saved trip and latest message. '
                            'Correct the structured update using this validation evidence; do not invent values or change unrelated fields. '
                            'If the latest message cannot be interpreted safely, return an empty changed_fields list.\n' + json.dumps(feedback))
        try:
            extracted = (extractor.invoke([SystemMessage(content=instruction)]) if hasattr(extractor, 'invoke')
                         else extractor(session.draft, text))
            raw_patch = extracted.model_dump(mode='python', exclude_unset=True) if hasattr(extracted, 'model_dump') else extracted
            patch = apply_extracted_patch(raw_patch, session.draft)
            if attempt and not patch:
                return patch, {'ok': False, 'issues': [{'problem': 'The requested change could not be identified safely'}],
                               'saved_draft': deepcopy(session.draft)}
            update = session.update_trip(patch)
            if not update['ok']:
                feedback = update.get('issues', [])
                if attempt == 0:
                    continue
                return patch, update
            return patch, update
        except (ValidationError, OutputParserException, ValueError, TypeError) as exc:
            if hasattr(exc, 'errors'):
                feedback = [{'field': '.'.join(map(str, item.get('loc', []))), 'problem': item.get('msg', 'Invalid value')}
                            for item in exc.errors()]
            elif isinstance(exc, OutputParserException):
                feedback = [{'problem': 'The response did not match the requested structured update. Return one valid update or no changed fields.'}]
            else:
                feedback = [{'problem': str(exc)[:500]}]
            if attempt:
                raise
    return {}, {'ok': False, 'issues': feedback, 'saved_draft': deepcopy(session.draft)}


def preserve_tool_schemas(request, schemas, captures):
    """Restore authoritative tool schemas after Ollama SDK's lossy serialization."""
    import json
    import httpx
    payload = json.loads(request.content)
    if payload.get('tools'):
        by_name = {schema['function']['name']: schema for schema in schemas}
        payload['tools'] = [by_name[item['function']['name']] for item in payload['tools']]
        content = json.dumps(payload).encode('utf-8')
        # HTTPX hooks receive an already built Request. Update both its cached body
        # and stream so diagnostics and the bytes actually sent are identical.
        request._content = content
        request.stream = httpx.ByteStream(content)
        request.headers['content-length'] = str(len(content))
    captures.append(payload)


def run_turn(session, text, invoke=None, extractor=None):
    from langchain_core.messages import HumanMessage, AIMessage
    import json
    session.messages.append(HumanMessage(content=text))
    started = perf_counter()
    activity_start = len(session.tool_activity)
    requests = []
    extraction_record = None
    previous_question = session.clarification
    pending_fields = list(getattr(session, 'pending_fields', []))
    session.clarification = None
    session.reply = None
    history_length = len(session.messages)
    tools = agent_tools(session)
    try:
        if invoke is None:
            from langchain.agents import create_agent
            from langchain_ollama import ChatOllama
            from langchain_core.utils.function_calling import convert_to_openai_tool
            from langchain_core.messages import SystemMessage
            def capture_request(request):
                payload = json.loads(request.content)
                if payload.get('tools'):
                    schemas = [convert_to_openai_tool(tool) for tool in tools]
                    preserve_tool_schemas(request, schemas, requests)
                else:
                    requests.append(payload)
            model = ChatOllama(model=os.getenv('PICK_OUR_HIKE_MODEL', 'phi4-mini'),
                              temperature=0, reasoning=os.getenv('PICK_OUR_HIKE_THINK', 'false').lower() == 'true', num_ctx=int(os.getenv('PICK_OUR_HIKE_CONTEXT', '16384')), num_predict=4096,
                              base_url=os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                              client_kwargs={'timeout': 120, 'trust_env': False},
                              sync_client_kwargs={'timeout': 90, 'event_hooks': {'request': [capture_request]}})
            from pick_our_hike.trip_extraction import ExtractedTripPatch, extraction_instructions
            from pick_our_hike.explicit_trip_updates import explicit_trip_patch, explicit_dog_update
            dog_patch, remaining = explicit_dog_update(text, session.draft)
            patch = explicit_trip_patch(text, session.draft) if extractor is None else None
            from pick_our_hike.explicit_trip_updates import clarification_patch
            answer_patch = clarification_patch(text, pending_fields, session.draft)
            if answer_patch is not None:
                patch = answer_patch
            if dog_patch:
                remainder_patch = explicit_trip_patch(remaining, session.draft)
                if not remaining.strip() or remaining.strip().lower().rstrip('.') in ('everything else remains same', 'everything else is same'):
                    remainder_patch = {}
                if remainder_patch is not None:
                    patch = {**remainder_patch, **dog_patch}
            if patch is not None:
                update = session.update_trip(patch)
            else:
                structured_extractor = extractor or model.model_copy(update={'num_predict': 900}).with_structured_output(ExtractedTripPatch, method='json_mode')
                # Stage the model update so a failed extraction cannot partially
                # change the real trip. Explicit dog facts win over model output.
                staged = PlannerSession(draft=deepcopy(session.draft))
                patch, update = extract_and_apply_trip_update(staged, remaining if dog_patch else text, structured_extractor,
                                                               extraction_instructions(session.draft, remaining if dog_patch else text)
                                                               + '\nPrevious question awaiting an answer: ' + (previous_question or 'None'))
                if update['ok']:
                    if dog_patch:
                        patch.pop('dogs', None)
                        patch.pop('remove_dogs', None)
                        patch.update(dog_patch)
                    update = session.update_trip(patch)
            extraction_record = {'patch': patch, 'ok': update['ok'], 'issues': update.get('issues', []),
                                 'explicit_dog_update': dog_patch, 'model_called': bool(requests)}
            if not update['ok']:
                raise ValueError('The extracted trip update did not pass validation')
            missing = []
            session.pending_fields = []
            for key, label in (('outing_date', 'the hike date'), ('start_time', 'your departure time'),
                               ('latest_return_time', 'your return deadline'), ('people', 'who is hiking (1–5 people)')):
                if not session.draft.get(key):
                    missing.append(label)
                    session.pending_fields.append({'field': key})
            for collection in ('people', 'dogs'):
                for member in session.draft.get(collection, []):
                    if member.get('max_distance_km') is None and not member.get('distance_unlimited'):
                        missing.append('the hiking distance limit for ' + member['name'] + ' (or say there is no limit)')
                        session.pending_fields.append({'collection': collection, 'name': member['name'], 'field': 'max_distance_km'})
            if missing:
                session.clarification = 'Could you tell me ' + '; '.join(missing) + '? I kept the other trip details.'
                session.messages.append(AIMessage(content=session.clarification))
                session.events.append({'ok': True, 'outcome': 'clarification', 'extraction': extraction_record})
                return session.clarification
            if not session.readiness_issues():
                from pick_our_hike.planning_dispatch import request_catalog_check
                comparison = request_catalog_check(session)
                matches = comparison['matching_ids']
                session.proposals.clear()
                session.reply = (
                    f'I found {len(matches)} matching hike option(s). Open Results to compare them. '
                    'All trails and travel times are fictional demo data, not travel advice.'
                    if matches else
                    'No trail in our catalog meets all your current requirements. '
                    'Would you consider changing the total outing time, driving allowance, or hiking limits?')
                session.messages.append(AIMessage(content=session.reply))
                session.events.append({'seconds': round(perf_counter() - started, 2), 'ok': True,
                                       'extraction': extraction_record, 'comparison': comparison,
                                       'tool_activity': deepcopy(session.tool_activity[activity_start:])})
                return session.reply
            tools = planning_tools(session)
            schemas = [convert_to_openai_tool(tool) for tool in tools]
            agent = create_agent(model, tools=tools, system_prompt=agent_context(session))
            invoke = lambda messages, _: agent.invoke({'messages': messages},
                config={'recursion_limit': int(os.getenv('PICK_OUR_HIKE_AGENT_STEPS', '32'))})
        elif extractor is not None:
            from pick_our_hike.trip_extraction import extraction_instructions
            patch, update = extract_and_apply_trip_update(session, text, extractor,
                                                           extraction_instructions(session.draft, text))
            extraction_record = {'patch': patch, 'ok': update['ok'], 'issues': update.get('issues', [])}
            if not update['ok']:
                raise ValueError('The extracted trip update did not pass validation')
        working_messages = list(session.messages)
        for attempt in range(3):
            result = invoke(working_messages, tools)
            completed = session.clarification or session.reply
            if completed:
                break
            from langchain_core.messages import SystemMessage
            working_messages = result['messages'] + [SystemMessage(content=
                'No response has been delivered. Follow the response protocol in your instructions using the tool evidence. '
                'Saved trip: ' + json.dumps(session.draft))]
        session.messages = result['messages']
        raw_answer = str(session.messages[-1].content)
        answer = session.clarification or session.reply or (
            'The planner could not finish this request. Your saved details are unchanged by any unapproved proposal. Please try again.')
        # Model prose is diagnostic evidence, never a substitute for a checked plan.
        raw_messages = [m.model_dump(mode='json') for m in session.messages]
        for message in session.messages[history_length:]:
            if message.type == 'ai' and not getattr(message, 'tool_calls', []):
                message.content = ''
        session.messages.append(AIMessage(content=answer))
        session.events.append({'seconds': round(perf_counter() - started, 2), 'ok': bool(session.reply or session.clarification),
                               'outcome': 'response' if session.reply else ('clarification' if session.clarification else 'unconfirmed'),
                               'model_requests': requests,
                               'tool_activity': deepcopy(session.tool_activity[activity_start:]),
                               'raw_answer': raw_answer, 'messages': raw_messages,
                               'extraction': extraction_record})
        return answer
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('Trip processing failed')
        session.events.append({'seconds': round(perf_counter() - started, 2), 'ok': False,
                               'model_requests': requests,
                               'tool_activity': deepcopy(session.tool_activity[activity_start:]),
                               'extraction': extraction_record,
                               'error': f'{type(exc).__name__}: {exc}'})
        if session.clarification:
            answer = session.clarification
        elif extraction_record is None or not extraction_record.get('ok'):
            answer = 'I couldn’t safely apply that trip update. Could you clarify the detail you want changed? Your saved details are unchanged.'
        else:
            answer = 'I couldn’t finish checking a hike. Your saved details are unchanged by any unapproved proposal. Please try again.'
        session.messages.append(AIMessage(content=answer))
        return answer

