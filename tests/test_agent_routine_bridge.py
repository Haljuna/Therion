import asyncio
from copy import deepcopy
from datetime import datetime,timezone
from therion.core.orchestrator import Orchestrator
from therion.autonomy.store import EvidenceStore
from therion.autonomy.runtime import AutonomyRuntime
from therion.autonomy.routines import RoutineService
from therion.agent.contracts import ToolCall,CancellationToken
from therion.agent.proposals import ActionProposals
from therion.agent.registry import ToolRegistry
from therion.integrations.routines import register_routine_tools


def setup(tmp_path):
    config={};now=lambda:datetime(2026,10,17,tzinfo=timezone.utc)
    def write(value):config.clear();config.update(deepcopy(value))
    runtime=AutonomyRuntime(EvidenceStore(tmp_path/'v4.sqlite3',now),lambda:deepcopy(config),write,now)
    class Calendar:
        def list_events_for_day(self,day):return []
    host=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),calendar_adapter=Calendar(),
        autonomy_runtime=runtime,agent_config={'enabled':True},agent_state_root=tmp_path/'agent')
    host._agent_proposals=ActionProposals(host._get_agent_store(),lambda:host.session_id)
    service=RoutineService(host,runtime);spec=service.configure('daily_summary',8,0)
    registry=ToolRegistry();register_routine_tools(registry,host)
    return host,runtime,service,spec,registry


def prepare(registry,identifier):
    call=ToolCall('routine_prepare_run',{'id':identifier});spec,blocked=registry.prepare(call)
    assert blocked is None
    return asyncio.run(spec.handler(call.arguments,CancellationToken()))


def test_v4_routine_needs_visual_confirmation_and_uses_existing_verified_receipt(tmp_path):
    host,runtime,service,spec,registry=setup(tmp_path)
    try:
        assert prepare(registry,spec.id).status=='awaiting_confirmation' and not runtime.store.recent()
        row=host._agent_proposals.list()[0]
        result=host._agent_proposals.approve_visual(row.id,row.digest,CancellationToken())
        assert result.status=='success' and runtime.store.recent()[0].verified
        assert service.entries()[0].enabled is False and runtime.policies()==[]
        progress=runtime.store.progress(spec.operation,spec.id,service.version(spec))
        assert progress['count']==1 and progress['ready'] is False
        assert host._agent_proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
    finally:host.close()


def test_changed_v4_routine_or_cancelled_confirmation_never_runs(tmp_path):
    host,runtime,service,spec,registry=setup(tmp_path)
    try:
        prepare(registry,spec.id);row=host._agent_proposals.list()[0]
        service.configure('daily_summary',9,0)
        assert host._agent_proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
        prepare(registry,spec.id);row=host._agent_proposals.list()[0];token=CancellationToken();token.cancel()
        assert host._agent_proposals.approve_visual(row.id,row.digest,token).status=='cancelled'
        assert not runtime.store.recent()
    finally:host.close()
