"""Referência estável não concede acesso nem oculta mudanças da fonte."""
from therion.agent import AgentDecision,ToolCall
from tests.test_agent_followup_sources import host_with_read_note


def test_reread_selected_source_without_search_preserves_id_and_verifies_new_call(tmp_path):
    host,_=host_with_read_note(tmp_path,AgentDecision('final','unused'))
    try:
        host._agent_provider.decisions=iter([
            AgentDecision('tools',calls=(ToolCall('read_source',{'source_id':'note:1'}),)),
            AgentDecision('final','O código é PONTE-42. Fonte: note:1.')])
        result=host.process_command('Leia novamente a nota Aurora.md inteira.')
        assert result.status=='success',result.message
        calls=host._get_agent_store().operations()
        assert len([row for row in calls if row['tool']=='search_notes'])==1
        assert len([row for row in calls if row['tool']=='read_source' and row['verified']])==2
        events=host.agent_events()
        assert any(event.type=='tool_finished' and (event.payload.get('reading') or {}).get('complete') is True for event in events)
    finally:host.close()


def test_old_selection_returns_no_content_after_source_change_or_revocation(tmp_path):
    from therion.agent.builtin import build_read_registry
    from therion.agent import CancellationToken
    import asyncio
    host,note=host_with_read_note(tmp_path,AgentDecision('final','unused'))
    try:
        registry=build_read_registry(host)
        spec,_=registry.prepare(ToolCall('read_source',{'source_id':'note:1'}))
        note.write_text('SEGREDO DA VERSÃO NOVA',encoding='utf-8')
        result=asyncio.run(spec.handler({'source_id':'note:1'},CancellationToken()))
        assert result.status=='blocked' and result.data is None
        host.second_brain.allowed_roots=[]
        result=asyncio.run(spec.handler({'source_id':'note:1'},CancellationToken()))
        assert result.status=='blocked' and result.data is None
    finally:host.close()


def test_alias_controls_keep_existing_flow_with_agent_enabled(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from tests.test_agent_runtime import ScriptedProvider
    for command in ('liste meus aliases','adicione um alias','exclua um alias','substitua um alias'):
        provider=ScriptedProvider()
        host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
            agent_config={'enabled':True},agent_provider=provider,agent_state_root=tmp_path/'state')
        try:
            result=host.process_command(command)
            assert result.status not in ('ai_unavailable','ai_invalid_response','unknown_intent'),result
            assert not provider.observations
        finally:host.close()


def test_old_sources_leave_capacity_for_new_searches(tmp_path):
    import asyncio
    from therion.agent.builtin import build_read_registry
    from therion.agent import CancellationToken
    host,_=host_with_read_note(tmp_path,AgentDecision('final','unused'))
    try:
        host._agent_turn_sources[(host.session_id,'fictitious')]=[
            {'id':f'note:{index+2}','source':str(tmp_path/f'old-{index}.md'),'version':'old'} for index in range(256)]
        registry=build_read_registry(host)
        spec,_=registry.prepare(ToolCall('search_notes',{'query':'Aurora'}))
        result=asyncio.run(spec.handler({'query':'Aurora'},CancellationToken()))
        assert result.status=='success' and result.data
    finally:host.close()


def test_simple_calendar_query_keeps_deterministic_path(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from tests.test_agent_runtime import ScriptedProvider
    class Calendar:
        def list_events_for_day(self,day):return []
    provider=ScriptedProvider()
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        calendar_adapter=Calendar(),agent_config={'enabled':True},agent_provider=provider,
        agent_state_root=tmp_path/'state')
    try:
        result=host.process_command('Minha agenda')
        assert result.status=='success',result
        assert not provider.observations
    finally:host.close()
