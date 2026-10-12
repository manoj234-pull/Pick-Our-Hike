from pick_our_hike.trip_extraction import apply_extracted_patch
from pick_our_hike.agent import PlannerSession, planning_tools


def test_unit_conversion_and_followup_patch_preserve_unmentioned_trip_facts():
    session = PlannerSession()
    session.update_trip({
        'outing_date': '2026-10-11', 'start_time': '08:00', 'latest_return_time': '17:00',
        'people': [{'name': 'Sam', 'max_distance_km': 6.437376, 'max_ascent_m': 182.88}],
        'dogs': [], 'preferred_one_way_drive_minutes': 60, 'drive_preference_strict': True,
    })

    patch = apply_extracted_patch({
        'changed_fields': ['people', 'preferred_one_way_drive', 'clear_fields'],
        'people': [{'name': 'Sam', 'changed_fields': ['max_distance'], 'max_distance': {'value': 5, 'unit': 'miles'}}],
        'preferred_one_way_drive': {'value': 4, 'unit': 'hours'},
        'clear_fields': ['max_total_minutes'],
    })
    result = session.update_trip(patch)

    assert result['ok']
    assert session.draft['outing_date'] == '2026-10-11'
    assert session.draft['start_time'].startswith('08:00')
    assert session.draft['people'][0]['max_distance_km'] == 8.04672
    assert session.draft['people'][0]['max_ascent_m'] == 182.88
    assert session.draft['preferred_one_way_drive_minutes'] == 240
    assert session.draft['max_total_minutes'] is None


def test_extraction_does_not_turn_omitted_people_into_default_limit_updates():
    patch = apply_extracted_patch({'changed_fields': ['people'], 'people': [{'name': 'Alex', 'changed_fields': ['max_ascent'], 'max_ascent': {'value': 200, 'unit': 'm'}}]})
    assert patch == {'people': [{'name': 'Alex', 'max_ascent_m': 200.0}], 'elevation_unit': 'm'}


def test_schema_nulls_do_not_clear_saved_facts_without_explicit_clear_instruction():
    session = PlannerSession()
    session.update_trip({'outing_date': '2026-10-11', 'max_total_minutes': 300,
                         'people': [{'name': 'Sam', 'max_distance_km': 5}]})
    patch = apply_extracted_patch({
        'changed_fields': [],
        'outing_date': None,
        'max_total': None,
        'people': [{'name': 'Sam', 'max_distance': None, 'max_ascent': None, 'pace': None,
                    'distance_unlimited': None, 'ascent_unlimited': None}],
    })
    session.update_trip(patch)
    assert session.draft['outing_date'] == '2026-10-11'
    assert session.draft['max_total_minutes'] == 300
    assert session.draft['people'][0]['max_distance_km'] == 5


def test_planning_stage_has_no_trip_mutation_tools():
    names = {tool.name for tool in planning_tools(PlannerSession())}
    assert {'list_trails', 'evaluate_trip', 'propose_plan', 'ask_for_details'} <= names
    assert not ({'set_schedule', 'set_participants', 'set_limit', 'remove_limit', 'start_new_trip'} & names)


def test_only_llm_declared_changed_fields_are_applied():
    patch = apply_extracted_patch({
        'changed_fields': ['preferred_one_way_drive'],
        'preferred_one_way_drive': {'value': 4, 'unit': 'hours'},
        'parking': {'value': 0, 'unit': 'minutes'},
        'people': [{'name': 'Sam', 'changed_fields': ['max_distance'],
                    'max_distance': {'value': 99, 'unit': 'miles'}}],
    })
    assert patch == {'preferred_one_way_drive_minutes': 240.0}


def test_python_expands_one_llm_extracted_shared_limit_to_all_saved_hikers():
    patch = apply_extracted_patch({
        'changed_fields': ['shared_hiker_distance', 'shared_hiker_ascent'],
        'shared_hiker_distance': {'value': 4, 'unit': 'miles'},
        'shared_hiker_ascent': {'value': 200, 'unit': 'm'},
    }, saved_trip={
        'people': [{'name': 'Casey'}, {'name': 'Jordan'}, {'name': 'Morgan'}, {'name': 'Taylor'}],
        'dogs': [],
    })
    assert patch['distance_unit'] == 'miles'
    assert patch['elevation_unit'] == 'm'
    assert patch['people'] == [
        {'name': 'Casey', 'max_distance_km': 4 * 1.609344, 'max_ascent_m': 200.0},
        {'name': 'Jordan', 'max_distance_km': 4 * 1.609344, 'max_ascent_m': 200.0},
        {'name': 'Morgan', 'max_distance_km': 4 * 1.609344, 'max_ascent_m': 200.0},
        {'name': 'Taylor', 'max_distance_km': 4 * 1.609344, 'max_ascent_m': 200.0},
    ]


def test_dog_can_inherit_hikers_most_restrictive_stated_limits():
    patch = apply_extracted_patch({
        'changed_fields': ['dogs'],
        'dogs': [{'name': 'Scout', 'changed_fields': ['share_hiker_limits'], 'share_hiker_limits': True}],
    }, saved_trip={
        'people': [
            {'name': 'Casey', 'max_distance_km': 6, 'max_ascent_m': 200},
            {'name': 'Jordan', 'max_distance_km': 4, 'max_ascent_m': 150},
        ], 'dogs': [],
    })
    assert patch['dogs'] == [{'name': 'Scout', 'max_distance_km': 4.0, 'max_ascent_m': 150.0,
                              'distance_unlimited': False, 'ascent_unlimited': False}]


def test_dog_does_not_get_invented_unlimited_capacity_when_hikers_are_unknown():
    patch = apply_extracted_patch({
        'changed_fields': ['dogs'],
        'dogs': [{'name': 'Scout', 'changed_fields': ['share_hiker_limits'], 'share_hiker_limits': True}],
    }, saved_trip={'people': [], 'dogs': []})
    assert patch['dogs'] == [{'name': 'Scout'}]


def test_turn_applies_extracted_followup_before_checked_planning():
    from langchain_core.messages import AIMessage
    from pick_our_hike.agent import run_turn

    session = PlannerSession()
    session.update_trip({
        'outing_date': '2026-10-11', 'start_time': '08:00', 'latest_return_time': '17:00',
        'people': [{'name': 'Sam', 'max_distance_km': 6.437376, 'max_ascent_m': 182.88}],
        'dogs': [], 'preferred_one_way_drive_minutes': 60, 'drive_preference_strict': True,
    })
    def extract(saved, latest):
        assert saved['outing_date'] == '2026-10-11'
        assert 'Everything else is same' in latest
        return {
            'changed_fields': ['people', 'max_one_way_drive', 'clear_fields'],
            'people': [{'name': 'Sam', 'changed_fields': ['distance_unlimited', 'ascent_unlimited'],
                        'distance_unlimited': True, 'ascent_unlimited': True}],
            'max_one_way_drive': {'value': 4, 'unit': 'hours'},
            'clear_fields': ['preferred_one_way_drive_minutes'],
        }
    def plan(messages, tools):
        proposal = session.propose('cedar-meadow', {}, 'Checked against current trip requirements.')
        assert proposal['ok']
        next(tool for tool in tools if tool.name == 'present_results').invoke({
            'message': 'Cedar Meadow Loop fits the updated trip details.',
            'outcome': 'matches', 'proposal_ids': [proposal['proposal_id']],
        })
        return {'messages': messages + [AIMessage(content='Done')]}

    answer = run_turn(session, 'Drive can be four hours. Everything else is same.', plan, extractor=extract)
    assert answer == 'Cedar Meadow Loop fits the updated trip details.'
    assert session.draft['max_one_way_drive_minutes'] == 240
    assert session.draft['preferred_one_way_drive_minutes'] is None
    assert session.draft['people'][0]['distance_unlimited'] is True
    assert session.draft['outing_date'] == '2026-10-11'


def test_invalid_patch_gets_one_model_repair_attempt_before_clarification():
    from langchain_core.messages import AIMessage
    from pick_our_hike.agent import run_turn

    session = PlannerSession()
    attempts = []
    def extract(saved, latest):
        attempts.append(latest)
        value = 0 if len(attempts) == 1 else 4
        return {'changed_fields': ['people'], 'people': [{
            'name': 'Hiker 1', 'changed_fields': ['max_distance'],
            'max_distance': {'value': value, 'unit': 'miles'},
        }]}
    def planner(messages, tools):
        next(tool for tool in tools if tool.name == 'ask_for_details').invoke({'question': 'What day would you like to hike?'})
        return {'messages': messages + [AIMessage(content='')]}

    answer = run_turn(session, 'I want to hike four miles.', planner, extractor=extract)
    assert answer == 'What day would you like to hike?'
    assert len(attempts) == 2
    assert session.draft['people'][0]['max_distance_km'] == 4 * 1.609344

def test_shared_limits_apply_to_new_hikers_and_can_be_removed():
    session = PlannerSession()
    patch = apply_extracted_patch({
        'changed_fields': ['people', 'shared_hiker_distance', 'shared_hiker_ascent'],
        'people': [{'name': 'A'}, {'name': 'B'}],
        'shared_hiker_distance': {'value': 4, 'unit': 'miles'},
        'shared_hiker_ascent': {'value': 600, 'unit': 'ft'},
    }, session.draft)
    assert session.update_trip(patch)['ok']
    assert all(p['max_distance_km'] == 6.437376 for p in session.draft['people'])
    patch = apply_extracted_patch({
        'changed_fields': ['all_hikers_distance_unlimited', 'all_hikers_ascent_unlimited'],
        'all_hikers_distance_unlimited': True, 'all_hikers_ascent_unlimited': True,
    }, session.draft)
    assert session.update_trip(patch)['ok']
    assert all(p['max_distance_km'] is None and p['max_ascent_m'] is None
               and p['distance_unlimited'] for p in session.draft['people'])
