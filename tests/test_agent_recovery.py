"""Regressões de revogação, migração, evidência e interrupção cooperativa."""
import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from unittest.mock import patch
import pytest


def test_context_usage_estimate_is_invalidated_when_model_profile_changes():
    from therion.agent.context import ContextBuilder
    builder=ContextBuilder();rows=[{'role':'user','content':'Aurora'}]
    fresh=builder.estimate(rows,[])
    builder.set_profile(('model-a','native',False));builder.record_usage(rows,[],100)
    assert builder.estimate(rows,[])<fresh
    builder.set_profile(('model-a','native',False));assert builder._anchor is not None
    builder.set_profile(('model-b','native',False));assert builder._anchor is None
    builder.record_usage(rows,[],100);builder.set_profile(('model-b','json',False));assert builder._anchor is None

from therion.agent import AgentRuntime,AgentDecision,ToolCall,ToolResult,ToolSpec,CancellationToken,TurnBudget
from therion.agent.store import SessionStore
from therion.agent.procedures import ProcedureLibrary
from therion.agent.registry import object_schema
from tests.test_agent_runtime import ScriptedProvider,registry,tool,run


def test_read_transient_retries_once_and_prepare_does_not():
    calls=[]
    def fail_then_success(args,token):
        calls.append(1)
        if len(calls)==1:raise ConnectionError('fixture')
        return ToolResult('success')
    result=run(ScriptedProvider(tool(),AgentDecision('final','Consulta concluída.')),registry(fail_then_success))
    assert result.status=='completed' and len(calls)==2
    calls.clear()
    result=run(ScriptedProvider(tool(),AgentDecision('final','Limitação.')),registry(fail_then_success,effect='prepare'))
    assert result.status=='partial' and len(calls)==1 and result.results[0][1].side_effect_state=='none'


def test_sync_handler_cancel_is_prompt_and_late_result_discarded():
    entered=threading.Event();release=threading.Event();finished=threading.Event();token=CancellationToken()
    def slow(args,cancel):
        entered.set();release.wait(3);finished.set();return ToolResult('success',data='tardio')
    async def exercise():
        task=asyncio.create_task(AgentRuntime(ScriptedProvider(tool()),registry(slow)).run('consulta',session_id='s',token=token))
        while not entered.is_set():await asyncio.sleep(.005)
        started=time.monotonic();token.cancel();result=await asyncio.wait_for(task,.5)
        assert result.status=='cancelled' and time.monotonic()-started<.5
        assert all(row.data!='tardio' for _,row in result.results)
    try:asyncio.run(exercise())
    finally:release.set();assert finished.wait(1)


def test_procedure_rejects_unverified_or_unrelated_receipt(tmp_path):
    store=SessionStore(tmp_path/'history.sqlite3');library=ProcedureLibrary(store)
    body={key:'Procedimento técnico genérico' for key in ('title','goal','preconditions','tools','steps','verification','limitations')}
    body['tools']='fixture';identifier=library.propose(body,{})
    library.transition(identifier,'testing',library.get(identifier)['digest'])
    for name,verified in [('fixture',False),('other',True)]:
        call=ToolCall(name,{})
        store.begin(call,'s','t','read');store.finish(call.id,'success',verified=verified)
        with pytest.raises(ValueError):library.record_test(identifier,call.id)


def test_migration_preserves_receipts_without_inventing_verification_and_cleans_backup(tmp_path):
    path=tmp_path/'history.sqlite3';store=SessionStore(path,enabled=True)
    store.append('s','user','Aurora')
    call=ToolCall('fixture',{});store.begin(call,'s','t','read');store.finish(call.id,'success')
    with store.connection() as db:
        db.execute('ALTER TABLE receipts DROP COLUMN verified');db.execute('PRAGMA user_version=1')
    migrated=SessionStore(path,enabled=True)
    backups=list((tmp_path/'migration-backups').glob('*.sqlite3'))
    assert len(backups)==1
    with migrated.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==2
        assert db.execute('SELECT verified FROM receipts').fetchone()[0]==0
    migrated.delete('s')
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM message_search').fetchone()[0]==0
    db.close()
    migrated.delete();assert not backups[0].exists()


def test_unknown_database_version_is_preserved(tmp_path):
    path=tmp_path/'future.sqlite3'
    with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=999')
    before=path.read_bytes()
    with pytest.raises(ValueError,match='Versão'):SessionStore(path)
    assert path.read_bytes()==before


def test_corrupt_database_is_preserved_and_blocks_runtime_before_any_tool(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from tests.test_agent_runtime import ScriptedProvider
    path=tmp_path/'state'/'sessions.sqlite3';path.parent.mkdir()
    damaged=b'corrupt controlled fixture PONTE-42';path.write_bytes(damaged)
    with pytest.raises(OSError):SessionStore(path)
    assert path.read_bytes()==damaged
    provider=ScriptedProvider()
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True},agent_state_root=path.parent,agent_provider=provider)
    try:
        result=host.process_command('Consulte uma nota')
        assert result.status=='ai_unavailable' and not provider.observations
        assert path.read_bytes()==damaged
    finally:host.close()


def test_active_procedure_is_usable_and_review_revokes_its_provenance(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from therion.agent import AgentDecision,ToolCall
    from tests.test_agent_runtime import ScriptedProvider
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True,'learning_enabled':True},agent_state_root=tmp_path/'state')
    try:
        store=host._get_agent_store();library=ProcedureLibrary(store)
        body={key:'Procedimento técnico fictício' for key in ('title','goal','preconditions','tools','steps','verification','limitations')}
        body['tools']='fixture';body['steps']='Conferir PONTE-42 antes de concluir.'
        identifier=library.propose(body,{'kind':'human_review'});row=library.get(identifier)
        reference={'id':'procedure:'+identifier,'source':body['title'],'version':row['digest']}
        assert not host._history_sources_allowed([reference])
        library.transition(identifier,'testing',row['digest'])
        for index in range(2):
            call=ToolCall('fixture',{'index':index});store.begin(call,'fixture','t','read');store.finish(call.id,'success',verified=True);library.record_test(identifier,call.id)
        library.transition(identifier,'active',row['digest'])
        assert host._history_sources_allowed([reference])
        host._agent_provider=ScriptedProvider(
            AgentDecision('tools',calls=(ToolCall('load_tools',{'names':['procedure_read']}),)),
            AgentDecision('tools',calls=(ToolCall('procedure_read',{'id':identifier}),)),
            AgentDecision('final','Conferir PONTE-42 antes de concluir.'))
        result=host.process_command('Consulte o procedimento técnico ativo.')
        assert result.status=='success' and 'PONTE-42' in result.message
        library.transition(identifier,'review',row['digest'])
        assert not host._history_sources_allowed([reference])
    finally:host.close()


def test_runtime_profiles_preserve_unknown_settings_and_do_not_change_legacy():
    from therion.agent.settings import validate_settings
    assert validate_settings({})['think'] is None
    profile=validate_settings({'think':False,'output_tokens':4096,'context_tokens':8192,'future_field':'preserved'})
    assert profile['think'] is False and profile['output_tokens']==4096 and profile['future_field']=='preserved'
    repaired=validate_settings({'context_tokens':True,'output_tokens':-1,'think':'false'})
    assert repaired['context_tokens']==8192 and repaired['output_tokens']==2048 and repaired['think'] is None


def test_gmail_history_is_hidden_after_local_account_revocation(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from therion.integrations.gmail import account_identity
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'gmail_enabled':True},agent_state_root=tmp_path/'state')
    try:
        root=host._agent_root/'credentials';root.mkdir(parents=True)
        token=root/'gmail-token.json'
        token.write_text(json.dumps({'client_id':'fixture','refresh_token':'account-one','scopes':['readonly']}))
        source={'id':'gmail:fixture','source':'https://mail.google.com/#all/fixture','account':account_identity(root)}
        assert host._history_sources_allowed([source])
        token.write_text(json.dumps({'client_id':'fixture','refresh_token':'account-two','scopes':['readonly']}))
        assert not host._history_sources_allowed([source])
        token.unlink()
        assert not host._history_sources_allowed([source])
    finally:host.close()


def test_full_history_iteration_and_export_beyond_fifty(tmp_path):
    store=SessionStore(tmp_path/'history.sqlite3',enabled=True)
    store.append('s','user','0')
    with store.connection() as db:
        now=store.clock()
        for number in range(1,125):
            cursor=db.execute('INSERT INTO messages(session,role,content,created,expires,sources) VALUES (?,?,?,?,?,?)',('s','user',str(number),now,now+86400,'[]'))
            db.execute('INSERT INTO message_search(rowid,content) VALUES (?,?)',(cursor.lastrowid,str(number)))
    assert len(list(store.iter_messages('s')))==125
    assert len(json.loads(store.export('s')))==125


def test_file_revocation_versions_and_history_dependencies(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from therion.context.second_brain import SecondBrainReader
    host=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_state_root=tmp_path/'state')
    host.second_brain=SecondBrainReader(str(tmp_path),allowed_roots=[str(tmp_path)])
    source=tmp_path/'note.md';source.write_text('Aurora',encoding='utf-8')
    ref={'id':'note:1','source':str(source),'version':hashlib.sha256(b'Aurora').hexdigest()}
    try:
        assert host._history_sources_allowed([ref])
        assert not host._history_sources_allowed([dict(ref,source='note.md')])
        host._agent_store=SessionStore(tmp_path/'state'/'history.sqlite3',enabled=True)
        host._agent_store.source_validator=host._history_sources_allowed
        message=host._agent_store.append('s','assistant','Aurora',sources=[ref])
        dependency={'id':'message:'+str(message),'source':'histórico local'}
        assert host._history_sources_allowed([dependency])
        source.write_text('Mudou',encoding='utf-8')
        assert not host._history_sources_allowed([ref]) and not host._history_sources_allowed([dependency])
        assert not host._agent_store.search('Aurora') and not host._agent_store.sessions()
        source.write_text('Aurora',encoding='utf-8')
        host._agent_store.delete('s')
        assert not host._history_sources_allowed([dependency])
    finally:host.close()


def test_oauth_start_failure_always_emits_completion(tmp_path):
    from PySide6.QtWidgets import QApplication
    from therion.interface.agent_panel import GmailAuthorizationWorker
    app=QApplication.instance() or QApplication([])
    worker=GmailAuthorizationWorker('fixture.json','read',tmp_path)
    messages=[];worker.completed.connect(messages.append)
    with patch('subprocess.Popen',side_effect=OSError('fixture unavailable')):worker.run()
    assert len(messages)==1 and 'Não consegui' in messages[0]
    worker.deleteLater();app.processEvents()


def test_context_compaction_preserves_current_tool_pair_and_originals():
    from copy import deepcopy
    from therion.agent.context import ContextBuilder
    builder=ContextBuilder();budget=TurnBudget(context_tokens=4096,output_tokens=1024)
    rows=[{'role':'system','content':'Regras estáveis.'}]
    rows.extend({'role':'user' if n%2 else 'assistant','content':str(n)+' Aurora '+('detalhe '*400)} for n in range(40))
    boundary=len(rows)
    active=[{'role':'user','content':'Recupere a informação antiga.'},
        {'role':'assistant','content':'','tool_calls':[{'id':'call-1','type':'function','function':{'name':'read','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'call-1','content':'{"status":"success","data":"PONTE-42"}'}]
    rows.extend(active);original=deepcopy(rows)
    result=builder.build(rows,[],budget,protected_from=boundary)
    assert result[-3:]==active and rows==original
    assert builder.estimate(result,[])<=3072
    assert 'não transcrição integral' in result[1]['content'] or 'omitida por orçamento' in result[1]['content']


def test_current_request_too_large_fails_explicitly():
    from therion.agent.context import ContextBuilder
    with pytest.raises(ValueError,match='orçamento'):
        ContextBuilder().build([{'role':'system','content':'Regras'},{'role':'user','content':'x'*16000}],[],TurnBudget(context_tokens=2048,output_tokens=1024),protected_from=1)


def test_context_reuses_identical_result_and_preserves_latest_full_observation():
    from therion.agent.context import ContextBuilder
    observation=json.dumps({'status':'success','data':'x'*1800,'evidence':[{'id':'fixture'}]})
    rows=[{'role':'system','content':'Regras'},
        {'role':'assistant','content':'','tool_calls':[{'id':'one'}]},
        {'role':'tool','tool_call_id':'one','content':observation},
        {'role':'assistant','content':'','tool_calls':[{'id':'two'}]},
        {'role':'tool','tool_call_id':'two','content':observation}]
    result=ContextBuilder().build(rows,[],TurnBudget(context_tokens=4096,output_tokens=2048),protected_from=1)
    assert result[-1]['content']==observation and rows[2]['content']==observation
    older=json.loads(result[2]['content'])
    assert older['data']=={'same_result_as_tool_call':'two'} and older['evidence']==[{'id':'fixture'}]


def test_visual_confirmation_uses_new_token_after_runtime_has_finished(tmp_path):
    from therion.agent.proposals import ActionProposals
    old=CancellationToken();old.cancel();fresh=CancellationToken();seen=[]
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'s')
    def execute(args,token):token.check();seen.append(token);return {'id':'fixture'}
    preview=proposals.prepare('fixture',{},'Prévia',execute,lambda args,value,token:True,
        lambda args,token:not token.cancelled,token_aware=True)
    result=proposals.approve_visual(preview.id,preview.digest,fresh)
    assert result.status=='success' and seen==[fresh]


def test_native_control_tool_waits_for_clarification_without_authorizing_action():
    from therion.agent.registry import ToolRegistry
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('ask_user',{'question':'Qual dia e horário?'}),)))
    result=run(provider,ToolRegistry())
    assert result.status=='awaiting_clarification' and result.message=='Qual dia e horário?'
    assert result.results[0][1].side_effect_state=='none'
