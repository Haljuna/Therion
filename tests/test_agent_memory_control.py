from pathlib import Path
from therion.core.orchestrator import Orchestrator
from therion.agent import AgentDecision,ToolCall
from tests.test_agent_runtime import ScriptedProvider
from tests.test_memory_supervised import setup


def test_supervised_memory_uses_runtime_without_sending_preview_to_model_or_history(tmp_path):
    class NeverModel:
        async def decide(self,*args):raise AssertionError('Prévia de memória não entra na inferência.')
    app=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_config={'enabled':True,'history_enabled':True},
        agent_state_root=tmp_path/'state',agent_provider=NeverModel())
    try:
        result=app.process_command('guarde que prefiro estudar cerâmica nas manhãs')
        assert result.status=='success' and 'Ainda não salvei' in result.message
        receipts=app._agent_store.operations()
        assert any(row['tool']=='memory_control' and row['state']=='success' for row in receipts)
        assert not app._agent_store.messages(app.session_id)
        # Busca da sessão também não transporta a prévia para o provider local.
        provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('load_tools',{'names':['search_session']}),)),
            AgentDecision('tools',calls=(ToolCall('search_session',{'query':'cerâmica'}),)),AgentDecision('final','Não encontrei essa informação na conversa recuperável.'))
        app._agent_provider=provider
        app.process_command('Consulte a conversa anterior sobre estudos.')
        assert 'prefiro estudar cerâmica' not in str(provider.observations)
        assert all('MEM-' not in str(messages) for messages in provider.observations)
    finally:app.close()


def test_legacy_memory_preview_is_excluded_even_with_history_enabled(tmp_path):
    app=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_config={'enabled':False,'history_enabled':True},agent_state_root=tmp_path/'state')
    try:
        app.process_command('guarde que prefiro estudar cerâmica nas manhãs')
        stored=str(app._agent_store.messages(app.session_id))
        assert 'cerâmica' not in stored and 'supervisionado' in stored
    finally:app.close()


def test_memory_save_status_query_does_not_confirm_the_pending_write(setup,tmp_path):
    make,root,_,_=setup;app=make();app._agent_config['enabled']=True;app._agent_root=tmp_path/'agent'
    try:
        assert app.process_command('lembre que prefiro exemplos curtos').status=='success'
        proposal=app.process_command('salve');assert proposal.status=='awaiting_confirmation'
        receipt=next(row for row in app._agent_store.operations() if row['state']=='awaiting_confirmation')
        assert not list(root.glob('RAS-*.md'))
        assert app.process_command('status da memória').status=='success'
        pending=app._agent_store.operations(receipt['call_id'])[0]
        assert pending['state']=='awaiting_confirmation' and pending['verified']==0
        assert app.confirm_session_proposal(proposal.plan,True,app.session_id,proposal.confirmation_id).status=='success'
        assert len(list(root.glob('RAS-*.md')))==1
        assert app._agent_store.operations(receipt['call_id'])[0]['verified']==1
    finally:app.close()
