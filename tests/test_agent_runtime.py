"""Contratos de comportamento do runtime; nenhuma conta ou dado pessoal."""
import asyncio
import threading
from dataclasses import replace

import pytest

from therion.agent import AgentRuntime, AgentDecision, CancellationToken, ToolCall, ToolResult, ToolSpec, TurnBudget
from therion.agent.contracts import AgentError
from therion.agent.registry import ToolRegistry, object_schema, TEXT
from therion.agent.store import SessionStore


class ScriptedProvider:
    def __init__(self, *decisions):
        self.decisions = iter(decisions)
        self.observations = []

    async def decide(self, messages, schemas, budget, token, event):
        self.observations.append(messages)
        return next(self.decisions)


def tool(query='x'):
    return AgentDecision('tools', calls=(ToolCall('lookup', {'query': query}),))


def registry(handler, **kwargs):
    result = ToolRegistry()
    result.register(ToolSpec('lookup', 'Consulta fictícia', object_schema(query=TEXT), handler,
        authorize=kwargs.pop('authorize', lambda args: True), **kwargs))
    return result


def run(provider, tools, **kwargs):
    return asyncio.run(AgentRuntime(provider, tools, **kwargs).run('Procure informação', session_id='fixture'))


def test_replans_from_result():
    provider = ScriptedProvider(tool('primeira'), tool('alternativa'), AgentDecision('final', 'Encontrei a fonte: fixture.'))
    result = run(provider, registry(lambda args, token: ToolResult('success', data=args['query'], evidence=({'id':'fixture'},))))
    assert result.status == 'completed'
    assert len(result.results) == 2
    assert 'primeira' in provider.observations[1][-1]['content']


def test_global_call_budget_stops_inside_batch():
    calls=[]
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('lookup',{'query':'one'}),ToolCall('lookup',{'query':'two'}))))
    runtime=AgentRuntime(provider,registry(lambda args,token:calls.append(args['query']) or ToolResult('success')))
    result=asyncio.run(runtime.run('Consulta fictícia',session_id='fixture',budget=TurnBudget(calls=1)))
    assert result.status=='partial' and calls==['one'] and len(result.results)==1


def test_identical_effect_in_same_batch_is_not_repeated(tmp_path):
    calls=[]
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('lookup',{'query':'one'}),ToolCall('lookup',{'query':'one'}))))
    tools=registry(lambda args,token:calls.append(1) or ToolResult('success',side_effect_state='verified'),effect='external',verify=lambda *args:True)
    result=run(provider,tools,store=SessionStore(tmp_path/'history.sqlite3'))
    assert result.status=='partial' and calls==[1]


def test_unknown_tool_only_one_repair():
    bad = AgentDecision('tools', calls=(ToolCall('shell', {}),))
    result = run(ScriptedProvider(bad, bad), registry(lambda *args: pytest.fail('Não executar')))
    assert result.status == 'failed'
    assert not result.results


def test_provider_unavailable_is_not_a_schema_repair_or_invalid_model_decision():
    from therion.agent.contracts import ProviderUnavailable
    calls=[];events=[]
    class Offline:
        async def decide(self,*args):calls.append(1);raise ProviderUnavailable('Ollama indisponível: HTTP 503.')
    result=run(Offline(),registry(lambda *args:pytest.fail('Nenhuma ferramenta')),emit=events.append)
    assert result.status=='failed' and calls==[1]
    assert any(event.type=='provider_failed' for event in events)
    assert not any(event.type=='decision_rejected' for event in events)


def test_read_verification_failure_never_exposes_unconfirmed_content_to_model():
    provider=ScriptedProvider(tool(),AgentDecision('final','Não confirmei a fonte.'))
    result=run(provider,registry(lambda *args:ToolResult('success',data='PRIVATE-FIXTURE-CONTENT'),verify=lambda *args:False))
    assert result.status=='partial' and result.results[0][1].status=='blocked'
    assert result.results[0][1].data is None
    assert 'PRIVATE-FIXTURE-CONTENT' not in str(provider.observations)


def test_schema_rejects_unknown_fields_and_bool_as_integer():
    from therion.agent.registry import validate
    with pytest.raises(AgentError):
        validate({'query':'x', 'extra':'y'}, object_schema(query=TEXT))
    with pytest.raises(AgentError):
        validate(True, {'type':'integer'})


def test_revocation_before_effect(tmp_path):
    checks = iter([True, False])
    result = run(ScriptedProvider(tool(), AgentDecision('final', 'Bloqueado.')),
        registry(lambda *args: pytest.fail('Revogação impede efeito'), authorize=lambda args: next(checks)),
        store=SessionStore(tmp_path/'history.sqlite3'))
    assert result.status == 'partial'
    assert result.results[0][1].status == 'blocked'


def test_uncertain_write_stops_without_retry(tmp_path):
    calls = []
    result = run(ScriptedProvider(tool(), tool()), registry(lambda *args: calls.append(1) or ToolResult('success'), effect='external'),
                 store=SessionStore(tmp_path/'history.sqlite3'))
    assert result.status == 'uncertain'
    assert calls == [1]


def test_duplicate_attempt_stops():
    calls = []
    result = run(ScriptedProvider(tool(), tool()), registry(lambda *args: calls.append(1) or ToolResult('success')))
    assert result.status == 'partial'
    assert calls == [1]


def test_claim_without_receipt_does_not_announce_success():
    result=run(ScriptedProvider(AgentDecision('final','Enviei o e-mail.')),ToolRegistry())
    assert result.status=='partial'
    assert 'Enviei' not in result.message


def test_unavailable_is_not_empty():
    result = run(ScriptedProvider(tool(), AgentDecision('final', 'Não consegui consultar.')),
        registry(lambda *args: pytest.fail('Indisponível'), available=lambda: False))
    assert result.status == 'partial'
    assert result.results[0][1].status == 'unavailable'


def test_cancel_during_provider():
    token = CancellationToken()
    class Waiting:
        async def decide(self, *args):
            token.cancel()
            return AgentDecision('final', 'Resposta tardia')
    result = asyncio.run(AgentRuntime(Waiting(), ToolRegistry()).run('oi', session_id='fixture', token=token))
    assert result.status == 'cancelled'
    assert result.message != 'Resposta tardia'


def test_history_opt_in_temporary_retention_delete(tmp_path):
    now = [0.0]
    store = SessionStore(tmp_path/'history.sqlite3', clock=lambda:now[0])
    store.append('s', 'user', 'segredo')
    assert not store.messages('s')
    store.enabled = True
    store.append('s', 'user', 'Aurora procedimento')
    store.append('s', 'user', 'temporário', temporary=True)
    assert len(store.messages('s')) == 1
    assert store.search('aurora')
    now[0] = 30*86400+1
    assert not store.messages('s') and not store.search('aurora')
    store.purge()
    store.append('s', 'user', 'novo')
    store.delete('s')
    assert not store.sessions() and not store.search('novo')


def test_crash_receipt_does_not_restore_authority(tmp_path):
    store = SessionStore(tmp_path/'history.sqlite3')
    call = ToolCall('external', {'target':'fixture'})
    store.begin(call, 's', 't', 'external')
    restored = SessionStore(tmp_path/'history.sqlite3')
    assert restored.interrupted()[0]['state'] == 'uncertain'
    with pytest.raises(ValueError, match='incerta'):
        restored.begin(ToolCall('external', {'target':'fixture'}), 's', 't2', 'external')
    assert not restored.messages('s')


def test_invalid_followup_preserves_partial_state_and_verified_effect_receipt(tmp_path):
    calls=[]
    bad=AgentDecision('tools',calls=(ToolCall('shell',{}),))
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('lookup',{'query':'one'}),)),bad,bad)
    store=SessionStore(tmp_path/'state.sqlite3')
    tools=registry(lambda args,token:calls.append(args['query']) or ToolResult('success',side_effect_state='verified'),effect='external',verify=lambda *args:True)
    result=run(provider,tools,store=store)
    assert result.status=='partial' and calls==['one']
    assert len(store.operations())==1 and store.operations()[0]['verified']==1


def test_output_maximum_can_shrink_without_changing_current_task_or_context_limit():
    from therion.agent.context import ContextBuilder,SYSTEM
    from therion.agent.registry import ToolRegistry
    from therion.agent import TurnBudget
    message='Pedido fictício que deve permanecer integral. '*70
    builder=ContextBuilder();events=[];seen=[]
    size=builder.estimate([{'role':'system','content':SYSTEM},{'role':'user','content':message}],[])
    budget=TurnBudget(context_tokens=size+1224,output_tokens=2048)
    class Provider:
        async def decide(self,rows,schemas,effective,*args):
            seen.append(effective)
            assert rows[-1]['content']==message
            assert builder.estimate(rows,schemas)+effective.output_tokens<=effective.context_tokens
            return AgentDecision('final','Resposta fictícia sem efeito.')
    result=asyncio.run(AgentRuntime(Provider(),ToolRegistry(control_tools=False),emit=events.append).run(message,session_id='fixture',budget=budget))
    assert result.status=='completed' and 1024<=seen[0].output_tokens<2048
    assert seen[0].context_tokens==budget.context_tokens
    assert any(event.type=='context_budget_adjusted' for event in events)


def test_long_history_preserves_recent_joke_before_omitting_all_conversation():
    from therion.agent.context import ContextBuilder,SYSTEM
    from therion.agent.registry import ToolRegistry
    from therion.agent import TurnBudget
    builder=ContextBuilder();seen=[]
    history=[{'role':'user','content':'Me conta uma piada.'},
             {'role':'assistant','content':'PIADA SOBRE COMPUTADOR: um bug nos convites. '+('Explicação extensa. '*1200)},
             {'role':'user','content':'Faz mais uma nessa linha de SC.'},
             {'role':'assistant','content':'O que você quis dizer com SC? '+('Contexto extenso. '*1200)}]
    question='Linha de raciocínio.'
    minimal=[{'role':'system','content':SYSTEM},{'role':'user','content':question}]
    budget=TurnBudget(context_tokens=builder.estimate(minimal,[])+2200,output_tokens=1024)
    class Provider:
        async def decide(self,rows,schemas,effective,*args):
            seen.append(rows)
            assert rows[-1]['content']==question
            assert any('PIADA SOBRE COMPUTADOR' in row.get('content','') for row in rows)
            assert any('Faz mais uma nessa linha de SC' in row.get('content','') for row in rows)
            assert builder.estimate(rows,schemas)+effective.output_tokens<=effective.context_tokens
            return AgentDecision('final','Outra piada fictícia sobre computadores.')
    result=asyncio.run(AgentRuntime(Provider(),ToolRegistry(control_tools=False)).run(question,session_id='fixture',history=history,budget=budget))
    assert result.status=='completed',result.message
    assert seen and 'trecho abreviado' in str(seen)
    assert 'trecho abreviado' not in history[1]['content']


def test_history_compaction_keeps_current_tool_observation_and_user_request_integral():
    from therion.agent.context import ContextBuilder
    from therion.agent import TurnBudget
    builder=ContextBuilder()
    history=[{'role':'assistant','content':'Histórico longo. '*2000}]
    current=[{'role':'user','content':'Pedido atual integral'},
             {'role':'tool','tool_call_id':'current','content':'Observação atual integral. '*30}]
    rows=[{'role':'system','content':'Política de teste.'}]+history+current
    compact=builder.build(rows,[],TurnBudget(context_tokens=2500,output_tokens=1000),protected_from=2)
    assert compact[-2:]==current
