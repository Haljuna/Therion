"""Protocolo real do adapter HTTP, sem depender de conta ou modelo externo."""
import asyncio
import json
import httpx
import pytest

from therion.agent import AgentRuntime, ToolSpec, ToolResult
from therion.agent.ollama import OllamaAgentProvider
from therion.agent.registry import ToolRegistry, object_schema, TEXT


@pytest.mark.parametrize('protocol',['native','json'])
def test_two_rounds_wire_format_and_connection_options(protocol):
    received=[];options=[]
    def transport(request):
        body=json.loads(request.content);received.append(body)
        if len(received)==1:
            message=({'tool_calls':[{'function':{'name':'lookup','arguments':{'query':'Aurora'}}}]} if protocol=='native'
                     else {'content':json.dumps({'kind':'tools','message':'','calls':[{'name':'lookup','arguments':{'query':'Aurora'}}]})})
        else:
            message=({'content':'Fonte: fixture'} if protocol=='native' else {'content':json.dumps({'kind':'final','message':'Fonte: fixture','calls':[]})})
        return httpx.Response(200,content=(json.dumps({'message':message,'done':True,'prompt_eval_count':100,'eval_count':10})+'\n').encode())
    def factory(**kwargs):
        options.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(transport),**kwargs)
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat','fixture',protocol=protocol,client_factory=factory)
    registry=ToolRegistry()
    registry.register(ToolSpec('lookup','Busca fictícia',object_schema(query=TEXT),lambda args,token:ToolResult('success',data='Aurora',evidence=({'id':'fixture'},)),authorize=lambda args:True))
    result=asyncio.run(AgentRuntime(provider,registry).run('Consulte Aurora',session_id='fixture'))
    assert result.status=='completed'
    assert len(options)==1 and options[0]['trust_env'] is False and options[0]['follow_redirects'] is False
    assert not provider._clients
    if protocol=='native':
        call=received[1]['messages'][-2]['tool_calls'][0]
        assert call['function']['arguments']=={'query':'Aurora'}
    else:
        schema=next(row for row in received[0]['format']['oneOf'][0]['properties']['calls']['items']['oneOf'] if row['properties']['name']['enum']==['lookup'])
        assert schema['properties']['arguments']['required']==['query']


def test_provider_rejects_nonlocal_endpoint():
    with pytest.raises(ValueError):OllamaAgentProvider('https://example.test/api/chat','fixture')


def test_background_review_waits_for_foreground_and_cancels_without_http(monkeypatch):
    import threading
    from types import SimpleNamespace
    from therion.agent.contracts import CancellationToken,Cancelled,TurnBudget
    import therion.agent.ollama as module
    gate=SimpleNamespace(state=threading.Lock(),lock=threading.Lock(),waiters=1)
    monkeypatch.setattr(module,'INFERENCE_GATE',gate)
    calls=[]
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat','fixture',client_factory=lambda **kwargs:calls.append(kwargs)).background_copy()
    assert provider.background and not provider._clients
    async def run():
        token=CancellationToken()
        task=asyncio.create_task(provider.decide([],[],TurnBudget(),token,lambda *args,**kwargs:None))
        await asyncio.sleep(.05)
        assert not calls and not gate.lock.locked()
        token.cancel()
        with pytest.raises(Cancelled):await task
    asyncio.run(run())
    assert gate.waiters==1 and not module._ASYNC_INFERENCE_SLOT.locked()


def test_inline_thinking_is_not_a_final_answer():
    from therion.agent.ollama import final_text
    assert final_text('raciocínio privado</think>Resposta final')=='Resposta final'
    with pytest.raises(ValueError):final_text('<think>sem resposta')


def test_interrupted_stream_never_executes_tool():
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'{"message":{"content":"unfinished"}}\n')),**kwargs)
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat','fixture',client_factory=factory)
    result=asyncio.run(AgentRuntime(provider,ToolRegistry()).run('oi',session_id='fixture'))
    assert result.status=='failed'


@pytest.mark.parametrize('model,think,expected', [('qwen3:4b',False,True),('hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',False,True),('qwen3:4b',True,False),('fixture',False,False),('qwen3:4b-instruct-2507-q4_K_M',False,False),('Qwen3:4B-INSTRUCT',False,False)])
def test_explicit_qwen_non_thinking_is_wire_only(model,think,expected):
    from therion.agent import TurnBudget,CancellationToken
    received=[]
    def respond(request):
        received.append(json.loads(request.content))
        return httpx.Response(200,content=b'{"message":{"content":"OK"},"done":true}\n')
    def factory(**kwargs):return httpx.AsyncClient(transport=httpx.MockTransport(respond),**kwargs)
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat',model,protocol='native',think=think,client_factory=factory)
    messages=[{'role':'system','content':'Regras.'},{'role':'user','content':'Pedido original.'}]
    async def run():
        try:return await provider.decide(messages,[],TurnBudget(),CancellationToken(),lambda *args,**kwargs:None)
        finally:await provider.aclose()
    assert asyncio.run(run()).message=='OK'
    assert ('/no_think' in received[0]['messages'][0]['content']) is expected
    assert messages==[{'role':'system','content':'Regras.'},{'role':'user','content':'Pedido original.'}]
    assert received[0]['messages'][1]==messages[-1]
    if expected:
        assert received[0]['messages'][-1]=={'role':'assistant','content':'<think>\n\n</think>\n\n'}
    else:assert received[0]['messages'][-1]==messages[-1]
