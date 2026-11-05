"""Agenda existente no núcleo: SDK reaproveitado em worker e confirmação central."""
from datetime import date,datetime,timezone
from dataclasses import asdict
import os
from pathlib import Path
import uuid

from therion.agent.contracts import ToolCall,ToolResult,ToolSpec,CancellationToken
from therion.agent.execution import cooperative_call
from therion.agent.proposals import fingerprint
from therion.agent.registry import object_schema,TEXT
from .gmail import account_identity
from .rpc import OwnedWorker


def account_key(host):
    factory=getattr(host,'_calendar_adapter_factory',None)
    if factory:return fingerprint(['fixture',id(factory)])
    from therion.calendar.google_adapter import GoogleCalendarAdapter
    if isinstance(host.calendar_adapter,GoogleCalendarAdapter):
        root=Path(os.environ['APPDATA'])/'Therion' if os.environ.get('APPDATA') else Path.home()/'.config'/'Therion'
        return account_identity(root,'token.json')
    return fingerprint(['adapter',id(host.calendar_adapter)]) if host.calendar_adapter is not None else None


def version(title,start,end):
    return fingerprint([title.strip(),start.astimezone(timezone.utc).isoformat(),end.astimezone(timezone.utc).isoformat()])


class CalendarSession:
    def __init__(self,config):
        from therion.calendar.google_adapter import GoogleCalendarAdapter
        self.config=config
        self.adapter=GoogleCalendarAdapter(config.get('time_zone','America/Sao_Paulo'),verified_writes=True)
        self.adapter._expected_account=config.get('account')

    def dispatch(self,operation,args):
        expected=self.config.get('account')
        root=self.config.get('credentials_root')
        if expected is not None and (not root or account_identity(root,'token.json')!=expected):
            raise ValueError('A conta da agenda mudou desde a preparação.')
        if operation=='list':
            events=self.adapter.list_events_for_day(date.fromisoformat(args['day']))
            if expected is not None and account_identity(root,'token.json')!=expected:raise ValueError('A conta mudou durante a consulta da agenda.')
            return [dict(asdict(event),start=event.start.isoformat(),end=event.end.isoformat()) for event in events]
        if operation=='get':event=self.adapter.get_event(args['id'])
        elif operation=='create':event=self.adapter.create_event(args['title'],datetime.fromisoformat(args['start']),datetime.fromisoformat(args['end']),event_id=args['id'])
        else:raise ValueError('Operação de agenda não cadastrada.')
        if expected is not None and account_identity(root,'token.json')!=expected:
            raise ValueError('A conta da agenda mudou durante a operação; consulte o resultado antes de repetir.')
        row=asdict(event);row['id']=row.pop('event_id');row['start']=event.start.isoformat();row['end']=event.end.isoformat()
        row['version']=version(event.summary,event.start,event.end) if not event.all_day else fingerprint(row)
        return row

    def close(self):pass


def worker_call(host,operation,args,token,account):
    root=Path(os.environ['APPDATA'])/'Therion' if os.environ.get('APPDATA') else Path.home()/'.config'/'Therion'
    configuration={'time_zone':host.calendar_adapter._time_zone,'credentials_root':str(root),'account':account}
    key='calendar'
    if key in host._agent_workers and host._agent_workers[key].config!=configuration:
        host._agent_workers[key].close();host._agent_workers.pop(key)
    if key not in host._agent_workers:host._agent_workers[key]=OwnedWorker('calendar',configuration)
    return host._agent_workers[key].call(operation,args,token)


class RuntimeCalendarReadAdapter:
    """Agenda para rotinas antigas com transporte/conta/cancelamento novos."""
    def __init__(self,host,token):self.host,self.token,self.account=host,token,account_key(host)
    def list_events_for_day(self,day):
        from therion.calendar.adapter import CalendarError
        from therion.calendar.models import CalendarEvent
        try:
            self.token.check()
            if self.account is None or account_key(self.host)!=self.account:raise ValueError('Conta da agenda alterada.')
            rows=worker_call(self.host,'list',{'day':day.isoformat()},self.token,self.account)
            if account_key(self.host)!=self.account:raise ValueError('Conta da agenda alterada durante a consulta.')
            return [CalendarEvent(event_id=row['event_id'],summary=row['summary'],
                start=(date if row['all_day'] else datetime).fromisoformat(row['start']),
                end=(date if row['all_day'] else datetime).fromisoformat(row['end']),all_day=row['all_day'],description=row.get('description')) for row in rows]
        except (ValueError,OSError) as error:raise CalendarError('Não consultei a agenda com segurança; não tratei como dia vazio.') from error


def register_calendar_tools(registry,host):
    from therion.calendar.google_adapter import GoogleCalendarAdapter
    factory=getattr(host,'_calendar_adapter_factory',None)
    if not factory and not isinstance(host.calendar_adapter,GoogleCalendarAdapter):return False
    account=account_key(host);proposals=host._agent_proposals
    def enabled():return host._agent_config.get('enabled') is True and account is not None and account_key(host)==account
    def call(operation,args,token):
        if factory:return factory(operation,args,token)
        return worker_call(host,operation,args,token,account)
    async def prepare(args,token):
        token.check()
        try:
            start=datetime.fromisoformat(args['start']);end=datetime.fromisoformat(args['end'])
            if not start.tzinfo or not end.tzinfo or end<=start or not args['title'].strip():raise ValueError()
        except ValueError:return ToolResult('awaiting_clarification',message='Informe título, início e fim com data, horário e fuso explícitos.')
        frozen=dict(args,id=uuid.uuid4().hex,_account=account,expected_version=version(args['title'],start,end))
        def verify(row,result,cancel):
            if not enabled():return False
            fresh=call('get',{'id':row['id']},cancel)
            return fresh.get('id')==row['id'] and fresh.get('version')==row['expected_version'] and enabled()
        row=proposals.prepare('calendar.create',frozen,'Criar evento no calendário\nTítulo: '+args['title']+'\nInício: '+start.isoformat()+'\nFim: '+end.isoformat(),
            lambda row,cancel:call('create',row,cancel),verify,lambda row,cancel:enabled(),token_aware=True,preparation_token=token)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},message='Revise o evento completo no painel Capacidades.',side_effect_state='pending')
    async def inspect(args,token):
        receipts=host._agent_store.operations(args['call_id'])
        if not receipts or receipts[0]['tool']!='calendar.create':return ToolResult('blocked',message='Recibo de criação de evento não encontrado.')
        receipt=receipts[0];refs=receipt['result_refs']
        target=next((row for row in refs if row.get('_account')==account and row.get('id') and row.get('expected_version')),None)
        if target is None:return ToolResult('blocked',message='O recibo não pertence à conta de agenda atual.')
        data=await cooperative_call(call,'get',{'id':target['id']},token,token=token);token.check()
        if not enabled() or data.get('version')!=target['expected_version']:return ToolResult('uncertain',message='Não confirmei o evento correspondente à prévia. Não repeti a criação.',side_effect_state='uncertain')
        host._agent_store.finish(receipt['call_id'],'success',verified=True)
        return ToolResult('success',data=data,evidence=({'id':'calendar:'+data['id'],'source':'Google Calendar','version':data['version'],'account':account},
            {'id':'receipt:'+receipt['call_id'],'source':'recibo reconciliado'}))
    registry.register(ToolSpec('calendar_prepare_event','Preparar evento com datas/fuso explícitos, usando agenda existente e confirmação visual. Não confirma pelo modelo.',
        object_schema(title=dict(type='string',minLength=1,maxLength=500),start=TEXT,end=TEXT),prepare,effect='prepare',authorize=lambda args:enabled(),available=enabled))
    registry.register(ToolSpec('calendar_inspect_result','Reconciliar por ID um evento incerto, sem repetir criação.',object_schema(call_id=TEXT),inspect,authorize=lambda args:enabled(),available=enabled))
    return True
