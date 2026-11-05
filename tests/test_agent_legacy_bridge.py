"""Confirmação real do fluxo legado e recibo central, com efeito de SO simulado."""
from unittest.mock import Mock
from therion.agent import AgentDecision,ToolCall
from therion.core.orchestrator import Orchestrator
from tests.test_agent_runtime import ScriptedProvider


def test_desktop_legacy_confirmation_resumes_runtime_without_deadlock_or_real_effect(tmp_path):
    import threading,time
    from therion.agent.contracts import CancellationToken
    app,command=host(tmp_path);app._agent_ui_confirmations=True
    app._agent_provider=ScriptedProvider(
        AgentDecision('tools',calls=(ToolCall('load_tools',{'names':['prepare_existing_action']}),)),
        AgentDecision('tools',calls=(ToolCall('prepare_existing_action',{'command':command}),)),
        AgentDecision('final','Simulei a abertura; nenhum aplicativo foi iniciado.'))
    app.executor.execute_real=Mock(side_effect=AssertionError('Não executar SO'))
    results=[];approved=[]
    worker=threading.Thread(target=lambda:results.append(app.process_command(command)))
    approval=None
    try:
        worker.start();deadline=time.monotonic()+3
        while not (app._agent_proposals and app._agent_proposals.list()) and time.monotonic()<deadline:time.sleep(.005)
        row=app._agent_proposals.list()[0]
        approval=threading.Thread(target=lambda:approved.append(app._agent_proposals.approve_visual(row.id,row.digest,CancellationToken())))
        approval.start();approval.join(timeout=3);worker.join(timeout=3)
        assert not approval.is_alive() and not worker.is_alive()
        assert approved[0].status=='success' and results[0].status=='success'
        assert 'Simulei' in results[0].message
        receipts=app._agent_store.operations()
        assert any(item['tool']=='apps.open' and item['state']=='simulated' for item in receipts)
        assert not any(item['verified'] for item in receipts)
        app.executor.execute_real.assert_not_called()
        assert sum(turn.role=='user' and turn.text==command for turn in app.memory.turns)==1
    finally:
        app.cancel_agent();worker.join(timeout=3)
        if approval:approval.join(timeout=3)
        app.close()


def host(tmp_path):
    command='abra o Obsidian'
    provider=ScriptedProvider(
        AgentDecision('tools',calls=(ToolCall('load_tools',{'names':['prepare_existing_action']}),)),
        AgentDecision('tools',calls=(ToolCall('prepare_existing_action',{'command':command}),)))
    return Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True},agent_provider=provider,agent_state_root=tmp_path/'state'),command


def test_pending_legacy_confirmation_updates_receipt_without_real_execution(tmp_path):
    app,command=host(tmp_path)
    try:
        result=app.process_command(command)
        assert result.status=='awaiting_confirmation' and result.plan is not None
        assert not app._workflow_cancel_event.is_set()
        identifier=app._confirmation_id
        binding=app._agent_legacy_pending[identifier]
        app.executor.execute_real=Mock(side_effect=AssertionError('Não executar SO'))
        final=app.confirm_session_proposal(result.plan,True,app.session_id,identifier)
        assert final.status=='executed_simulated'
        receipt=app._agent_store.operations(binding['call_id'])[0]
        assert receipt['state']=='simulated' and receipt['verified']==0
        assert app.confirm_session_proposal(result.plan,True,app.session_id,identifier).status=='cancelled'
        app.executor.execute_real.assert_not_called()
    finally:app.close()


def test_legacy_cancel_is_recorded_and_pending_does_not_resume_after_restart(tmp_path):
    app,command=host(tmp_path)
    try:
        result=app.process_command(command);identifier=app._confirmation_id
        binding=app._agent_legacy_pending[identifier]
        assert app.confirm_session_proposal(result.plan,False,app.session_id,identifier).status=='cancelled'
        assert app._agent_store.operations(binding['call_id'])[0]['state']=='cancelled'
    finally:app.close()


def test_opening_history_first_recovers_receipts_only_once(tmp_path):
    from therion.agent.store import SessionStore
    path=tmp_path/'state'/'sessions.sqlite3'
    old=SessionStore(path)
    old.begin(ToolCall('fixture_write',{}),'previous','old','external')
    app,command=host(tmp_path)
    try:
        store=app._get_agent_store()
        assert store.operations()[0]['state']=='uncertain'
        live=ToolCall('fixture_live',{})
        store.begin(live,app.session_id,'live','external')
        assert app._get_agent_store() is store
        assert store.operations(live.id)[0]['state']=='running'
    finally:app.close()


def test_operational_audit_does_not_create_a_hidden_transcript(tmp_path):
    from therion.memory.working_memory import TaskContext
    app,command=host(tmp_path)
    try:
        app.memory.current_task=TaskContext(command='Segredo fictício PONTE-42',target='PONTE-42',
            plan_steps=['PONTE-42'],execution_result='PONTE-42',verification_result='PONTE-42',
            context_queries=[{'content':'PONTE-42'}])
        app.audit_logger.log_task=Mock(return_value=True)
        app._complete_task()
        recorded=app.audit_logger.log_task.call_args.args[0]
        assert 'PONTE-42' not in str(recorded.to_dict())
        assert recorded.task_id==app.memory.history[-1].task_id
    finally:app.close()


def test_restrictive_memory_controls_cancel_active_turn_and_reach_legacy_policy(tmp_path):
    from therion.agent import CancellationToken
    app,_=host(tmp_path)
    try:
        for command in ('pause a memória','revogue a gravação de memória','revogue o acesso ampliado'):
            token=CancellationToken();app._agent_turn_token=token
            app._agent_original_request='Pedido em andamento'
            assert app._dispatch_agent(command) is None
            assert token.cancelled
            assert app._agent_original_request=='Pedido em andamento'
    finally:
        app._agent_turn_token=None;app.close()
