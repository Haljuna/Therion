"""Tarefa composta: apenas o controlador visual autoriza cada efeito."""
import asyncio
import threading

from therion.agent import AgentRuntime,AgentDecision,ToolCall,ToolResult,ToolSpec,CancellationToken,TurnBudget
from therion.agent.registry import ToolRegistry,object_schema,TEXT
from therion.agent.proposals import ActionProposals
from therion.agent.store import SessionStore


def test_two_approvals_continue_same_turn(tmp_path):
    store=SessionStore(tmp_path/'state.sqlite3');store.source_validator=lambda rows:True
    proposals=ActionProposals(store,lambda:'s');effects=[];events=[]
    class Provider:
        count=0
        async def decide(self,messages,*args):
            self.count+=1
            if self.count<3:return AgentDecision('tools',calls=(ToolCall('prepare',{'text':str(self.count)}),))
            assert 'receipt:' in str(messages) and 'verified' in str(messages)
            return AgentDecision('final','Salvei os dois resultados verificados.')
    def prepare(args,token):
        row=proposals.prepare('fixture.write',args,'Prévia '+args['text'],lambda value:effects.append(value['text']) or {'id':value['text']},lambda *args:True,lambda *args:True)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},side_effect_state='pending')
    tools=ToolRegistry();tools.register(ToolSpec('prepare','Prévia',object_schema(text=TEXT),prepare,effect='prepare',authorize=lambda args:True))
    async def approve():
        while len(effects)<2:
            for row in proposals.list():
                result=await asyncio.to_thread(proposals.approve_visual,row.id,row.digest,CancellationToken())
                assert result.status=='success'
            await asyncio.sleep(.01)
    async def scenario():
        approval=asyncio.create_task(approve())
        runtime=AgentRuntime(Provider(),tools,store=store,confirmations=proposals,emit=events.append)
        result=await runtime.run('Salve dois resultados',session_id='s')
        await approval
        return result
    result=asyncio.run(scenario())
    assert result.status=='completed' and effects==['1','2']
    assert sum(event.type=='awaiting_confirmation' for event in events)==2
    assert len({event.turn_id for event in events})==1
    assert len([row for row in store.operations() if row['tool']=='fixture.write' and row['verified']])==2


def test_cancel_waiting_does_not_execute(tmp_path):
    proposals=ActionProposals(SessionStore(tmp_path/'state.sqlite3'),lambda:'s')
    row=proposals.prepare('fixture.write',{},'Prévia',lambda _:(_ for _ in ()).throw(AssertionError('efeito')),lambda *args:True,lambda *args:True)
    token=CancellationToken();token.cancel()
    result=asyncio.run(proposals.wait_for_result(row.id,token,1))
    assert result.status=='cancelled' and proposals.list()==[]


def test_success_for_another_session_does_not_resume(tmp_path):
    session=['s'];proposals=ActionProposals(SessionStore(tmp_path/'state.sqlite3'),lambda:session[0])
    row=proposals.prepare('fixture.write',{},'Prévia',lambda _: {'id':'one'},lambda *args:True,lambda *args:True)
    proposals.approve_visual(row.id,row.digest,CancellationToken());session[0]='other'
    result=asyncio.run(proposals.wait_for_result(row.id,CancellationToken(),1))
    assert result.status=='uncertain'


def test_wait_timeout_invalidates_preview(tmp_path):
    proposals=ActionProposals(SessionStore(tmp_path/'state.sqlite3'),lambda:'s')
    row=proposals.prepare('fixture.write',{},'Prévia',lambda _:None,lambda *args:True,lambda *args:True)
    assert asyncio.run(proposals.wait_for_result(row.id,CancellationToken(),0)).status=='cancelled'
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
