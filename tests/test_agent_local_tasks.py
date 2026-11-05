import asyncio
from types import SimpleNamespace
import pytest

from therion.agent.contracts import ToolCall,CancellationToken
from therion.agent.proposals import ActionProposals
from therion.agent.registry import ToolRegistry
from therion.agent.store import SessionStore
from therion.integrations.tasks import TaskInbox
from therion.integrations.tools import register_personal_tools


def setup(tmp_path):
    store=SessionStore(tmp_path/'state.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'tasks_enabled':True,'gmail_enabled':False},_agent_store=store,_agent_proposals=proposals,_agent_workers={})
    registry=ToolRegistry();register_personal_tools(registry,host)
    return store,proposals,registry


def invoke(registry,name,args):
    spec,blocked=registry.prepare(ToolCall(name,args));assert blocked is None
    return asyncio.run(spec.handler(args,CancellationToken()))


def test_local_tasks_work_without_gmail_and_without_network(tmp_path):
    store,proposals,registry=setup(tmp_path)
    assert not any(row['function']['name'].startswith('gmail_') for row in registry.schemas())
    args={'title':'Revisar Aurora','source_id':'user:current','due':''}
    result=invoke(registry,'prepare_task',args)
    assert result.status=='awaiting_confirmation' and TaskInbox(store).list()==[]
    row=proposals.list()[0];approved=proposals.approve_visual(row.id,row.digest,CancellationToken())
    assert approved.status=='success' and approved.side_effect_state=='verified'
    tasks=invoke(registry,'list_inbox',{}).data['tasks']
    assert len(tasks)==1 and tasks[0]['title']=='Revisar Aurora'


def test_uncertain_local_create_cannot_be_repeated_with_new_id_or_timezone(tmp_path,monkeypatch):
    store,proposals,registry=setup(tmp_path);original=TaskInbox.create;calls=[]
    def create(self,*args,**kwargs):
        identifier=original(self,*args,**kwargs);calls.append(identifier);raise TimeoutError('Depois do commit fictício')
    monkeypatch.setattr(TaskInbox,'create',create)
    args={'title':'Revisar Aurora','source_id':'user:current','due':'2026-10-19T14:00:00-03:00'}
    invoke(registry,'prepare_task',args);row=proposals.list()[0]
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='uncertain'
    receipt=next(row for row in store.operations() if row['tool']=='tasks.create')
    invoke(registry,'prepare_task',dict(args,due='2026-10-19T17:00:00+00:00'));second=proposals.list()[0]
    assert proposals.approve_visual(second.id,second.digest,CancellationToken()).status=='blocked' and len(calls)==1
    reconciled=invoke(registry,'tasks_inspect_result',{'call_id':receipt['call_id']})
    assert reconciled.status=='success' and store.operations(receipt['call_id'])[0]['verified']==1
    assert len(TaskInbox(store).list())==1


def test_inbox_filter_and_pagination_preserve_old_pending_tasks(tmp_path):
    store,proposals,registry=setup(tmp_path);inbox=TaskInbox(store)
    first=inbox.create('Pendente antiga',{'id':'user:current'})
    for index in range(15):
        identifier=inbox.create('Concluída '+str(index),{'id':'user:current'});inbox.set_state(identifier,'completed')
    assert invoke(registry,'list_inbox',{'state':'pending'}).data['tasks'][0]['id']==first
    page=invoke(registry,'list_inbox',{'state':'completed','limit':5}).data
    assert len(page['tasks'])==5 and page['next_offset']==5


def test_legacy_uncertain_fingerprint_requires_reconciliation(tmp_path):
    store=SessionStore(tmp_path/'state.sqlite3');old=ToolCall('calendar.create',{'id':'old'})
    store.begin(old,'s','t','external');store.finish(old.id,'uncertain')
    new=ToolCall('calendar.create',{'id':'new','expected_version':'different','_account':'fixture'})
    with pytest.raises(ValueError,match='antigo incerto'):store.begin(new,'s','t2','external')
