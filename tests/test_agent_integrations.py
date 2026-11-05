"""Integrações em fixtures: prévias, arquivos e recuperação, sem contas reais."""
import asyncio
from copy import deepcopy
from pathlib import Path
import threading
import time
from unittest.mock import Mock

import pytest

from therion.agent.contracts import CancellationToken, ToolResult, ToolCall, AgentDecision
from therion.agent.proposals import ActionProposals
from therion.agent.store import SessionStore
from therion.agent.procedures import ProcedureLibrary
from therion.integrations.tasks import TaskInbox
from therion.integrations.documents import DocumentAdapter
from therion.integrations.gmail import GmailAdapter, address


def test_visual_proposal_exact_once_and_revocation(tmp_path):
    session=['one'];calls=[]
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:session[0])
    args={'to':'fixture@example.test'}
    row=proposals.prepare('send',args,'Prévia',lambda value:calls.append(value) or 'id',lambda *args:True,lambda args:True)
    args['to']='outro@example.test'
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='success'
    assert calls==[{'to':'fixture@example.test'}]
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
    row=proposals.prepare('send',args,'Prévia',lambda value:pytest.fail('Sessão antiga'),lambda *args:True,lambda args:True)
    session[0]='two'
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'


def test_preview_changed_or_expired_does_not_execute(tmp_path):
    now=[0]
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'s',lambda:now[0])
    def prepare():return proposals.prepare('write',{},'Prévia',lambda *args:pytest.fail('Não autorizado'),lambda *args:True,lambda *args:True)
    row=prepare()
    assert proposals.approve_visual(row.id,'changed',CancellationToken()).status=='blocked'
    row=prepare();now[0]=301
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'


def test_external_timeout_is_not_replayed(tmp_path):
    store=SessionStore(tmp_path/'history.sqlite3');proposals=ActionProposals(store,lambda:'s')
    calls=[]
    def timeout(args):calls.append(1);raise TimeoutError()
    row=proposals.prepare('send',{'to':'fixture@example.test'},'Prévia',timeout,lambda *args:True,lambda args:True)
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='uncertain'
    row=proposals.prepare('send',{'to':'fixture@example.test'},'Prévia',timeout,lambda *args:True,lambda args:True)
    result=proposals.approve_visual(row.id,row.digest,CancellationToken())
    assert result.status=='blocked' and 'incerta' in result.message
    assert calls==[1]


@pytest.mark.parametrize('suffix',['.txt','.md','.docx','.pdf','.xlsx'])
def test_document_roundtrip_and_drift(tmp_path,suffix):
    adapter=DocumentAdapter([tmp_path],[tmp_path]);target=tmp_path/('fixture'+suffix)
    result=adapter.write(target,'Projeto Aurora\nInformação verificável.',None)
    assert result['version']==adapter.version(target)
    read=adapter.read(target)
    assert 'Aurora' in str(read['sections'])
    with pytest.raises(ValueError,match='mudou'):adapter.write(target,'não sobrescrever',None)
    assert adapter.version(target)==result['version']


def test_document_scope_and_formula(tmp_path):
    root=tmp_path/'allowed';root.mkdir()
    outside=tmp_path/'outside.md';outside.write_text('fora',encoding='utf-8')
    adapter=DocumentAdapter([root],[root])
    with pytest.raises(ValueError):adapter.read(outside)
    from openpyxl import Workbook
    workbook=Workbook();workbook.active['A1']='=1+1';file=root/'formula.xlsx';workbook.save(file);workbook.close()
    assert 'não executadas' in str(adapter.read(file)['warnings'])
    adapter.write(root/'new.xlsx','=1+1',None)
    assert "'=1+1" in str(adapter.read(root/'new.xlsx')['sections'])


def test_pdf_scan_is_not_empty_document(tmp_path):
    from pypdf import PdfWriter
    path=tmp_path/'scan.pdf';writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    with path.open('wb') as stream:writer.write(stream)
    assert 'OCR' in str(DocumentAdapter([tmp_path]).read(path)['warnings'])


@pytest.mark.parametrize('value',['a@example.test\nBcc: b@example.test','Nome <a@example.test>','a@example.test,b@example.test','não-email'])
def test_gmail_header_injection_rejected(value):
    with pytest.raises(ValueError):address(value)


def test_gmail_read_no_mutation_and_draft_not_send():
    service=Mock();service.users.return_value.messages.return_value.list.return_value.execute.return_value={'messages':[{'id':'m1','threadId':'t1'}]}
    gmail=GmailAdapter(service)
    assert gmail.search('Aurora')['messages'][0]['id']=='m1'
    service.users.return_value.messages.return_value.modify.assert_not_called()
    gmail.save_draft({'to':'fixture@example.test','subject':'Aurora','body':'Rascunho fictício','draft_id':''})
    service.users.return_value.drafts.return_value.send.assert_not_called()


def test_task_requires_explicit_timezone(tmp_path):
    inbox=TaskInbox(SessionStore(tmp_path/'history.sqlite3'))
    with pytest.raises(ValueError,match='fuso'):inbox.create('Aurora',{'id':'gmail:1'},'2026-10-17T08:00:00')
    identifier=inbox.create('Aurora',{'id':'gmail:1'},'2026-10-17T08:00:00-03:00')
    inbox.set_state(identifier,'completed')
    assert inbox.list()[0]['state']=='completed'


def test_procedure_revision_and_activation_evidence(tmp_path):
    store=SessionStore(tmp_path/'history.sqlite3');library=ProcedureLibrary(store)
    body={key:'Procedimento genérico '+key for key in ('title','goal','preconditions','tools','steps','verification','limitations')}
    body['tools']='fixture'
    identifier=library.propose(body,{'receipt':'fixture'})
    assert library.propose(body,{'receipt':'other'})==identifier
    original=library.get(identifier)
    with pytest.raises(ValueError,match='Transição'):library.transition(identifier,'active',original['digest'])
    library.transition(identifier,'testing',original['digest'])
    with pytest.raises(ValueError,match='dois recibos'):library.transition(identifier,'active',original['digest'])
    for index in range(2):
        call=ToolCall('fixture',{'index':index});store.begin(call,'s','t','read');store.finish(call.id,'success',verified=True);library.record_test(identifier,call.id)
    assert library.transition(identifier,'active',original['digest'])=='active'
    body=dict(body,steps='Procedimento corrigido')
    with pytest.raises(ValueError,match='Leia'):library.propose(body,{},identifier,'old')
    library.propose(body,{},identifier,original['digest'])
    assert library.get(identifier)['revision']==2 and library.get(identifier)['state']=='proposed'


def test_host_opt_in_read_and_scope(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from tests.test_agent_runtime import ScriptedProvider
    from therion.context.second_brain import SecondBrainReader
    source=tmp_path/'note.md';source.write_text('Aurora: PONTE-42',encoding='utf-8')
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('search_notes',{'query':'Aurora'}),)),
        AgentDecision('tools',calls=(ToolCall('read_source',{'source_id':'note:1'}),)),AgentDecision('final','PONTE-42 [note:1]'))
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_config={'enabled':True},
        agent_state_root=tmp_path/'state',agent_provider=provider)
    host.second_brain=SecondBrainReader(str(tmp_path),allowed_roots=[str(tmp_path)])
    try:
        result=host.process_command('Leia Aurora')
        assert result.status=='success' and 'PONTE-42' in result.message
        assert not host._agent_store.messages(host.session_id)
    finally:host.close()
