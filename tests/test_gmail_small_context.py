"""Gmail fictício no orçamento relatado; nenhum acesso à conta pessoal."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from therion.agent import AgentDecision,AgentRuntime,CancellationToken,ToolCall,TurnBudget
from therion.agent.context import ContextBuilder,SYSTEM
from therion.agent.registry import ToolRegistry,initial_tools
from therion.agent.store import SessionStore
from therion.integrations.tools import register_personal_tools


@pytest.fixture
def gmail(tmp_path):
    client=Mock()
    client.search.return_value={'messages':[{'id':f'm{i}','threadId':f't{i}'} for i in range(1,4)]}
    client.metadata.side_effect=lambda identifier:{'id':identifier,'internalDate':'1792512000000',
        'payload':{'headers':[{'name':'Subject','value':'Assunto '+identifier},
                              {'name':'From','value':'fixture@example.test'}],
                   'body':{'data':'PRIVATE-BODY-NOT-REQUESTED'}}}
    store=SessionStore(tmp_path/'state.sqlite3')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True},_agent_proposals=None,
        _agent_store=store,_gmail_adapter_factory=lambda mode:client)
    registry=ToolRegistry();register_personal_tools(registry,host)
    registry.enable_discovery(initial_tools('Liste os assuntos dos meus três e-mails mais recentes.'))
    return registry,client


def test_three_subjects_fit_reported_budget_without_loading_bodies_or_effect_tools(gmail):
    registry,client=gmail
    assert {'gmail_search','gmail_message_headers'}<=registry.advertised
    assert not {'gmail_prepare_send','gmail_prepare_draft','prepare_task'} & registry.advertised
    decisions=iter([
        AgentDecision('tools',calls=(ToolCall('gmail_search',{'query':'in:anywhere'}),)),
        AgentDecision('tools',calls=(ToolCall('gmail_message_headers',{'message_ids':['m1','m2','m3']}),)),
        AgentDecision('final','Assuntos: m1 [gmail:m1], m2 [gmail:m2], m3 [gmail:m3].')])
    seen=[]
    class Provider:
        async def decide(self,rows,schemas,budget,*args):
            assert budget.context_tokens==5120
            assert ContextBuilder().estimate(rows,schemas)+budget.output_tokens<=5120
            assert 'PRIVATE-BODY-NOT-REQUESTED' not in str(rows)
            seen.append(budget)
            return next(decisions)
    result=asyncio.run(AgentRuntime(Provider(),registry).run(
        'Liste os assuntos dos meus três e-mails mais recentes.',session_id='fixture',
        budget=TurnBudget(context_tokens=5120,output_tokens=4352)))
    assert result.status=='completed',result.message
    assert len(seen)==3 and client.metadata.call_count==3
    assert all(source.get('account') for _,row in result.results for source in row.evidence)
    assert all(b.output_tokens<4352 for b in seen)
    client.thread.assert_not_called()
    client.send_draft.assert_not_called()


def test_unselected_message_cannot_be_read(gmail):
    registry,client=gmail
    spec,rejection=registry.prepare(ToolCall('gmail_message_headers',{'message_ids':['unselected']}))
    assert rejection is None
    result=asyncio.run(spec.handler({'message_ids':['unselected']},CancellationToken()))
    assert result.status=='blocked'
    client.metadata.assert_not_called()


def test_metadata_identity_mismatch_is_blocked(gmail):
    registry,client=gmail
    async def execute():
        spec,_=registry.prepare(ToolCall('gmail_search',{'query':'x'}))
        await spec.handler({'query':'x'},CancellationToken())
        client.metadata.side_effect=lambda _: {'id':'wrong'}
        spec,_=registry.prepare(ToolCall('gmail_message_headers',{'message_ids':['m1']}))
        return await spec.handler({'message_ids':['m1']},CancellationToken())
    assert asyncio.run(execute()).status=='blocked'


def test_output_reserve_can_drop_below_1024_without_altering_current_request():
    message='Pedido integral fictício.'
    rows=[{'role':'system','content':SYSTEM},{'role':'user','content':message}]
    size=ContextBuilder().estimate(rows,[])
    seen=[]
    class Provider:
        async def decide(self,rows,schemas,budget,*args):
            assert rows[-1]['content']==message
            seen.append(budget.output_tokens)
            return AgentDecision('final','Resposta fictícia.')
    result=asyncio.run(AgentRuntime(Provider(),ToolRegistry(control_tools=False)).run(message,
        session_id='fixture',budget=TurnBudget(context_tokens=size+400,output_tokens=2048)))
    assert result.status=='completed' and 256<=seen[0]<512


def test_email_send_request_keeps_its_existing_preparation_tools():
    assert 'gmail_prepare_send' in initial_tools('Envie o e-mail que preparei.')
