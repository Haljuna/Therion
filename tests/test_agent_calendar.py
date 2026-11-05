import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from therion.agent.contracts import CancellationToken,ToolCall
from therion.agent.proposals import ActionProposals
from therion.agent.registry import ToolRegistry
from therion.agent.store import SessionStore
from therion.calendar.google_adapter import GoogleCalendarAdapter
from therion.integrations.calendar import register_calendar_tools,version


def test_verified_google_create_uses_fixed_id_and_independent_get():
    adapter=GoogleCalendarAdapter(verified_writes=True);service=Mock();adapter._get_service=lambda:service
    start=datetime.fromisoformat('2026-10-19T14:00:00-03:00');end=datetime.fromisoformat('2026-10-19T15:00:00-03:00')
    identifier='a'*32
    row={'id':identifier,'summary':'Aurora','start':{'dateTime':start.isoformat()},'end':{'dateTime':end.isoformat()}}
    service.events.return_value.insert.return_value.execute.return_value=dict(row,summary='Resposta inicial não usada como prova')
    service.events.return_value.get.return_value.execute.return_value=row
    event=adapter.create_event('Aurora',start,end,event_id=identifier)
    assert event.event_id==identifier and event.summary=='Aurora'
    assert service.events.return_value.insert.call_args.kwargs['body']['id']==identifier
    service.events.return_value.get.assert_called_once_with(calendarId='primary',eventId=identifier)
    service.close.assert_called_once()


def test_calendar_timeout_reconciles_same_id_without_repeating_create(tmp_path):
    events={};calls=[]
    def factory(operation,args,token):
        token.check()
        if operation=='create':
            calls.append(args['id']);events[args['id']]={'id':args['id'],'version':args['expected_version'],'summary':args['title']}
            raise TimeoutError('Resposta perdida depois do efeito fictício')
        return events[args['id']]
    store=SessionStore(tmp_path/'state.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'enabled':True},_calendar_adapter_factory=factory,calendar_adapter=object(),
        _agent_store=store,_agent_proposals=proposals,_agent_workers={})
    registry=ToolRegistry();assert register_calendar_tools(registry,host)
    async def invoke(name,args):
        spec,blocked=registry.prepare(ToolCall(name,args));assert blocked is None
        return await spec.handler(args,CancellationToken())
    args={'title':'Aurora','start':'2026-10-19T14:00:00-03:00','end':'2026-10-19T15:00:00-03:00'}
    prepared=asyncio.run(invoke('calendar_prepare_event',args));assert prepared.status=='awaiting_confirmation' and not calls
    row=proposals.list()[0]
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='uncertain'
    receipt=next(row for row in store.operations() if row['tool']=='calendar.create')
    assert receipt['state']=='uncertain' and receipt['result_refs'][0]['id'] in calls
    asyncio.run(invoke('calendar_prepare_event',dict(args,start='2026-10-19T17:00:00+00:00',end='2026-10-19T18:00:00+00:00')))
    second=proposals.list()[0]
    assert proposals.approve_visual(second.id,second.digest,CancellationToken()).status=='blocked' and len(calls)==1
    result=asyncio.run(invoke('calendar_inspect_result',{'call_id':receipt['call_id']}))
    assert result.status=='success' and len(calls)==1
    assert store.operations(receipt['call_id'])[0]['verified']==1


def test_calendar_ambiguous_timezone_does_not_prepare_write(tmp_path):
    store=SessionStore(tmp_path/'state.sqlite3');proposals=ActionProposals(store,lambda:'s')
    host=SimpleNamespace(_agent_config={'enabled':True},_calendar_adapter_factory=lambda *args:None,calendar_adapter=object(),
        _agent_store=store,_agent_proposals=proposals,_agent_workers={})
    registry=ToolRegistry();register_calendar_tools(registry,host)
    args={'title':'Aurora','start':'2026-10-19T14:00:00','end':'2026-10-19T15:00:00'}
    spec,blocked=registry.prepare(ToolCall('calendar_prepare_event',args));assert blocked is None
    assert asyncio.run(spec.handler(args,CancellationToken())).status=='awaiting_clarification'
    assert proposals.list()==[]


def test_calendar_worker_refuses_changed_account_before_api(tmp_path,monkeypatch):
    from therion.integrations.calendar import CalendarSession
    monkeypatch.setattr('therion.integrations.calendar.account_identity',lambda *args:'changed')
    worker=CalendarSession({'credentials_root':str(tmp_path),'account':'original'})
    worker.adapter=Mock()
    import pytest
    with pytest.raises(ValueError,match='conta'):worker.dispatch('get',{'id':'event'})
    worker.adapter.get_event.assert_not_called()


def test_strict_calendar_follows_pages_and_closes_transport():
    from datetime import date
    adapter=GoogleCalendarAdapter(verified_writes=True);service=Mock();adapter._get_service=lambda:service
    def item(identifier):return {'id':identifier,'summary':'Aurora','start':{'date':'2026-10-19'},'end':{'date':'2026-10-20'}}
    service.events.return_value.list.return_value.execute.side_effect=[{'items':[item('one')],'nextPageToken':'next'},{'items':[item('two')]}]
    rows=adapter.list_events_for_day(date(2026,10,19))
    assert [row.event_id for row in rows]==['one','two']
    assert service.events.return_value.list.call_args.kwargs['pageToken']=='next'
    service.close.assert_called_once()
