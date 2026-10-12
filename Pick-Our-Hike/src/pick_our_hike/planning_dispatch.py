"""Let the model request a read-only catalog check, with a deterministic fallback."""
import os
import json
from pathlib import Path


def request_catalog_check(session, caller=None):
    from langchain_core.tools import tool
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_ollama import ChatOllama

    @tool
    def check_hiking_options() -> dict:
        """Check all catalog hikes against the saved validated trip. Takes no arguments."""
        return session.compare_catalog()

    activity = {'tool': 'check_hiking_options', 'arguments': {}, 'requested_by': 'python_fallback'}
    try:
        if caller is None:
            model = ChatOllama(model=os.getenv('PICK_OUR_HIKE_MODEL', 'phi4-mini'),
                               base_url=os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                               temperature=0, num_ctx=2048, num_predict=100, disable_streaming=True,
                               client_kwargs={'timeout': 8, 'trust_env': False},
                               sync_client_kwargs={'timeout': 8, 'trust_env': False})
            caller = model.bind_tools([check_hiking_options])
        instruction = Path(__file__).with_name('prompts').joinpath('tool_dispatch.txt').read_text(encoding='utf-8')
        response = caller.invoke([SystemMessage(content=instruction),
                                  HumanMessage(content='The trip is validated and ready. Check the hiking options.')])
        calls = getattr(response, 'tool_calls', [])
        if not calls and isinstance(response.content, str):
            # Some local models emit the OpenAI function envelope as JSON text.
            # Accept only the entire, single-call envelope, never free-form prose.
            try:
                envelope = json.loads(response.content)
                if isinstance(envelope, list) and len(envelope) == 1:
                    item = envelope[0]
                    if set(item) == {'type', 'function'} and item['type'] == 'function':
                        function = item['function']
                        if set(function) == {'name', 'arguments'}:
                            calls = [{'name': function['name'], 'args': function['arguments']}]
                            activity['call_format'] = 'json_envelope'
            except (ValueError, TypeError, KeyError):
                pass
        if len(calls) == 1 and calls[0].get('name') == 'check_hiking_options' and calls[0].get('args') == {}:
            activity['requested_by'] = 'llm'
        else:
            activity['fallback_reason'] = 'Model did not return the supported tool call with empty arguments.'
    except Exception as exc:
        activity['fallback_reason'] = type(exc).__name__
    # Both paths execute exactly the same checked tool once. Model prose and
    # supplied trip fields cannot replace saved state or calculated results.
    result = check_hiking_options.invoke({})
    activity['result'] = result
    session.tool_activity.append(activity)
    return result
