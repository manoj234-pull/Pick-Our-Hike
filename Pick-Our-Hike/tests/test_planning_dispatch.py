from types import SimpleNamespace
import pytest
from pick_our_hike.planning_dispatch import request_catalog_check

class Session:
    def __init__(self): self.tool_activity = []; self.calls = 0
    def compare_catalog(self):
        self.calls += 1
        return {'matching_ids':['verified']}

@pytest.mark.parametrize('response,expected', [
    (SimpleNamespace(content='',tool_calls=[{'name':'check_hiking_options','args':{}}]),'llm'),
    (SimpleNamespace(content='[{"type":"function","function":{"name":"check_hiking_options","arguments":{}}}]',tool_calls=[]),'llm'),
    (SimpleNamespace(content='Invented hike',tool_calls=[]),'python_fallback'),
    (SimpleNamespace(content='',tool_calls=[{'name':'check_hiking_options','args':{'dogs':[]}}]),'python_fallback'),
    (SimpleNamespace(content='',tool_calls=[{'name':'remove_limit','args':{}}]),'python_fallback'),
])
def test_dispatch_only_executes_validated_catalog_tool(response,expected):
    s=Session()
    result=request_catalog_check(s,SimpleNamespace(invoke=lambda _:response))
    assert result == {'matching_ids':['verified']}
    assert s.calls == 1
    assert s.tool_activity[-1]['requested_by'] == expected

def test_timeout_preserves_results():
    def timeout(_): raise TimeoutError()
    s=Session()
    assert request_catalog_check(s,SimpleNamespace(invoke=timeout))['matching_ids'] == ['verified']
    assert s.calls == 1
