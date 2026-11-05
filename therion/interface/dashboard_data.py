"""Adaptador do painel para os serviços existentes; sem modelo nem OAuth implícito."""
import asyncio
from datetime import date, datetime
import os
from pathlib import Path
from therion.agent.contracts import CancellationToken, ToolCall, ToolResult


class DashboardSource:
    def __init__(self, orchestrator):
        self.host = orchestrator

    def identity(self):
        from therion.integrations.calendar import account_key
        h = self.host
        return (h.session_id, account_key(h), id(h._agent_store),
                bool(h._agent_config.get('tasks_enabled') or h._agent_config.get('gmail_enabled')))

    def calendar(self, day, token):
        from therion.calendar.google_adapter import GoogleCalendarAdapter
        from therion.integrations.calendar import account_key
        from therion.integrations.rpc import OwnedWorker
        h = self.host
        token.check()
        if h.calendar_adapter is None:
            return {'state':'disconnected','message':'Agenda não configurada. Configure a conexão Google Calendar.', 'items':[]}
        adapter = h.calendar_adapter
        account = account_key(h)
        if isinstance(adapter, GoogleCalendarAdapter):
            if not account:
                return {'state':'disconnected','message':'Conecte sua conta Google Calendar.', 'items':[]}
            root = Path(os.environ['APPDATA'])/'Therion' if os.environ.get('APPDATA') else Path.home()/'.config'/'Therion'
            worker = OwnedWorker('calendar',{'time_zone':adapter._time_zone,
                                 'credentials_root':str(root),'account':account})
            try:
                rows = worker.call('list',{'day':day.isoformat()},token,timeout=30)
            finally:
                worker.close()
        else:
            rows = [dict(summary=e.summary, start=e.start.isoformat(), all_day=e.all_day)
                    for e in adapter.list_events_for_day(day)]
        token.check()
        if account_key(h) != account:
            raise ValueError('A conta da agenda mudou durante a consulta.')
        tz = h._calendar_now().tzinfo
        items = []
        for row in rows:
            start = row['start']
            when = 'Dia inteiro' if row['all_day'] else datetime.fromisoformat(start).astimezone(tz).strftime('%H:%M')
            items.append({'title':row['summary'], 'time':when})
        return {'state':'ready','items':items,'message':'Nenhum compromisso neste dia.' if not items else ''}

    def tasks(self, token):
        from therion.integrations.tasks import TaskInbox
        h = self.host
        token.check()
        temporary = [dict(id=t.id,title=t.description,completed=t.completed) for t in h._session_tasks.list()]
        allowed = h._agent_config.get('tasks_enabled') is True or h._agent_config.get('gmail_enabled') is True
        if not allowed:
            return {'state':'disconnected','message':'Ative Tarefas locais em Capacidades.', 'saved':[], 'temporary':temporary}
        # Mesmo repositório usado pelas ferramentas, sem leitura de outras fontes.
        rows = TaskInbox(h._get_agent_store()).list(limit=100)
        token.check()
        return {'state':'ready','message':'','saved':rows,'temporary':temporary}

    def action(self, operation, arguments, token):
        return self.host.dashboard_action(operation, arguments, token)

    def mailbox(self,operation,arguments,token):
        return self.host.mailbox_request(operation,arguments,token)

    def mailbox_status(self):
        return self.mailbox('status',{},CancellationToken())


def dashboard_action(host, operation, arguments, token):
    """Entrada determinística do orquestrador para pedidos explícitos do painel."""
    from therion.agent.proposals import ActionProposals
    from therion.agent.registry import ToolRegistry
    from therion.integrations.tools import register_personal_tools
    token.check()
    if operation in {'session_add','session_state'}:
        request = ({'operation':'add','text':arguments['title']} if operation == 'session_add'
                   else {'operation':'complete' if arguments['completed'] else 'reopen','id':str(arguments['id'])})
        result = host._handle_session_tasks(request)
        return ToolResult('success' if result.status == 'success' else 'blocked', message=result.message)
    if operation not in {'prepare_task','prepare_task_state','approve','discard'}:
        return ToolResult('blocked', message='Operação do painel não cadastrada.')
    allowed = host._agent_config.get('tasks_enabled') is True or host._agent_config.get('gmail_enabled') is True
    if operation.startswith('prepare_') and not allowed:
        return ToolResult('blocked', message='Tarefas locais não estão autorizadas. Configure em Capacidades.')
    host._get_agent_store()
    if host._agent_proposals is None:
        host._agent_proposals = ActionProposals(host._agent_store, lambda:host.session_id,
            dependencies=lambda:host._agent_runtime.sources if host._agent_runtime and host._agent_runtime.active else (),
            verify_dependencies=lambda sources,cancel:host._history_sources_allowed(sources))
    if operation == 'approve':
        return host._agent_proposals.approve_visual(arguments['id'],arguments['digest'],token)
    if operation == 'discard':
        host._agent_proposals.discard(arguments['id'])
        return ToolResult('cancelled',message='Proposta descartada.')
    registry = ToolRegistry()
    register_personal_tools(registry, host)
    call = ToolCall(operation, arguments)
    spec, blocked = registry.prepare(call)
    return blocked or asyncio.run(spec.handler(arguments, token))
