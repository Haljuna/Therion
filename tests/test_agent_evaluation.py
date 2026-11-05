"""O avaliador não perde resultados, não os sobrescreve e mede o contrato real."""
import asyncio
from argparse import Namespace
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from therion.agent import AgentDecision,ToolCall
from tests.test_agent_runtime import ScriptedProvider


def evaluator():
    path=Path(__file__).resolve().parents[1]/'scripts'/'evaluate-agent.py'
    spec=importlib.util.spec_from_file_location('fixture_agent_evaluator',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Reply:
    def json(self):return {'models':[{'name':'fixture','digest':'fixture-digest'}],'template':'fixture'}
    def raise_for_status(self):pass


class Client:
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def get(self,*args,**kwargs):return Reply()
    async def post(self,*args,**kwargs):return Reply()


class Provider(ScriptedProvider):
    def __init__(self,*args,**kwargs):
        self.usage={}
        super().__init__(AgentDecision('tools',calls=(ToolCall('search_memory',{'query':'Aurora'}),)),AgentDecision('final','LARANJA'))


def options(tmp_path):
    return Namespace(output=tmp_path/'matrix.jsonl',models=['fixture'],protocols=['native'],think=False,
        context=8192,output_tokens=2048,timeout=30,repeats=1,limit=1,per_group_limit=1,resume=False,
        endpoint='http://127.0.0.1:11435/api/chat',stop_file=None)


def test_evaluator_measures_events_and_safe_resume(tmp_path):
    module=evaluator();args=options(tmp_path)
    with patch('httpx.AsyncClient',Client),patch.object(module,'OllamaAgentProvider',Provider):
        asyncio.run(module.evaluate(args))
        original=args.output.read_bytes()
        row=json.loads(original)
        assert row['passed'] and row['valid_decisions']==2 and row['invalid_decisions']==0
        assert 'raw_response' not in row and 'diagnostics' not in row
        assert json.loads(args.output.with_suffix('.state.json').read_text())['status']=='completed'
        with pytest.raises(ValueError,match='já existe'):asyncio.run(module.evaluate(args))
        assert args.output.read_bytes()==original
        args.resume=True;asyncio.run(module.evaluate(args));assert args.output.read_bytes()==original
        args.timeout=31
        with pytest.raises(ValueError,match='Código ou perfil'):asyncio.run(module.evaluate(args))
        assert args.output.read_bytes()==original


def test_stop_file_prevents_next_case_and_records_interruption(tmp_path):
    module=evaluator();args=options(tmp_path)
    args.output.with_suffix('.stop').touch()
    with patch('httpx.AsyncClient',Client),patch.object(module,'OllamaAgentProvider',side_effect=AssertionError('Não inferir')):
        asyncio.run(module.evaluate(args))
    assert args.output.read_bytes()==b''
    state=json.loads(args.output.with_suffix('.state.json').read_text())
    assert state['status']=='interrupted' and state['completed']==0


def test_model_preflight_does_not_load_candidate_without_weight_headroom(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock,AsyncMock
    module=evaluator();args=options(tmp_path);args.resources=True;args.preflight_model_memory=True
    class WeightsReply(Reply):
        def json(self):return {'models':[{'name':'fixture','size':5*1024**3,'digest':'fixture-digest'}],'template':'fixture'}
    class WeightsClient(Client):
        async def get(self,*args,**kwargs):return WeightsReply()
    sample=Mock(return_value={'ram_available_bytes':8*1024**3,'commit_available_bytes':6*1024**3})
    with patch.dict('sys.modules',{'agent_resources':SimpleNamespace(sample=sample)}),patch('httpx.AsyncClient',WeightsClient),patch.object(module,'OllamaAgentProvider',side_effect=AssertionError('Não carregar')),patch.object(module.asyncio,'sleep',AsyncMock()):
        asyncio.run(module.evaluate(args))
    availability=json.loads(args.output.with_suffix('.availability.json').read_text())
    assert availability[0]['admitted'] is False and args.output.read_bytes()==b''


def test_preflight_waits_for_previous_model_commit_to_be_released(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock,AsyncMock
    module=evaluator();args=options(tmp_path);args.resources=True;args.preflight_model_memory=True
    class WeightsReply(Reply):
        def json(self):return {'models':[{'name':'fixture','size':2*1024**3,'digest':'fixture-digest'}],'template':'fixture'}
    class WeightsClient(Client):
        async def get(self,*args,**kwargs):return WeightsReply()
    low={'ram_available_bytes':8*1024**3,'commit_available_bytes':1024**3};high=dict(low,commit_available_bytes=6*1024**3)
    sample=Mock(side_effect=[low,high,high])
    with patch.dict('sys.modules',{'agent_resources':SimpleNamespace(sample=sample)}),patch('httpx.AsyncClient',WeightsClient),patch.object(module,'OllamaAgentProvider',Provider),patch.object(module.asyncio,'sleep',AsyncMock()):
        asyncio.run(module.evaluate(args))
    admission=json.loads(args.output.with_suffix('.availability.json').read_text())[0]
    assert admission['admitted'] and len(admission['probes'])==2
    assert json.loads(args.output.read_text())['passed']


@pytest.mark.parametrize('recovered',[True,False])
def test_pressure_release_never_ignores_the_memory_floor(tmp_path,recovered):
    from types import SimpleNamespace
    from unittest.mock import Mock,AsyncMock
    module=evaluator();args=options(tmp_path);args.resources=True;args.release_on_pressure=True
    low={'ram_available_bytes':8*1024**3,'commit_available_bytes':100*1024**2}
    high={'ram_available_bytes':8*1024**3,'commit_available_bytes':8*1024**3}
    sample=Mock(side_effect=[low,high]) if recovered else Mock(return_value=low)
    provider=Provider if recovered else Mock(side_effect=AssertionError('Não inferir sem margem'))
    with patch.dict('sys.modules',{'agent_resources':SimpleNamespace(sample=sample)}),patch('httpx.AsyncClient',Client),patch.object(module,'OllamaAgentProvider',provider),patch.object(module.asyncio,'sleep',AsyncMock()):
        asyncio.run(module.evaluate(args))
    state=json.loads(args.output.with_suffix('.state.json').read_text())
    assert state['status']==('completed' if recovered else 'resource_limited')
    if recovered:assert json.loads(args.output.read_text())['resource_release_before_case'] is True
    else:assert args.output.read_bytes()==b''


def test_fixture_source_change_can_be_recovered_without_false_partial():
    from therion.agent import AgentRuntime
    module=evaluator()
    case=next(case for case in module.cases() if case['id']=='replanejamento-4')
    def call(name,**arguments):return AgentDecision('tools',calls=(ToolCall(name,arguments),))
    provider=ScriptedProvider(call('search_notes',query='Íris'),call('read_source',source_id='note:1'),
        call('search_notes',query='Íris'),call('read_source',source_id='note:2'),AgentDecision('final','PONTE-42 note:2'))
    result=asyncio.run(AgentRuntime(provider,module.fixtures(case)).run(case['prompt'],session_id='fixture'))
    assert result.status=='completed' and len(result.results)==4


def test_forbidden_fixture_never_returns_public_secret_as_private_content():
    module=evaluator();tools=module.fixtures({'id':'permissoes-1','group':'permissoes'})
    spec,rejection=tools.prepare(ToolCall('search_notes',{'query':'privada:1'}))
    from therion.agent import CancellationToken
    result=asyncio.run(spec.handler({'query':'privada:1'},CancellationToken()))
    assert rejection is None and result.status=='blocked' and result.data is None
    assert 'read_source' not in [row['function']['name'] for row in tools.schemas()]
