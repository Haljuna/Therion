import asyncio
import hashlib
import json
import threading

from therion.agent import AgentDecision,CancellationToken,ToolCall,TurnBudget
from therion.agent.context import ContextBuilder
from therion.agent.proposals import ActionProposals
from therion.agent.store import SessionStore
from therion.core.orchestrator import Orchestrator


class WaitingProvider:
    def __init__(self):self.started=threading.Event()
    async def decide(self,messages,schemas,budget,token,event):
        self.started.set()
        while True:token.check();await asyncio.sleep(.005)


def test_clear_while_runtime_waits_does_not_publish_into_new_session(tmp_path):
    provider=WaitingProvider()
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True},agent_provider=provider,agent_state_root=tmp_path/'state')
    host._agent_ui_confirmations=True;results=[]
    worker=threading.Thread(target=lambda:results.append(host.process_command('Converse comigo sobre o projeto Aurora.')))
    try:
        original=host.session_id;worker.start();assert provider.started.wait(3)
        host.clear_session();worker.join(timeout=3)
        assert not worker.is_alive() and results[0].status=='cancelled'
        assert host.session_id!=original and not host.memory.turns
    finally:host.cancel_agent();worker.join(timeout=3);host.close()


def test_second_turn_cannot_replace_request_while_first_is_active(tmp_path):
    provider=WaitingProvider()
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True},agent_provider=provider,agent_state_root=tmp_path/'state')
    host._agent_ui_confirmations=True;worker=threading.Thread(target=lambda:host.process_command('Pedido original Aurora.'))
    try:
        worker.start();assert provider.started.wait(3)
        assert host.process_command('Pedido concorrente.').status=='clarification'
        assert host._agent_original_request=='Pedido original Aurora.'
    finally:host.cancel_agent();worker.join(timeout=3);host.close()


def test_context_removes_superseded_content_but_preserves_originals():
    rows=[{'role':'system','content':'Regras estáveis.'}]
    for version,text in [('v1','SEGREDO-ANTIGO'),('v2','SEGREDO-ATUAL')]:
        rows.append({'role':'tool','tool_call_id':version,'content':json.dumps({'status':'success','data':text,
            'evidence':[{'id':version,'source':'fixture.md','version':version}]})})
    result=ContextBuilder().build(rows,[],TurnBudget())
    assert 'SEGREDO-ANTIGO' not in result[1]['content'] and 'SEGREDO-ATUAL' in result[2]['content']
    assert 'SEGREDO-ANTIGO' in rows[1]['content']


def test_source_change_invalidates_preview_without_model_provenance_argument(tmp_path):
    source=tmp_path/'source.md';source.write_bytes(b'old');effects=[]
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    proposals=ActionProposals(SessionStore(tmp_path/'state.sqlite3'),lambda:'s',
        dependencies=lambda:[{'id':'note:1','source':str(source),'version':original}],
        verify_dependencies=lambda rows,token:all(hashlib.sha256(source.read_bytes()).hexdigest()==row['version'] for row in rows))
    row=proposals.prepare('fixture.write',{},'Salvar resultado',lambda _:effects.append(1),lambda *args:True,lambda *args:True)
    assert str(source) in row.preview
    source.write_bytes(b'new')
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked' and effects==[]


def test_new_source_version_does_not_bypass_uncertain_write_guard(tmp_path):
    current=['v1'];effects=[]
    proposals=ActionProposals(SessionStore(tmp_path/'state.sqlite3'),lambda:'s',dependencies=lambda:[{'id':'fixture','source':'fixture','version':current[0]}],verify_dependencies=lambda *args:True)
    def execute(args):effects.append(1);raise TimeoutError()
    def prepare():return proposals.prepare('fixture.write',{},'Salvar resultado',execute,lambda *args:True,lambda *args:True)
    row=prepare();assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='uncertain'
    current[0]='v2';second=prepare();assert second.digest!=row.digest
    assert proposals.approve_visual(second.id,second.digest,CancellationToken()).status=='blocked' and effects==[1]


def test_confirmed_edit_replaces_old_source_version_without_false_partial(tmp_path):
    from therion.agent import AgentRuntime,ToolResult,ToolSpec
    from therion.agent.registry import ToolRegistry,object_schema
    from tests.test_agent_runtime import ScriptedProvider
    path=tmp_path/'fixture.md';path.write_bytes(b'old');old=hashlib.sha256(b'old').hexdigest();new=hashlib.sha256(b'new').hexdigest()
    store=SessionStore(tmp_path/'state.sqlite3')
    def allowed(rows):return all(source['id'].startswith('receipt:') or hashlib.sha256(path.read_bytes()).hexdigest()==source['version'] for source in rows)
    store.source_validator=allowed
    runtime=None
    proposals=ActionProposals(store,lambda:'s',dependencies=lambda:runtime.sources,verify_dependencies=lambda rows,token:allowed(rows))
    def read(args,token):return ToolResult('success',data='old',evidence=({'id':'note:1','source':str(path),'version':old},))
    def execute(args):path.write_bytes(b'new');return {'path':str(path),'version':new}
    def prepare(args,token):
        row=proposals.prepare('documents.write',{'path':str(path)},'Salvar new',execute,lambda *args:path.read_bytes()==b'new',lambda *args:True)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},side_effect_state='pending')
    registry=ToolRegistry();registry.register(ToolSpec('read','Ler',object_schema(),read,authorize=lambda args:True))
    registry.register(ToolSpec('prepare','Preparar',object_schema(),prepare,effect='prepare',authorize=lambda args:True))
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('read',{}),)),AgentDecision('tools',calls=(ToolCall('prepare',{}),)),AgentDecision('final','Salvei o resultado verificado.'))
    runtime=AgentRuntime(provider,registry,store=store,confirmations=proposals)
    async def approve():
        while not proposals.list():await asyncio.sleep(.005)
        row=proposals.list()[0];await asyncio.to_thread(proposals.approve_visual,row.id,row.digest,CancellationToken())
    async def scenario():
        approving=asyncio.create_task(approve());result=await runtime.run('Edite a fixture.',session_id='s');await approving;return result
    result=asyncio.run(scenario())
    assert result.status=='completed' and path.read_bytes()==b'new'
    assert all(source.get('version')!=old for source in runtime.sources)
