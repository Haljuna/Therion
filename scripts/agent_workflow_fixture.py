"""Pedido composto em SDK fictício; só o controlador visual confirma efeitos."""
import asyncio
import base64
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from therion.agent import AgentRuntime,AgentDecision,ToolCall,CancellationToken
from therion.agent.proposals import ActionProposals
from therion.agent.registry import ToolRegistry
from therion.agent.store import SessionStore
from therion.integrations.gmail import GmailAdapter
from therion.integrations.tools import register_personal_tools
from therion.integrations.tasks import TaskInbox


from therion.agent.registry import initial_tools

PROMPT='Busque e leia o e-mail Aurora. Crie a tarefa "Revisar Aurora", sem prazo. Prepare resposta na mesma thread para fixture@example.test, com assunto original e corpo exatamente "Vamos revisar Aurora.". Após as confirmações visuais, salve o rascunho e envie usando o ID retornado. Informe o resultado e as fontes.'

async def run_personal_fixture(tmp_path,provider,*,budget=None):
    sdk=Mock();users=sdk.users.return_value;drafts={};sent=[]
    users.messages.return_value.list.return_value.execute.return_value={'messages':[{'id':'m1','threadId':'t1'}]}
    users.threads.return_value.get.return_value.execute.return_value={'id':'t1','historyId':'v1','messages':[
        {'id':'m1','payload':{'mimeType':'text/plain','headers':[{'name':'Subject','value':'Aurora'},
        {'name':'Message-ID','value':'<m1@example.test>'}], 'body':{'data':base64.urlsafe_b64encode(b'Revisar proposta Aurora.').decode()}}}]}
    def create():
        body=users.drafts.return_value.create.call_args.kwargs['body']
        drafts['draft1']=dict(body,id='draft1');return drafts['draft1']
    users.drafts.return_value.create.return_value.execute.side_effect=create
    users.drafts.return_value.get.return_value.execute.side_effect=lambda:drafts[users.drafts.return_value.get.call_args.kwargs['id']]
    def send():
        sent.append(users.drafts.return_value.send.call_args.kwargs['body']['id']);return {'id':'sent1'}
    users.drafts.return_value.send.return_value.execute.side_effect=send
    users.messages.return_value.get.return_value.execute.return_value={'id':'sent1','labelIds':['SENT']}
    client=GmailAdapter(sdk);store=SessionStore(tmp_path/'state.sqlite3')
    proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True,'tasks_enabled':True},_agent_store=store,
        _agent_proposals=proposals,_gmail_adapter_factory=lambda mode:client)
    from therion.agent.host import AgentSupport
    store.source_validator=lambda references:AgentSupport._history_sources_allowed(host,references)
    registry=ToolRegistry();register_personal_tools(registry,host)
    # Produção anuncia apenas capacidades pertinentes, com descoberta sob
    # demanda. Não inserir todos os schemas da conta num contexto de8k.
    registry.enable_discovery(initial_tools(PROMPT))
    approved=[];errors=[];stop=threading.Event();turn_token=CancellationToken()
    def visual_controller():
        try:
            while not stop.is_set():
                for row in proposals.list():
                    if row.id in approved:continue
                    with proposals._lock:frozen=dict(proposals._pending[row.id][1])
                    if row.operation=='gmail.save_draft':
                        assert 'Resposta na thread t1' in row.preview and not drafts and not sent
                        assert frozen['to']=='fixture@example.test' and frozen['subject']=='Aurora' and frozen['body']=='Vamos revisar Aurora.'
                        assert frozen['_reply']['thread_id']=='t1' and not frozen.get('draft_id')
                    elif row.operation=='tasks.create':
                        assert 'Revisar Aurora' in row.preview and not sent
                        assert frozen['title']=='Revisar Aurora' and not frozen.get('due')
                    elif row.operation=='gmail.send_draft':
                        assert 'fixture@example.test' in row.preview and 'Vamos revisar Aurora.' in row.preview and not sent
                        assert frozen['draft_id']=='draft1'
                    else:raise AssertionError('Efeito fora do roteiro humano da fixture.')
                    outcome=proposals.approve_visual(row.id,row.digest,CancellationToken())
                    assert outcome.status=='success',outcome
                    approved.append(row.id)
                time.sleep(.005)
        except BaseException as error:errors.append(error);turn_token.cancel()
    controller=threading.Thread(target=visual_controller);controller.start()
    try:
        events=[]
        runtime=AgentRuntime(provider,registry,store=store,confirmations=proposals,emit=events.append)
        host._agent_runtime=runtime
        result=await runtime.run(PROMPT,session_id='s',token=turn_token,budget=budget)
        return {'result':result,'approved':len(approved),'sent':list(sent),'tasks':TaskInbox(store).list(),
            'errors':[str(error) for error in errors],'receipts':store.operations(),
            'rejections':[event.payload for event in events if event.type=='decision_rejected']}
    finally:stop.set();controller.join(timeout=3)
