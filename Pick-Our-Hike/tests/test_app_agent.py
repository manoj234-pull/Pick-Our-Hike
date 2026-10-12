from pathlib import Path
from unittest.mock import patch
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest
from pick_our_hike.agent import PlannerSession

APP = Path(__file__).resolve().parents[1] / 'app.py'


def test_chat_renders_followup_without_form_or_raw_errors():
    def reply(session, message):
        session.update_trip({'people': [{'name': 'Sam', 'max_distance_km': 6}]})
        session.messages.append(AIMessage(content='What day would you like to hike?'))
    with patch('pick_our_hike.ollama_connection.connection_status', return_value=(True, 'Test model')):
        app = AppTest.from_file(str(APP)).run()
        with patch('pick_our_hike.agent.run_turn', side_effect=reply):
            app.chat_input[0].set_value('Sam wants to hike').run()
        assert not app.exception
        assert not app.text_area and not app.selectbox
        assert any('What day would you like to hike?' in m.value for m in app.markdown)
        assert app.session_state['planner_session'].draft['people'][0]['name'] == 'Sam'


def test_view_plan_preserves_units_and_multiple_members():
    session = PlannerSession()
    session.update_trip(dict(outing_date='2026-10-11', start_time='13:00', latest_return_time='18:00',
        people=[dict(name=name, max_distance_km=6.437376, max_ascent_m=200) for name in ['casey', 'jordan', 'morgan', 'taylor']],
        dogs=[dict(name='Scout', max_distance_km=6.437376, max_ascent_m=200)],
        preferred_one_way_drive_minutes=60, drive_preference_strict=True,
        distance_unit='miles', elevation_unit='m', clock_format='12h'))
    result = session.propose('cedar-meadow', {}, 'A shared hike within the supplied limits.')
    assert result['ok']
    with patch('pick_our_hike.ollama_connection.connection_status', return_value=(True, 'Test model')):
        app = AppTest.from_file(str(APP))
        app.session_state['planner_session'] = session
        app.run()
        assert not app.exception
        assert {m.label: m.value for m in app.metric}['Hike'] == '2 miles'
        assert any('Back at Redlands City Hall' in m.value for m in app.markdown)
        output = '\n'.join(m.value for m in app.markdown)
        assert '4 miles' in output and '1 PM' in output and 'Scout' in output
        assert not any('Not verified' in w.value for w in app.warning)
        assert not any(b.label == 'Accept this plan' for b in app.button)
        metrics = {m.label: m.value for m in app.metric}
        assert metrics['Hike'] == '2 miles'
        assert metrics['Uphill'] == '54.86 m'


def test_dog_information_only_shown_for_trips_with_dogs():
    for dog_count in (0, 1, 5):
        session = PlannerSession()
        session.update_trip(dict(outing_date='2026-10-11', start_time='08:00', latest_return_time='18:00',
            people=[dict(name='Sam', max_distance_km=6)],
            dogs=[dict(name=f'Dog {i}', max_distance_km=6) for i in range(dog_count)]))
        assert session.propose('cedar-meadow', {}, 'A hiking option.')['ok']
        with patch('pick_our_hike.ollama_connection.connection_status', return_value=(True, 'Test model')):
            app = AppTest.from_file(str(APP))
            app.session_state['planner_session'] = session
            app.run()
            assert not app.exception
            output = '\n'.join(m.value for m in app.markdown)
            assert ('Dogs on this trail' in output) == bool(dog_count)
            assert ('Demo rule: dogs must be leashed.' in output) == bool(dog_count)
            assert not any(e.label == 'Agent activity and diagnostics' for e in app.expander)


def test_group_size_boundaries():
    import pytest
    from pydantic import ValidationError
    from pick_our_hike.models import GroupRequest
    base = dict(outing_date='2026-10-11', start_time='08:00', latest_return_time='18:00')
    for people_count, dog_count in ((1, 0), (5, 5)):
        GroupRequest(**base, people=[dict(name=str(i), max_distance_km=6) for i in range(people_count)],
                     dogs=[dict(name=str(i), max_distance_km=6) for i in range(dog_count)])
    for people_count, dog_count in ((0, 0), (6, 0), (1, 6)):
        with pytest.raises(ValidationError):
            GroupRequest(**base, people=[dict(name=str(i), max_distance_km=6) for i in range(people_count)],
                         dogs=[dict(name=str(i), max_distance_km=6) for i in range(dog_count)])


def test_alternative_is_labelled_and_ui_has_ordered_sections():
    session = PlannerSession()
    session.update_trip(dict(outing_date='2026-10-11', start_time='08:00', latest_return_time='18:00',
        people=[dict(name='Sam', distance_unlimited=True, ascent_unlimited=True)],
        preferred_one_way_drive_minutes=1))
    assert session.propose('cedar-meadow', {'preferred_one_way_drive_minutes':60}, 'A longer drive')['ok']
    with patch('pick_our_hike.ollama_connection.connection_status', return_value=(True, 'Test model')):
        app = AppTest.from_file(str(APP))
        app.session_state['planner_session'] = session
        app.run()
        assert not app.exception
        assert [tab.label for tab in app.tabs] == ['Plan', 'Results', 'Trip details']
        assert any('No matching results' in w.value for w in app.warning)
        output = '\n'.join(m.value for m in app.markdown)
        assert 'Requirements this alternative cannot meet' in output
        assert 'No distance cap' in output and 'No ascent cap' in output
        assert any(b.label == 'Apply these changes' for b in app.button)


def test_results_refresh_after_trip_update():
    session = PlannerSession()
    session.update_trip(dict(outing_date='2026-10-11',start_time='08:00',latest_return_time='17:00',
        people=[dict(name='Sam',max_distance_km=6.437376,max_ascent_m=182.88)],
        preferred_one_way_drive_minutes=60,drive_preference_strict=True))
    session.propose('cedar-meadow',{},'Fits')
    with patch('pick_our_hike.ollama_connection.connection_status',return_value=(True,'Test')):
        app=AppTest.from_file(str(APP))
        app.session_state['planner_session']=session
        app.run()
        assert len([b for b in app.button if b.key and b.key.startswith('review_match_')])==3
        session.update_trip({'people':[dict(name='Sam',distance_unlimited=True,ascent_unlimited=True)],
            'preferred_one_way_drive_minutes':240,'drive_preference_strict':False})
        session.propose('cedar-meadow',{},'Still fits')
        app.run()
        assert not app.exception
        assert len([b for b in app.button if b.key and b.key.startswith('review_match_')])==8
        app.button(key='review_match_pine-arch').click().run()
        assert not app.exception
        assert any(p.trail_id=='pine-arch' for p in session.proposals.values())
        assert session.accepted is None
