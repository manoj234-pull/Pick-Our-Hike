import pytest
from pick_our_hike.agent import PlannerSession


def complete():
    return dict(outing_date='2026-10-11', start_time='08:00', latest_return_time='18:00',
                people=[dict(name='Sam', max_distance_km=6, max_ascent_m=200)],
                dogs=[], preferred_one_way_drive_minutes=60, drive_preference_strict=True)


def test_incomplete_trip_returns_validation_issues():
    session = PlannerSession()
    assert session.update_trip({'people': [{'name': 'Sam', 'max_distance_km': 6}]})['ok']
    result = session.evaluate('cedar-meadow')
    assert not result['ok'] and result['issues']
    assert 'question' not in result
    assert session.draft['people'][0]['name'] == 'Sam'


def test_invalid_update_preserves_state_and_valid_followup_merges():
    session = PlannerSession()
    session.update_trip(complete())
    before = session.draft.copy()
    assert not session.update_trip({'people': [{'name': 'Sam', 'max_distance_km': -1}]})['ok']
    assert session.draft == before
    session.update_trip({'people': [{'name': 'Alex', 'max_distance_km': 4}]})
    session.update_trip({'people': [{'name': 'Sam', 'max_ascent_m': 150}]})
    assert len(session.draft['people']) == 2
    assert session.draft['people'][0]['max_distance_km'] == 6


def test_proposed_changes_require_acceptance():
    session = PlannerSession()
    session.update_trip({**complete(), 'preferred_one_way_drive_minutes': 10})
    proposal = session.propose('cedar-meadow', {'preferred_one_way_drive_minutes': 60}, 'Longer drive for a suitable hike.')
    assert proposal['ok']
    assert session.draft['preferred_one_way_drive_minutes'] == 10
    assert session.accepted is None
    accepted = session.accept(proposal['proposal_id'])
    assert accepted['ok']
    assert session.accepted.request.preferred_one_way_drive_minutes == 60


def test_cannot_propose_violating_hard_limits_or_accept_stale_plan():
    session = PlannerSession()
    session.update_trip({**complete(), 'max_one_way_drive_minutes': 10})
    assert not session.propose('cedar-meadow', {}, 'Try it')['ok']
    result = session.propose('cedar-meadow', {'max_one_way_drive_minutes': 60}, 'Would a longer drive work?')
    assert result['ok']
    session.update_trip({'break_minutes': 50})
    assert not session.accept(result['proposal_id'])['ok']


def test_catalog_exposes_all_routes_and_preferences_do_not_hide_them():
    session = PlannerSession()
    session.update_trip({**complete(), 'preferred_one_way_drive_minutes': 1})
    assert len(session.catalog()['trails']) == 10
    assert session.catalog()['data_kind'] == 'synthetic'
    assert session.inspect('cedar-meadow')['data_kind'] == 'synthetic'
    report = session.evaluate('cedar-meadow')
    assert report['ok']
    assert report['evaluation']['preference_checks'][0]['status'] == 'fail'
    assert not any(c['rule'] == 'drive_budget' for c in report['evaluation']['checks'])


def test_tools_do_not_expose_approval_and_reject_infinite_conversion():
    from pick_our_hike.agent import agent_tools
    tools = {t.name: t for t in agent_tools(PlannerSession())}
    assert 'accept' not in tools
    assert tools['convert_quantity'].invoke({'value': 4, 'from_unit': 'miles', 'to_unit': 'km'})['value'] == pytest.approx(6.437376)
    assert tools['convert_quantity'].invoke({'value': float('inf'), 'from_unit': 'miles', 'to_unit': 'km'})['ok'] is False


def test_failure_records_diagnostics_and_preserves_saved_details():
    from pick_our_hike.agent import run_turn
    session = PlannerSession()
    def failing(messages, tools):
        next(t for t in tools if t.name=='set_participants').invoke({'group':'hikers','names':['Sam']})
        raise RuntimeError('Model stopped')
    reply = run_turn(session, 'Sam wants to hike', failing)
    assert 'RuntimeError' not in reply
    assert session.draft['people'][0]['name'] == 'Sam'
    assert session.events[-1]['tool_activity'][0]['tool'] == 'set_participants'


def test_unsupported_dog_fields_cannot_poison_saved_draft():
    session = PlannerSession()
    result = session.update_trip({'dogs': [{'name': 'Scout', 'pace_minutes_per_km': 20}]})
    assert not result['ok']
    assert session.draft == {}


def test_langchain_returns_invalid_arguments_to_model_then_saves_valid_update():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from pick_our_hike.agent import agent_tools

    class ToolModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    responses = [
        AIMessage(content='', tool_calls=[{'id': 'bad', 'name': 'set_participants', 'args': {'group':'invalid','names':['Sam']}}]),
        AIMessage(content='', tool_calls=[{'id': 'good', 'name': 'set_participants', 'args': {'group':'hikers','names':['Sam']}}]),
        AIMessage(content='What day would you like to hike?')]
    session = PlannerSession()
    agent = create_agent(ToolModel(responses=responses), tools=agent_tools(session))
    result = agent.invoke({'messages': [HumanMessage(content='Sam wants a six-kilometre hike.')]})
    tool_messages = [m for m in result['messages'] if m.type == 'tool']
    assert tool_messages[0].status == 'error'
    assert session.draft['people'][0]['name'] == 'Sam'
    assert result['messages'][-1].content == 'What day would you like to hike?'


def test_ollama_request_preserves_nested_tool_schema():
    import httpx, json
    from pick_our_hike.agent import preserve_tool_schemas
    from ollama._types import ChatRequest
    # A nested schema fixture tests lossless transport independently of current tools.
    schemas = [{'type': 'function', 'function': {'name': 'nested_example',
        'description': 'Test-only nested arguments', 'parameters': {'type': 'object',
        'properties': {'changes': {'type': 'object', 'properties': {
            'people': {'anyOf': [{'type': 'array', 'items': {'type': 'object',
                'properties': {'max_distance_km': {'type': 'number'}}}}, {'type': 'null'}]}}}}}}}]
    stripped = ChatRequest(model='test', tools=schemas).model_dump(mode='json', exclude_none=True)
    request = httpx.Request('POST', 'http://localhost/api/chat', json=stripped)
    captures = []
    preserve_tool_schemas(request, schemas, captures)
    sent = json.loads(request.content)
    changes = sent['tools'][0]['function']['parameters']['properties']['changes']
    assert 'people' in changes['properties']
    assert 'max_distance_km' in changes['properties']['people']['anyOf'][0]['items']['properties']
    assert int(request.headers['content-length']) == len(request.content)
    assert captures[0] == sent


def test_unbacked_plan_is_not_returned_to_user():
    from langchain_core.messages import AIMessage
    from pick_our_hike.agent import run_turn
    s = PlannerSession()
    def invented(messages, tools):
        return {'messages': messages + [AIMessage(content='Hike Redlands City Hall Trail; 12 km, 1200 m.')]} 
    answer = run_turn(s, 'Plan a hike', invented)
    assert 'City Hall Trail' not in answer
    assert '1200' not in answer
    assert not s.proposals


def test_missing_dog_details_ask_question_and_continue_saved_trip():
    from langchain_core.messages import AIMessage
    from pick_our_hike.agent import run_turn
    session = PlannerSession()
    def first(messages, tools):
        session.update_trip(complete())
        next(t for t in tools if t.name=='set_participants').invoke({'group':'dogs','names':['Scout']})
        next(t for t in tools if t.name == 'ask_for_details').invoke({'question':'Could you tell me how far Scout can hike?'})
        return {'messages': messages + [AIMessage(content='Internal validation exception dogs max_distance_km')]}
    reply = run_turn(session, 'Bring Scout too', first)
    assert 'how far Scout can hike' in reply
    assert 'max_distance_km' not in reply and 'exception' not in reply
    def second(messages, tools):
        next(t for t in tools if t.name=='set_limit').invoke({'limit':'distance','value':6,'unit':'km','group':'dogs'})
        p = next(t for t in tools if t.name == 'propose_plan').invoke({'trail_id': 'cedar-meadow', 'reason': 'Fits'})
        next(t for t in tools if t.name=='present_results').invoke({'message':'Cedar Meadow Loop fits the demo group.', 'outcome':'matches', 'proposal_ids':[p['proposal_id']]})
        return {'messages': messages + [AIMessage(content='Fake route is 100 miles')]}
    reply = run_turn(session, 'Same six kilometres as Sam', second)
    assert 'Cedar Meadow Loop' in reply and 'Fake' not in reply
    assert session.draft['outing_date'] == '2026-10-11'
    assert session.draft['dogs'][0]['max_distance_km'] == 6


def test_unknown_trail_cannot_be_proposed():
    s = PlannerSession()
    s.update_trip(complete())
    assert not s.propose('REDLANDS_CITY_HALL', {}, 'Great hike')['ok']
    assert not s.proposals


def test_no_exact_match_claim_checks_entire_catalog():
    s = PlannerSession()
    s.update_trip({**complete(), 'preferred_one_way_drive_minutes': 1})
    result = s.propose('cedar-meadow', {'preferred_one_way_drive_minutes': 60}, 'A longer drive')
    assert result['ok']
    evidence = s.proposals[result['proposal_id']].comparison
    assert evidence['evaluated_count'] == 10
    assert evidence['matching_ids'] == []
    assert evidence['unmet_requirements']


def test_overall_four_hour_limit_preserves_schedule_and_blocks_longer_routes():
    s=PlannerSession()
    s.update_trip({**complete(), 'people':[dict(name='Sam',distance_unlimited=True,ascent_unlimited=True)],
                   'preferred_one_way_drive_minutes':240})
    from pick_our_hike.agent import agent_tools
    next(t for t in agent_tools(s) if t.name=='set_limit').invoke({'limit':'overall_time','value':4,'unit':'hours'})
    assert s.draft['max_total_minutes']==240
    assert s.draft['latest_return_time']=='18:00:00'
    assert s.compare_catalog()['matching_ids']==['cedar-meadow']
    assert not s.propose('amber-ridge',{},'Fits')['ok']
    result=s.propose('amber-ridge',{'max_total_minutes':300},'Longer alternative')
    assert result['ok']
    assert s.draft['max_total_minutes']==240
    assert s.proposals[result['proposal_id']].changes


def test_result_tool_requires_valid_proposal_and_catalog_evidence():
    from pick_our_hike.agent import agent_tools
    s=PlannerSession();s.update_trip(complete())
    tools={t.name:t for t in agent_tools(s)}
    result=tools['propose_plan'].invoke({'trail_id':'cedar-meadow','reason':'Fits'})
    message='Cedar Meadow Loop fits your checked limits. Open Results for the demo itinerary.'
    assert tools['present_results'].invoke({'message':message,'outcome':'matches','proposal_ids':[result['proposal_id']]})['ok']
    assert s.reply==message
    s.reply=None
    assert not tools['present_results'].invoke({'message':'Nothing fits','outcome':'no_matches','proposal_ids':[]})['ok']
    assert s.reply is None
    assert not tools['present_results'].invoke({'message':'Invented route fits','outcome':'matches','proposal_ids':['fake']})['ok']


def test_focused_tools_preserve_state_across_four_followups():
    from pick_our_hike.agent import agent_tools
    s=PlannerSession();t={tool.name:tool for tool in agent_tools(s)}
    assert t['set_schedule'].invoke({'date':'2026-10-11','departure':'08:00','return_by':'17:00'})['ok']
    t['set_participants'].invoke({'group':'hikers','names':['Sam','Alex']})
    t['set_participants'].invoke({'group':'dogs','names':[]})
    t['set_limit'].invoke({'limit':'distance','value':4,'unit':'miles'})
    t['set_limit'].invoke({'limit':'ascent','value':600,'unit':'ft'})
    t['set_limit'].invoke({'limit':'preferred_drive','value':1,'unit':'hours','strict':True})
    assert s.compare_catalog()['matching_ids']==['cedar-meadow', 'amber-ridge', 'willow-bank']
    t['set_limit'].invoke({'limit':'preferred_drive','value':4,'unit':'hours'})
    t['remove_limit'].invoke({'limit':'distance'})
    t['remove_limit'].invoke({'limit':'ascent'})
    assert len(s.compare_catalog()['matching_ids'])==8 and s.draft['dogs']==[]
    t['set_limit'].invoke({'limit':'overall_time','value':5,'unit':'hours'})
    assert s.compare_catalog()['matching_ids']==['cedar-meadow', 'amber-ridge', 'willow-bank', 'fern-hollow']
    t['remove_limit'].invoke({'limit':'overall_time'})
    t['set_participants'].invoke({'group':'dogs','names':['Dog 1']})
    assert s.readiness_issues()
    assert s.draft['max_total_minutes'] is None
    assert s.draft['start_time']=='08:00:00' and s.draft['latest_return_time']=='17:00:00'
    assert all(p['distance_unlimited'] and p['ascent_unlimited'] for p in s.draft['people'])
    t['start_new_trip'].invoke({})
    assert s.draft=={} and not s.proposals


def test_focused_tools_reject_unknown_people_and_incompatible_units():
    from pick_our_hike.agent import agent_tools
    s=PlannerSession();t={tool.name:tool for tool in agent_tools(s)}
    t['set_participants'].invoke({'group':'hikers','names':['Hiker 1']})
    before=s.draft.copy()
    assert not t['set_limit'].invoke({'limit':'distance','value':4,'unit':'hours'})['ok']
    assert not t['remove_limit'].invoke({'limit':'distance','names':['Invented person']})['ok']
    assert s.draft==before
