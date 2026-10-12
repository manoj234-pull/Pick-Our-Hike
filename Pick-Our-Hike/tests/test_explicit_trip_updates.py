import pytest
from types import SimpleNamespace

@pytest.fixture(autouse=True)
def simulated_tool_request(monkeypatch):
    from langchain_ollama import ChatOllama
    response = SimpleNamespace(content='', tool_calls=[{'name': 'check_hiking_options', 'args': {}}])
    monkeypatch.setattr(ChatOllama, 'bind_tools', lambda *a, **k: SimpleNamespace(invoke=lambda messages: response))

from pick_our_hike.agent import PlannerSession, run_turn
from pick_our_hike.explicit_trip_updates import explicit_dog_update

PROMPT = 'Plan a hike on October 11, 2026, leaving at 8 AM and returning by 5 PM. Sam and Alex can each hike up to 4 miles with 600 feet of ascent. No dogs. We prefer driving less than one hour each way'


def test_five_turn_sequence_preserves_group_and_asks_about_new_dog(monkeypatch):
    from langchain_ollama import ChatOllama
    def unexpected(*args, **kwargs):
        raise AssertionError('Explicit sequence must not need a model call')
    monkeypatch.setattr(ChatOllama, 'with_structured_output', unexpected)
    session = PlannerSession()
    run_turn(session, PROMPT)
    assert session.draft['people'][0]['max_distance_km'] == 6.437376
    assert session.draft['people'][0]['max_ascent_m'] == 182.88
    run_turn(session, 'The drive can be 4 hours each way. No ascent or hike distance limitations. Everything else is same.')
    assert len(session.compare_catalog()['matching_ids']) == 8
    run_turn(session, 'Give me a plan that takes only 5 hours overall')
    assert session.compare_catalog()['matching_ids'] == ['cedar-meadow', 'amber-ridge', 'willow-bank', 'fern-hollow']
    answer = run_turn(session, 'No total duration restrictions. I want to bring a dog. Everything else remains same.')
    assert 'distance limit for Dog 1' in answer
    assert session.draft['max_total_minutes'] is None
    run_turn(session, 'The dog can hike up to 4 miles with 600 feet of ascent.')
    assert session.draft['dogs'][0]['max_distance_km'] == 6.437376
    assert [p['name'] for p in session.draft['people']] == ['Sam', 'Alex']
    assert session.draft['latest_return_time'].startswith('17:00')


def test_dog_addition_keeps_existing_dogs_and_does_not_invent_limits():
    saved = {'dogs': [{'name': 'Scout', 'max_distance_km': 3}]}
    patch, rest = explicit_dog_update('I want to bring another dog named Luna. Prefer a shady trail.', saved)
    assert [d['name'] for d in patch['dogs']] == ['Scout', 'Luna']
    assert patch['dogs'][1] == {'name': 'Luna'}
    assert rest == 'Prefer a shady trail.'


def test_ambiguous_pronoun_and_negation_stay_for_model():
    saved = {'dogs': [{'name': 'Scout'}, {'name': 'Luna'}]}
    for text in ('He can hike 3 miles.', 'I do not want to bring a dog.'):
        patch, rest = explicit_dog_update(text, saved)
        assert not patch and rest == text

def test_python_dog_facts_override_conflicting_model_fields(monkeypatch):
    from langchain_ollama import ChatOllama
    class Extractor:
        def invoke(self, messages):
            return {'changed_fields': ['max_total', 'dogs', 'remove_dogs'],
                    'max_total': {'value': 5, 'unit': 'hours'},
                    'dogs': [{'name': 'Invented', 'changed_fields': ['distance_unlimited'], 'distance_unlimited': True}],
                    'remove_dogs': ['Scout']}
    monkeypatch.setattr(ChatOllama, 'with_structured_output', lambda *a, **k: Extractor())
    session = PlannerSession(draft={'outing_date': '2026-10-11', 'start_time': '08:00',
                                   'latest_return_time': '17:00', 'people': [{'name': 'A', 'max_distance_km': 5}],
                                   'dogs': [{'name': 'Scout', 'max_distance_km': 3}]})
    answer = run_turn(session, 'I want to bring another dog named Luna. Keep the entire adventure within five hours.')
    assert session.draft['max_total_minutes'] == 300
    assert [d['name'] for d in session.draft['dogs']] == ['Scout', 'Luna']
    assert 'distance limit for Luna' in answer

def test_short_no_limit_answer_only_updates_pending_dog(monkeypatch):
    from langchain_ollama import ChatOllama
    monkeypatch.setattr(ChatOllama, 'with_structured_output', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Unexpected model call')))
    session = PlannerSession()
    run_turn(session, PROMPT)
    run_turn(session, 'I want to bring a dog.')
    people_before = [dict(p) for p in session.draft['people']]
    answer = run_turn(session, 'There is no limit')
    assert session.draft['dogs'][0]['distance_unlimited'] is True
    assert session.draft['people'] == people_before
    assert session.draft['preferred_one_way_drive_minutes'] == 60
    assert session.messages[-1].content == answer and answer
    assert not session.pending_fields


def test_short_answer_without_single_question_is_not_guessed():
    from pick_our_hike.explicit_trip_updates import clarification_patch
    assert clarification_patch('There is no limit', [], {}) is None
    assert clarification_patch('There is no limit', [{'field':'max_distance_km'}] * 2, {}) is None
