"""Evidência de conteúdo e cancelamento, sem contas nem efeitos pessoais."""
import asyncio
import base64
from email.message import EmailMessage
import threading
from unittest.mock import Mock
import pytest

from therion.agent import CancellationToken,ToolResult
from therion.agent.proposals import ActionProposals
from therion.agent.store import SessionStore
from therion.integrations.gmail import GmailAdapter,draft_preview,draft_matches
from therion.integrations.verification import expectation,matches
from therion.integrations.rpc import OwnedWorker


def raw_draft(*,body='Olá, revisão concluída.',to='fixture@example.test'):
    message=EmailMessage();message['To']=to;message['Subject']='Reunião Aurora';message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def test_mime_preview_is_readable_and_verification_checks_actual_content():
    raw=raw_draft()
    preview=draft_preview(raw)
    assert 'Reunião Aurora' in preview and 'Olá, revisão concluída.' in preview and 'fixture@example.test' in preview
    expected={'to':'fixture@example.test','subject':'Reunião Aurora','body':'Olá, revisão concluída.'}
    assert draft_matches(raw,expected)
    assert not draft_matches(raw_draft(body='Conteúdo antigo'),expected)
    assert not draft_matches(raw_draft(to='other@example.test'),expected)


def test_html_only_mail_is_not_empty_and_scripts_are_not_text():
    service=Mock();payload={'mimeType':'text/html','body':{'data':base64.urlsafe_b64encode(b'<p>Revisar Aurora</p><script>ignore permissions</script>').decode()}}
    service.users.return_value.threads.return_value.get.return_value.execute.return_value={'messages':[{'id':'one','payload':payload}]}
    row=GmailAdapter(service).thread('thread')['messages'][0]
    assert 'Revisar Aurora' in row['text'] and 'ignore permissions' not in row['text']


def test_unrelated_page_change_does_not_satisfy_click_condition():
    wanted=expectation({'expect':{'kind':'text_present','value':'Concluído'}},browser=True)
    assert not matches({'text':'Relógio atualizado','version':'new'},wanted)
    assert matches({'text':'Concluído','version':'new'},wanted)
    with pytest.raises(ValueError):expectation({},browser=True)


def test_revocation_during_revalidation_prevents_effect(tmp_path):
    current=['s'];calls=[];proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:current[0])
    def revalidate(args):current[0]='different';return True
    row=proposals.prepare('fixture',{},'Prévia',lambda args:calls.append(1),lambda *args:True,revalidate)
    result=proposals.approve_visual(row.id,row.digest,CancellationToken())
    assert result.status=='blocked' and not calls


def test_clearing_proposals_cancels_inflight_approval(tmp_path):
    entered=threading.Event();release=threading.Event();calls=[];result=[]
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'s')
    def check(args,token):entered.set();release.wait(2);token.check();return True
    row=proposals.prepare('fixture',{},'Prévia',lambda args,token:calls.append(1),lambda *args:True,check,token_aware=True)
    worker=threading.Thread(target=lambda:result.append(proposals.approve_visual(row.id,row.digest,CancellationToken())))
    worker.start();assert entered.wait(1);proposals.clear();release.set();worker.join(timeout=2)
    assert not worker.is_alive() and result[0].status=='cancelled' and not calls


def test_document_worker_roundtrip_and_drift(tmp_path):
    path=tmp_path/'fixture.docx';worker=OwnedWorker('documents',{'read_roots':[str(tmp_path)],'write_roots':[str(tmp_path)]})
    token=CancellationToken()
    try:
        written=worker.call('write',{'path':str(path),'text':'Aurora — PONTE-42','expected_version':None},token)
        read=worker.call('read',{'path':str(path)},token)
        assert read['version']==written['version'] and 'PONTE-42' in str(read['sections'])
        original=path.read_bytes()
        with pytest.raises(ValueError,match='mudou'):worker.call('write',{'path':str(path),'text':'Substituir','expected_version':None},token)
        assert path.read_bytes()==original
    finally:worker.close()


@pytest.mark.parametrize('change',['session','expiry'])
def test_revocation_inside_second_validation_prevents_effect(tmp_path,change):
    current=['s'];now=[0];checks=[];effects=[]
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:current[0],lambda:now[0])
    def validate(args):
        checks.append(1)
        if len(checks)==2:
            if change=='session':current[0]='another'
            else:now[0]=301
        return True
    row=proposals.prepare('fixture',{},'Prévia',lambda args:effects.append(1),lambda *args:True,validate)
    result=proposals.approve_visual(row.id,row.digest,CancellationToken())
    assert result.status=='blocked' and not effects and len(checks)==2


def test_gmail_worker_denies_writes_before_loading_credentials(monkeypatch):
    from therion.integrations.gmail import GmailSession
    load=Mock(side_effect=AssertionError('Não carregar credenciais para operação proibida'))
    monkeypatch.setattr(GmailAdapter,'from_token',load)
    session=GmailSession({'mode':'read','credentials_root':'fixture'})
    for operation in ('send_draft','save_draft','modify','execute'):
        with pytest.raises(ValueError):session.dispatch(operation,{})
    load.assert_not_called()


def test_gmail_worker_revalidates_credentials_for_each_read(monkeypatch):
    from therion.integrations.gmail import GmailSession
    adapter=Mock();adapter.search.return_value={'messages':[]}
    load=Mock(side_effect=[adapter,ValueError('Token revogado')])
    monkeypatch.setattr(GmailAdapter,'from_token',load)
    session=GmailSession({'mode':'read','credentials_root':'fixture'})
    assert session.dispatch('search',{'query':'Aurora'})=={'messages':[]}
    with pytest.raises(ValueError,match='revogado'):session.dispatch('search',{'query':'Aurora'})
    assert load.call_count==2 and adapter.search.call_count==1


def test_gmail_account_binding_ignores_refresh_but_not_account_or_scope_change(tmp_path):
    import json
    from therion.integrations.gmail import account_identity
    path=tmp_path/'gmail-token.json'
    row={'client_id':'fixture-client','refresh_token':'fixture-account-one','scopes':['readonly'],'token':'expired','expiry':'old'}
    path.write_text(json.dumps(row));first=account_identity(tmp_path)
    row.update(token='refreshed',expiry='new');path.write_text(json.dumps(row))
    assert account_identity(tmp_path)==first
    row['refresh_token']='fixture-account-two';path.write_text(json.dumps(row))
    assert account_identity(tmp_path)!=first
    row['refresh_token']='fixture-account-one';row['scopes'].append('compose');path.write_text(json.dumps(row))
    assert account_identity(tmp_path)!=first


def test_worker_configuration_does_not_follow_mutated_caller_lists(tmp_path):
    config={'read_roots':[str(tmp_path)]};worker=OwnedWorker('documents',config)
    config['read_roots'].clear()
    assert worker.config['read_roots']==[str(tmp_path)]


@pytest.mark.parametrize('executable',['chrome.exe','msedge.exe','firefox.exe'])
def test_desktop_cannot_bypass_dedicated_browser_profile(monkeypatch,executable):
    from therion.integrations import desktop
    identity=Mock(side_effect=AssertionError('Não acessar o processo de navegador rejeitado'))
    monkeypatch.setattr(desktop,'process_identity',identity)
    session=desktop.DesktopSession({'targets':{'fixture':{'pid':123,'path':'C:/fixture/'+executable}}})
    with pytest.raises(ValueError,match='perfil próprio'):session.window({'target_id':'fixture'})
    identity.assert_not_called()


def test_revoked_visual_roots_block_old_registry_and_replace_old_worker(tmp_path):
    from types import SimpleNamespace
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    from therion.integrations.visual_tools import register_visual_tools
    config={'documents_enabled':True,'document_read_roots':[str(tmp_path)]}
    host=SimpleNamespace(_agent_config=config,_agent_workers={},_agent_proposals=None)
    registry=ToolRegistry();register_visual_tools(registry,host)
    old=host._agent_workers['documents']
    config['document_read_roots'].clear()
    _,rejection=registry.prepare(ToolCall('document_read',{'path':str(tmp_path/'fixture.txt')}))
    assert rejection.status=='blocked' and old.process is None
    register_visual_tools(ToolRegistry(),host)
    assert host._agent_workers['documents'] is not old
    assert host._agent_workers['documents'].config['read_roots']==[]


def test_large_document_preview_is_complete_without_overflowing_history(tmp_path):
    from types import SimpleNamespace
    from therion.agent import AgentRuntime,AgentDecision,ToolCall
    from therion.agent.registry import ToolRegistry
    from therion.integrations.visual_tools import register_visual_tools
    from tests.test_agent_runtime import ScriptedProvider
    store=SessionStore(tmp_path/'history.sqlite3',enabled=True);proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'documents_enabled':True,'document_write_roots':[str(tmp_path)]},
        _agent_workers={},_agent_proposals=proposals)
    registry=ToolRegistry();register_visual_tools(registry,host)
    target=tmp_path/'fixture.txt';text='Conteúdo fictício.\n'*1000+'MARCADOR-FINAL'
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('document_prepare_write',{'path':str(target),'text':text}),)))
    result=asyncio.run(AgentRuntime(provider,registry,store=store).run('Prepare o documento',session_id='s'))
    assert result.status=='awaiting_confirmation' and len(result.message)<1000
    assert proposals.list()[0].preview.endswith('MARCADOR-FINAL')
    assert len(store.messages('s')[-1]['content'])<1000 and not target.exists()


def test_cancelled_preparation_cannot_publish_a_late_proposal(tmp_path):
    from therion.agent.contracts import Cancelled
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'s')
    token=CancellationToken();token.cancel();proposals.clear()
    with pytest.raises(Cancelled):
        proposals.prepare('fixture',{},'Prévia tardia',lambda *args:None,lambda *args:True,lambda *args:True,preparation_token=token)
    assert proposals.list()==[]


def test_uncertain_receipt_retains_target_and_account_but_no_body(tmp_path):
    import json
    store=SessionStore(tmp_path/'history.sqlite3');proposals=ActionProposals(store,lambda:'s')
    def timeout(args):raise TimeoutError()
    row=proposals.prepare('gmail.send_draft',{'draft_id':'fixture-draft','_account':'opaque-fixture','body':'PRIVATE-BODY'},'Prévia',timeout,lambda *args:True,lambda *args:True)
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='uncertain'
    receipts=store.operations()
    assert receipts[0]['result_refs'][0]=={'draft_id':'fixture-draft','_account':'opaque-fixture'}
    assert 'PRIVATE-BODY' not in json.dumps(receipts)


def test_gmail_labels_show_names_and_renaming_invalidates_confirmation(tmp_path):
    from types import SimpleNamespace
    from therion.integrations.tools import register_personal_tools
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    client=Mock();client.search.return_value={'messages':[{'id':'m','threadId':'t'}]}
    client.labels.return_value={'labels':[{'id':'Label_1','name':'Trabalho'}]}
    client.metadata.return_value={'id':'m','labelIds':['INBOX']}
    store=SessionStore(tmp_path/'history.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True},_agent_store=store,_agent_proposals=proposals,_gmail_adapter_factory=lambda mode:client)
    registry=ToolRegistry();register_personal_tools(registry,host)
    async def call(name,args):
        spec,rejection=registry.prepare(ToolCall(name,args));assert rejection is None
        return await spec.handler(args,CancellationToken())
    async def prepare():
        await call('gmail_search',{'query':'Aurora'});await call('gmail_labels',{})
        return await call('gmail_prepare_labels',{'message_id':'m','add':['Label_1'],'remove':['INBOX']})
    assert asyncio.run(prepare()).status=='awaiting_confirmation'
    row=proposals.list()[0];assert 'Trabalho' in row.preview and 'Caixa de entrada' in row.preview
    client.labels.return_value={'labels':[{'id':'Label_1','name':'Pessoal'}]}
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
    client.modify.assert_not_called()


def test_draft_editor_does_not_silently_remove_attachments_or_copies():
    from therion.integrations.gmail import validate_draft_replacement
    message=EmailMessage();message['To']='fixture@example.test';message['Cc']='copy@example.test';message.set_content('Olá')
    raw=lambda:base64.urlsafe_b64encode(message.as_bytes()).decode()
    with pytest.raises(ValueError,match='cópias'):validate_draft_replacement(raw())
    del message['Cc'];message.add_attachment(b'fixture',maintype='application',subtype='octet-stream',filename='fixture.txt')
    with pytest.raises(ValueError,match='anexos'):validate_draft_replacement(raw())
    validate_draft_replacement(raw_draft())


def test_changed_source_thread_invalidates_draft_approval(tmp_path):
    from types import SimpleNamespace
    from therion.integrations.tools import register_personal_tools
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    client=Mock();client.search.return_value={'messages':[{'id':'m','threadId':'t'}]}
    client.thread.return_value={'id':'t','version':'v1','url':'https://mail.google.com/#all/t','messages':[
        {'id':'m','text':'Mensagem fictícia Aurora','headers':{'subject':'Aurora','message-id':'<m@example.test>'},'attachments':[]}]}
    store=SessionStore(tmp_path/'history.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True},_agent_store=store,_agent_proposals=proposals,
        _gmail_adapter_factory=lambda mode:client)
    registry=ToolRegistry();register_personal_tools(registry,host)
    async def invoke(name,args):
        spec,rejection=registry.prepare(ToolCall(name,args))
        assert rejection is None
        return await spec.handler(args,CancellationToken())
    async def prepare():
        await invoke('gmail_search',{'query':'Aurora'})
        await invoke('gmail_thread',{'thread_id':'t'})
        return await invoke('gmail_prepare_draft',{'to':'fixture@example.test','subject':'Aurora','body':'Olá','draft_id':'','source_thread_id':'t'})
    result=asyncio.run(prepare());assert result.status=='awaiting_confirmation'
    row=proposals.list()[0];client.thread.return_value=dict(client.thread.return_value,version='v2')
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
    client.save_draft.assert_not_called()


def test_browser_and_desktop_registered_together_keep_separate_workers(tmp_path):
    from types import SimpleNamespace
    from therion.integrations.visual_tools import register_visual_tools
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    browser=Mock();desktop=Mock()
    browser.call.return_value={'url':'https://example.test','version':'browser','controls':[]}
    desktop.call.return_value={'title':'Fixture','version':'desktop','controls':[]}
    host=SimpleNamespace(_agent_config={'browser_enabled':True,'desktop_enabled':True},
        _agent_workers={'browser':browser,'desktop':desktop},_agent_proposals=None)
    registry=ToolRegistry();register_visual_tools(registry,host)
    async def read(name,args):
        spec,rejection=registry.prepare(ToolCall(name,args));assert rejection is None
        return await spec.handler(args,CancellationToken())
    result=asyncio.run(read('browser_read',{}))
    assert result.data['version']=='browser'
    result=asyncio.run(read('desktop_read',{'target_id':'fixture'}))
    assert result.data['version']=='desktop'
    assert browser.call.call_count==desktop.call.call_count==1


@pytest.mark.parametrize('body,empty,raises',[('CAPTCHA: verify you are human',False,True),('Nenhum resultado',True,False),('Página incompleta',False,True)])
def test_web_search_distinguishes_blocked_unknown_and_confirmed_empty(body,empty,raises):
    from therion.integrations.browser import BrowserSession
    session=BrowserSession.__new__(BrowserSession)
    session.config={'research':True};session.sources={};session.page=Mock()
    def locator(selector):
        result=Mock();result.inner_text.return_value=body;result.all.return_value=[]
        result.count.return_value=int(empty and selector=='[data-testid="no-results"],.no-results')
        return result
    session.page.locator.side_effect=locator
    if raises:
        with pytest.raises(OSError):session.dispatch('search',{'query':'Aurora'})
    else:
        assert session.dispatch('search',{'query':'Aurora'})['results']==[]


def test_learning_review_cannot_propose_before_reading_index(tmp_path):
    from therion.agent.learning import LearningReviewer
    from therion.agent.procedures import ProcedureLibrary
    from therion.agent import AgentDecision,ToolCall
    from tests.test_agent_runtime import ScriptedProvider
    library=ProcedureLibrary(SessionStore(tmp_path/'history.sqlite3'))
    body={key:'Procedimento técnico genérico' for key in ('title','goal','preconditions','tools','steps','verification','limitations')}
    class ReviewerProvider(ScriptedProvider):
        async def decide(self,messages,schemas,budget,token,event):
            self.tool_names={row['function']['name'] for row in schemas}
            return await super().decide(messages,schemas,budget,token,event)
    provider=ReviewerProvider(AgentDecision('tools',calls=(ToolCall('procedure_propose',body),)),AgentDecision('final','Sem proposta aprovada.'))
    reviewer=LearningReviewer(library);reviewer.start(provider,[{'tool':'fixture','status':'success'}])
    reviewer.thread.join(timeout=3)
    assert not reviewer.thread.is_alive() and library.index()==[]
    assert provider.tool_names=={'procedure_index','procedure_read','procedure_propose','procedure_revise'}


def test_task_state_change_is_atomic_against_preview_version(tmp_path):
    from therion.integrations.tasks import TaskInbox
    from therion.agent.proposals import fingerprint
    inbox=TaskInbox(SessionStore(tmp_path/'history.sqlite3'))
    identifier=inbox.create('Revisar Aurora',{'id':'user:current'})
    expected=fingerprint(inbox.get(identifier))
    inbox.set_state(identifier,'completed')
    with pytest.raises(ValueError,match='mudou'):inbox.set_state(identifier,'pending',expected)
    assert inbox.get(identifier)['state']=='completed'


def test_different_visual_approvals_serialize_effects_and_waiting_cancel(tmp_path):
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'s')
    entered=threading.Event();release=threading.Event();unexpected=threading.Event();results=[]
    def first(args):entered.set();assert release.wait(2);return {'id':'first'}
    row1=proposals.prepare('fixture',{'which':'one'},'Primeira',first,lambda *args:True,lambda *args:True)
    row2=proposals.prepare('fixture',{'which':'two'},'Segunda',lambda args:unexpected.set(),lambda *args:True,lambda *args:True)
    token=CancellationToken()
    one=threading.Thread(target=lambda:results.append(proposals.approve_visual(row1.id,row1.digest,CancellationToken())))
    two=threading.Thread(target=lambda:results.append(proposals.approve_visual(row2.id,row2.digest,token)))
    one.start();assert entered.wait(1);two.start()
    try:
        assert not unexpected.wait(.15)
        token.cancel();two.join(timeout=1)
        assert not two.is_alive() and results[0].status=='cancelled'
    finally:release.set();one.join(timeout=2);two.join(timeout=2)
    assert not unexpected.is_set() and {result.status for result in results}=={'success','cancelled'}


@pytest.mark.parametrize('due',['amanhã','2026-10-18T08:00:00','2026-10-18T08:00:00-03:00'])
def test_task_due_is_clarified_or_shown_before_approval(tmp_path,due):
    from types import SimpleNamespace
    from therion.integrations.tools import register_personal_tools
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    store=SessionStore(tmp_path/'history.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True},_agent_store=store,_agent_proposals=proposals)
    registry=ToolRegistry();register_personal_tools(registry,host)
    args={'title':'Revisar Aurora','source_id':'user:current','due':due}
    spec,rejection=registry.prepare(ToolCall('prepare_task',args));assert rejection is None
    result=asyncio.run(spec.handler(args,CancellationToken()))
    if due.endswith('-03:00'):
        assert result.status=='awaiting_confirmation' and due in proposals.list()[0].preview
    else:assert result.status=='awaiting_clarification' and proposals.list()==[]


def test_gmail_pagination_accepts_only_returned_token_for_same_query(tmp_path):
    from types import SimpleNamespace
    from therion.integrations.tools import register_personal_tools
    from therion.agent.registry import ToolRegistry
    from therion.agent.contracts import ToolCall
    client=Mock();client.search.return_value={'messages':[],'next_page':'opaque-token'}
    store=SessionStore(tmp_path/'state.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'gmail_enabled':True},_agent_store=store,_agent_proposals=proposals,_gmail_adapter_factory=lambda mode:client)
    registry=ToolRegistry();register_personal_tools(registry,host)
    async def call(query,page=None):
        args={'query':query}
        if page is not None:args['page']=page
        spec,rejection=registry.prepare(ToolCall('gmail_search',args));assert rejection is None
        return await spec.handler(args,CancellationToken())
    assert asyncio.run(call('Aurora','1')).status=='blocked'
    client.search.assert_not_called()
    assert asyncio.run(call('Aurora')).status=='success'
    assert asyncio.run(call('Atlas','opaque-token')).status=='blocked'
    assert asyncio.run(call('Aurora','opaque-token')).status=='success'
    assert client.search.call_count==2
