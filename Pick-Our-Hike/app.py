"""Conversational Pick Our Hike: agent-led decisions, reviewable proposals."""
import streamlit as st
from pathlib import Path
from pick_our_hike.agent import PlannerSession, run_turn
from pick_our_hike.ollama_connection import connection_status
from pick_our_hike.display_formatting import DisplayFormat
from pick_our_hike.route_facts import load_route_facts
from pick_our_hike.trip_context_loader import load_demo_snapshot
from pick_our_hike.trip_evaluation import build_itinerary

st.set_page_config(page_title='Pick Our Hike', page_icon=':mountain:', layout='wide')
assets = Path(__file__).parent / 'assets'
st.markdown('<style>' + (assets / 'pick_our_hike.css').read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)
scene = (assets / 'trail_scene.svg').read_text(encoding='utf-8')
st.markdown('''<section class="hb-hero"><div class="hb-hero-copy">
<div class="hb-eyebrow">A little planning. A great day outside.</div>
<h1>Find your next shared adventure.</h1>
<p>Meet Pick Our Hike. Tell me about your crew, your time and your kind of trail.
We’ll work out the details together.</p>
<div class="hb-pills"><span>🌲 10 trail routes</span><span>🥾 1–5 hikers</span>
<span>🐾 0–5 dogs, optional</span><span>📍 Start in Redlands</span></div>
</div>''' + scene + '</section>', unsafe_allow_html=True)
st.caption('Original trail illustration — not a photograph, map, or depiction of a specific destination.')
ready, status = connection_status()
with st.sidebar:
    st.markdown('## 🌲 Pick Our Hike')
    st.caption('Your group. Your pace. One shared trail.')
    if ready:
        st.success('Planner connected')
    else:
        st.warning(status)
    st.divider()
    st.markdown('**📍 Meeting point**\n\nRedlands City Hall\n\n35 Cajon Street, Redlands, CA')
    st.info('Fictional demo: all trails, weather, rules and travel times are invented. Not for real trip planning.')
    if st.button('Start a new trip', use_container_width=True):
        st.session_state['planner_session'] = PlannerSession()
        st.rerun()
    st.caption('Starting over clears this conversation and its saved trip.')
session = st.session_state.setdefault('planner_session', PlannerSession())
# Streamlit can keep an instance of the old class after a code reload.
if not isinstance(session, PlannerSession):
    refreshed = PlannerSession()
    refreshed.__dict__.update(session.__dict__)
    session = st.session_state['planner_session'] = refreshed


def show_trip(values):
    fmt = DisplayFormat.from_trip(values)
    schedule = []
    if values.get('outing_date'):
        schedule.append(str(values['outing_date']))
    if values.get('start_time'):
        schedule.append('Leave ' + fmt.clock(values['start_time']))
    if values.get('latest_return_time'):
        schedule.append('Back by ' + fmt.clock(values['latest_return_time']))
    if schedule:
        st.write(' | '.join(schedule))
    for collection, label in [('people', 'Hiker'), ('dogs', 'Dog')]:
        for member in values.get(collection, []):
            parts = []
            if member.get('distance_unlimited'):
                parts.append('No distance cap')
            if member.get('ascent_unlimited'):
                parts.append('No ascent cap')
            if member.get('max_distance_km') is not None:
                parts.append('up to ' + fmt.distance(member['max_distance_km']))
            if member.get('max_ascent_m') is not None:
                parts.append(fmt.elevation(member['max_ascent_m']) + ' uphill')
            if member.get('pace_minutes_per_km') is not None:
                parts.append(fmt.pace(member['pace_minutes_per_km']))
            st.write(f"**{label} {member['name']}** - " + '; '.join(parts))
    if values.get('max_total_minutes') is not None:
        st.write('Maximum total outing: ' + fmt.duration(values['max_total_minutes']))
    if values.get('max_one_way_drive_minutes') is not None:
        st.write(f"Maximum drive each way: {fmt.duration(values['max_one_way_drive_minutes'])}")
    if values.get('preferred_one_way_drive_minutes') is not None:
        comparison = 'under' if values.get('drive_preference_strict') else 'up to'
        st.write(f"Preferred drive each way: {comparison} {fmt.duration(values['preferred_one_way_drive_minutes'])}")
    for key, label in [('parking_minutes', 'Parking and preparation'), ('break_minutes', 'Breaks')]:
        if values.get(key) is not None:
            st.write(f"{label}: {fmt.duration(values[key])}")


facts = load_route_facts()
snapshot = load_demo_snapshot()


def show_plan(proposal):
    trail_id = proposal.trail_id
    route = facts[trail_id]['primary_route']
    details = snapshot['destinations'][trail_id]
    fmt = DisplayFormat.from_trip(proposal.request.model_dump(mode='json'))
    columns = st.columns(4)
    for column, label, value in zip(columns, ['Rough drive out', 'Hike', 'Uphill', 'Rough drive back'],
            [fmt.duration(details['drive']['outbound_minutes']), fmt.distance(route['distance_miles'] * 1.609344),
             fmt.elevation(route['ascent_feet'] * .3048), fmt.duration(details['drive']['return_minutes'])]):
        column.metric(label, value)
    columns[0].caption('Approx. ' + fmt.distance(details['drive']['outbound_miles'] * 1.609344))
    st.caption('All destinations, distances and travel times are fictional demo values. Do not use them for travel.')
    with st.expander('Itinerary, trail conditions and planning assumptions'):
        slowest_pace = max(person.pace_minutes_per_km for person in proposal.request.people)
        st.info(
            f'Hiking pace used: {fmt.pace(slowest_pace)} — the slowest hiker’s pace keeps the group together. '
            f'When no pace is supplied, we assume {fmt.pace(20)} per hiker. '
            f'Hiking time = distance × pace, plus 12 minutes per {fmt.elevation(100)} of ascent, '
            'then a 35% extra time allowance. Driving, parking and breaks are added separately. '
            'This is a rough planning estimate. Tell me your usual hiking pace in the chat to change it.'
        )
        st.markdown('#### 🕒 Your day, step by step')
        for step in build_itinerary(proposal.request, proposal.evaluation, details):
            st.markdown(f"**{fmt.clock(step['time'])}** - {step['label']}")
        if proposal.request.dogs:
            st.markdown('**Dogs on this trail**')
            st.write(facts[trail_id]['dog_rule'])
            dog_details = facts[trail_id]['dog_details']
            st.write(dog_details['summary'])
            st.caption(dog_details['scope'])
            st.caption(dog_details['limits_note'])
        st.markdown('#### ☁️ Before you head out')
        st.write('Posted hours: ' + facts[trail_id]['posted_hours']['label'])
        st.write('Demo weather (' + details['weather']['forecast_for_date'] + '): ' + details['weather']['summary'])
        st.caption('Invented weather scenario, not an NWS forecast or current conditions.')
    with st.expander('Calculation details'):
        for check in proposal.evaluation.checks + proposal.evaluation.preference_checks:
            st.write(fmt.text(check.reason))
        st.caption('Hiking estimates include an illustrative ascent allowance and 35% time margin. All route, weather and travel data is fictional.')


plan_tab, results_tab, details_tab = st.tabs(['Plan', 'Results', 'Trip details'])
with plan_tab:
    st.subheader('Plan your hike')
    st.caption('Start here, answer a question, or change your plans. Earlier details are remembered.')
    visible = [m for m in session.messages if getattr(m, 'type', '') in ('human', 'ai')
               and m.content and not getattr(m, 'tool_calls', [])
               and not m.additional_kwargs.get('ui_event')
               and not str(m.content).startswith('I accepted proposal ')]
    if visible:
        latest = visible[-1]
        with st.chat_message('assistant' if latest.type == 'ai' else 'user'):
            st.markdown(str(latest.content))
        if len(visible) > 1:
            with st.expander('Earlier conversation'):
                for item in visible[:-1]:
                    with st.chat_message('user' if item.type == 'human' else 'assistant'):
                        st.markdown(str(item.content))
    else:
        st.info('Tell me who is coming and when you want to hike. I will ask if anything is missing.')
    with st.container():
        message = st.chat_input('Tell me about your hike, or change a detail...', disabled=not ready)
    if message:
        with st.spinner('Reading your message and checking the trip details...'):
            run_turn(session, message)
        st.rerun()
    with st.expander('Need a starting point? See an example and what to include'):
        st.write('Tell me your date, departure and return times, and how many hikers are coming (1-5), with their hiking distance limits and any ascent limits. Names are optional: unnamed hikers appear as Hiker 1, Hiker 2, and so on. Shared limits are fine. Up to 5 dogs are optional: if bringing dogs, include their names and hiking limits, or say they have the same limits as the group. If details are missing, I will ask a follow-up question; you do not need to start again.')
        st.caption('Example: Two of us want to hike on October 11, 2026, from 8 AM to 5 PM, up to 4 miles and 600 feet uphill. No dogs. We prefer under an hour driving each way.')
        st.caption('No exact wording is required. “Same as us” can share the stated limits with your dog; “ideally under an hour” is a driving preference. If a detail is unclear, I will ask.')
        st.caption('Default planning assumptions: about 32 min/mile walking pace, 15 minutes for parking and 20 minutes of breaks. You can supply your own values.')

with results_tab:
    st.subheader('Your hiking options')
    st.caption('View any hike to see its itinerary. Confirmation is needed only for changes to your requirements.')
    if session.accepted:
        st.subheader('Your hike: ' + facts[session.accepted.trail_id]['primary_route']['name'])
        show_plan(session.accepted)
    current_matches = session.compare_catalog() if not session.readiness_issues() else {}
    matching_ids = current_matches.get('matching_ids', [])
    if matching_ids:
        with st.expander('Explore matching hikes', expanded=not (session.proposals or session.accepted)):
            st.markdown(f'### All {len(matching_ids)} matching trails')
            st.caption('Based on your current trip details. Estimated times include driving, hiking, parking and breaks. All destinations and conditions are fictional.')
            fmt = DisplayFormat.from_trip(session.draft)
            for trail_id in matching_ids:
                route = facts[trail_id]['primary_route']
                report = session.evaluate(trail_id)
                with st.container(border=True):
                    info, action = st.columns([4, 1])
                    info.markdown('**' + route['name'] + '**')
                    info.caption(fmt.distance(route['distance_miles'] * 1.609344) + ' | ' +
                        fmt.elevation(route['ascent_feet'] * .3048) + ' uphill | ' +
                        fmt.duration(report['evaluation']['total_minutes_high']) + ' total outing')
                    if action.button('View hike', key='review_match_' + trail_id):
                        result = session.propose(trail_id, {}, 'Selected by the user from current matching trails.')
                        if result['ok']:
                            selected = session.proposals[result['proposal_id']]
                            session.proposals = {result['proposal_id']: selected}
                            st.rerun()
                        else:
                            st.warning('This hike could not be prepared. Please update your trip in Plan.')
    elif current_matches.get('complete'):
        st.warning('No matching results for your current trip details. Any proposed alternatives below require reviewing the compromises.')
    elif not session.proposals and not session.accepted:
        st.info(session.clarification or 'No plan is ready yet. Continue the conversation in Plan.')
    if session.proposals:
        st.markdown('### Hike details')

    for identifier, proposal in list(session.proposals.items()):
        with st.container(border=True):
            evidence = getattr(proposal, 'comparison', {})
            no_matches = evidence.get('complete') and not evidence.get('matching_ids')
            unmet = evidence.get('unmet_requirements', [])
            if no_matches:
                st.warning('No matching results: none of the trails in our catalog meets all your current limits and preferences. This is the alternative proposed for your review.')
            elif unmet:
                st.warning('Suggested alternative: this option does not meet every original requirement.')
            else:
                st.success('Matches your known limits and preferences. Fictional demo only; not real travel advice.')
            st.subheader(facts[proposal.trail_id]['primary_route']['name'])
            if unmet:
                st.markdown('**Requirements this alternative cannot meet**')
                for reason in unmet:
                    st.write('- ' + DisplayFormat.from_trip(session.draft).text(reason))
            if proposal.changes:
                st.warning('Accepting this alternative applies the changes shown below.')
                with st.expander('Review changes before accepting', expanded=True):
                    left, right = st.columns(2)
                    with left:
                        st.markdown('**Current details**')
                        show_trip(session.draft)
                    with right:
                        st.markdown('**Proposed details**')
                        show_trip(proposal.request.model_dump(mode='json'))
            for check in proposal.evaluation.checks:
                if check.status == 'unknown':
                    st.warning('Not verified: ' + check.reason)
            if proposal.changes:
                if st.button('Apply these changes', key='accept_' + identifier, type='primary'):
                    result = session.accept(identifier)
                    if not result['ok']:
                        st.warning(result['message'])
                    st.rerun()
            show_plan(proposal)

with details_tab:
    st.subheader('Your saved trip')
    st.caption('These details carry forward when you send another message. Proposed changes apply only after acceptance.')
    if session.draft:
        show_trip(session.draft)
    else:
        st.info('Your trip details will appear here as we plan together.')
    with st.expander('Planning defaults and data'):
        st.write('Default walking pace: about 32 minutes per mile. Parking: 15 minutes. Breaks: 20 minutes. Tell me your own values in Plan to change them.')
        st.write('The local dataset contains invented trails, weather, rules and travel times. Results demonstrate planning calculations only.')
