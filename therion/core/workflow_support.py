"""Integração interna de workflows; reutiliza os serviços e controles do orquestrador."""
from copy import deepcopy

from therion.calendar.adapter import CalendarError
from therion.calendar.dialogue import event_datetimes, parse_day, query_request
from therion.context.language import control
from therion.context.note_references import NoteResults
from therion.context.read_scope import effective_roots, _canonical
from therion.context.second_brain import SearchTrace
from therion.core.intent import Intent
from therion.core.workflow_runtime import WorkflowRuntime, render_workflow
from therion.memory.knowledge import SourceReference
from therion.memory.session_tasks import task_request


class WorkflowSupport:
    def _init_workflows(self):
        import threading
        self._workflows = WorkflowRuntime()
        self._workflow_cancel_event = threading.Event()
        self._workflow_running = False

    def cancel_workflow(self):
        cancel_agent = getattr(self, 'cancel_agent', None)
        if callable(cancel_agent):
            cancel_agent()
        self._workflow_cancel_event.set()
        self._workflows.cancel()

    def workflow_progress(self):
        return self._workflows.snapshot()

    def _workflow_control(self, command):
        from therion.core.orchestrator import OrchestrationResult
        cleaned = control(command)
        if cleaned not in {'status do pedido', 'status do pedido composto', 'mostre as etapas',
                'cancele o pedido', 'cancelar pedido', 'cancele pedido', 'cancele as etapas restantes'}:
            return None
        if cleaned.startswith(('cancele', 'cancelar')):
            self.cancel_workflow()
            self._workflows.abandon()
            self._reset_calendar_create_flow()
            self._confirmation_id = None
        snapshot = self._workflows.snapshot()
        message, speech = render_workflow(snapshot) if snapshot else ('Não há pedido composto nesta sessão.', 'Não há pedido composto nesta sessão.')
        self.memory.add_turn('user', command, origin='workflow_status')
        self.memory.add_turn('therion', message, origin='workflow_status')
        return OrchestrationResult(status='success', message=message, speech_message=speech,
            confirmation_id=self._confirmation_id)

    def _try_workflow(self, command, scope):
        from therion.core.orchestrator import OrchestrationResult
        from therion.core.workflows import interpret_workflow, WorkflowError
        provider = getattr(self.ai_core, '_provider', None) if self.ai_core is not None else None
        try:
            now = self._calendar_now()
        except CalendarError:
            now = None
        try:
            spec = interpret_workflow(command, provider=provider, context={'now':now})
            if spec is None:
                # Um comando novo e explícito substitui a proposta terminal anterior.
                if self._workflows.active and (task_request(command) or query_request(command)):
                    self._workflows.abandon()
                    self._reset_calendar_create_flow()
                return None
            self._preflight_workflow(spec)
        except (WorkflowError, CalendarError, ValueError) as error:
            self._workflows.abandon()
            self._reset_calendar_create_flow()
            result = OrchestrationResult(status='clarification', message=str(error))
            self._complete_task()
            self._finalize_session_result(result)
            return result
        self._workflows.abandon()
        self._reset_alias_flow(); self._reset_delete_alias_flow(); self._reset_replace_alias_flow()
        self._reset_unknown_target_flow(); self._reset_open_app_flow(); self._reset_calendar_create_flow()
        self._pending_clarification = None
        self._note_results = NoteResults((), ())
        self._last_tool_evidence = None
        self._recent_note_index = None
        self._workflow_running = True
        contains_tasks = any(step.action.startswith('task_') for step in spec.steps)
        if contains_tasks and self.memory.turns:
            self._task_turn_ids.add(self.memory.turns[-1].turn_id)
        # Não registrar descrições de tarefas compostas na auditoria persistente.
        self.memory.record_intent('tarefas da sessão', None)
        try:
            snapshot = self._workflows.run(spec, self.session_id,
                lambda step, index, rows: self._execute_workflow_step(step, index, rows, scope),
                cancelled=self._workflow_cancel_event)
        finally:
            self._workflow_running = False
        if snapshot.state == 'cancelled':
            self._reset_calendar_create_flow()
        message, speech = render_workflow(snapshot)
        status = ('awaiting_confirmation' if snapshot.state == 'awaiting_confirmation' else
            'cancelled' if snapshot.state == 'cancelled' else
            'clarification' if snapshot.state == 'awaiting_clarification' else 'success')
        result = OrchestrationResult(status=status, message=message, speech_message=speech)
        self._complete_task()
        self._finalize_session_result(result)
        if contains_tasks and self.memory.turns:
            self._task_turn_ids.add(self.memory.turns[-1].turn_id)
        return result

    def _preflight_workflow(self, spec):
        tasks = deepcopy(self._session_tasks)
        for step in spec.steps:
            args = step.arguments
            if step.action == 'calendar_create':
                event_datetimes(deepcopy(args['draft']), self._calendar_now())
            elif step.action == 'calendar_query':
                parse_day(args['request'].get('date', 'hoje'), self._calendar_now())
            elif step.action.startswith('task_'):
                request = args['request']
                if request['operation'] == 'add':
                    tasks.add(request['text'])
                elif request['operation'] in {'complete', 'reopen'}:
                    tasks.update(request['id'], request['operation'] == 'complete')

    def _execute_workflow_step(self, step, index, rows, scope):
        from therion.core.orchestrator import OrchestrationResult
        args = deepcopy(step.arguments)
        if self._workflow_cancel_event.is_set():
            return OrchestrationResult(status='cancelled', message='Etapa cancelada.'), None
        if step.action.startswith('task_'):
            result = self._handle_session_tasks(args['request'])
            return result, {'kind':'tasks', 'read_only':True, 'items':self._session_tasks.context()}
        if step.action == 'calendar_query':
            if self.calendar_adapter is None:
                return OrchestrationResult(status='execution_failed', message='Calendário não disponível; não verifiquei seus compromissos.'), None
            intent = Intent(action='consultar agenda', target='', raw_command=step.command)
            if args.get('plan_day'):
                from therion.skills.registry import get_skill
                now = self._calendar_now()
                result = get_skill('SKILL-002')(calendar=self.calendar_adapter, second_brain=self.second_brain).execute(today=now.date(), now=now)
                return OrchestrationResult(status='success' if result.status == 'success' else 'execution_failed', message=result.message), {'kind':'day_plan', 'partial':result.status != 'success'}
            result = self._handle_calendar_query(intent, args['request'])
            evidence = deepcopy(self._last_tool_evidence)
            if evidence and evidence.get('partial') and result.status == 'success':
                result.status = 'execution_failed'
            return result, evidence
        if step.action == 'saved_tasks':
            from therion.agent.contracts import CancellationToken
            from therion.integrations.task_query import render
            from therion.interface.dashboard_data import DashboardSource
            message, speech = render(DashboardSource(self).tasks(CancellationToken()))
            return OrchestrationResult(status='success', message=message, speech_message=speech), {'kind':'tasks', 'read_only':True}
        if step.action == 'mail_important':
            return self._workflow_mail('in:inbox is:important newer_than:1d', 'E-mails importantes de hoje',
                                       'Nenhum e-mail marcado como importante pelo Gmail hoje.')
        if step.action == 'mail_about_events':
            titles = (rows[step.depends_on[0]].evidence or {}).get('titles') or []
            if not titles:
                return OrchestrationResult(status='success', message='Sem compromissos no período, não procurei e-mails.'), None
            parts, spoken = [], []
            for title in titles[:6]:
                clean = title.replace('"', ' ').strip()
                result, _ = self._workflow_mail(f'"{clean}" newer_than:30d', f'Sobre "{title}"',
                                                f'Nenhum e-mail dos últimos 30 dias menciona "{title}".')
                if result.status != 'success':
                    return result, None
                parts.append(result.message)
                spoken.append(result.speech_message)
            return OrchestrationResult(status='success', message='\n\n'.join(parts), speech_message=' '.join(spoken)), None
        if step.action == 'note_search':
            return self._workflow_search(args['query'], scope)
        if step.action in {'note_read', 'note_summary'}:
            evidence = rows[step.depends_on[0]].evidence or {}
            sources = evidence.get('sources', ())
            chosen = args['index']
            chosen = len(sources) if chosen == -1 else chosen
            if not 1 <= chosen <= len(sources):
                return OrchestrationResult(status='execution_failed', message='A busca deste pedido não apresentou essa nota.'), None
            source = sources[chosen-1]
            current_roots = effective_roots(scope, self.second_brain.allowed_roots)
            if source is None or not source.valid(current_roots):
                return OrchestrationResult(status='execution_failed', message='A fonte foi alterada, removida ou perdeu permissão. Faça uma nova busca.'), None
            restricted = NoteResults((source.path,), tuple(_canonical(root) for root in source.roots)).restricted_scope(self.memory.current_task.task_id, current_roots)
            result = self._read_note_result(source.path, step.command, restricted, summarize=step.action == 'note_summary')
            if not source.valid(effective_roots(scope, self.second_brain.allowed_roots)):
                return OrchestrationResult(status='execution_failed', message='A fonte mudou durante a leitura; não usei o resultado.'), None
            return result, {'kind':'note', 'source':source}
        if step.action == 'calendar_create':
            self._pending_event_draft = {'duration_minutes':60}
            self._merge_event_fields(self._pending_event_draft, args['draft'])
            return self._present_calendar_summary(), {'kind':'calendar_proposal'}
        return OrchestrationResult(status='execution_failed', message='Etapa não permitida.'), None

    def _workflow_mail(self, query, heading, empty):
        """Só assunto e remetente (metadados); o corpo do e-mail não é lido nem vai ao modelo."""
        from therion.core.orchestrator import OrchestrationResult
        from therion.agent.contracts import CancellationToken
        try:
            view = self._mailbox.page(query, None, CancellationToken())
        except (OSError, ValueError, TimeoutError) as error:
            return OrchestrationResult(status='execution_failed', message=f'Não consegui consultar o Gmail: {error}'), None
        if view.get('state') != 'ready':
            return OrchestrationResult(status='execution_failed', message=view.get('message') or 'Gmail indisponível.'), None
        items = view.get('items') or []
        if not items:
            return OrchestrationResult(status='success', message=empty, speech_message=empty), None
        sender = lambda item: item['sender'].split('<')[0].strip().strip('"') or item['sender']
        lines = [f'{i}. {item["subject"]} — {sender(item)}' for i, item in enumerate(items[:5], 1)]
        more = f'\n(e mais {len(items) - 5})' if len(items) > 5 else ''
        spoken = f'{heading}: ' + '; '.join(f'"{item["subject"]}", de {sender(item)}' for item in items[:3]) + '.'
        return OrchestrationResult(status='success', message=f'{heading}:\n' + '\n'.join(lines) + more, speech_message=spoken), None

    def _workflow_search(self, query, scope):
        from therion.core.orchestrator import OrchestrationResult
        trace = SearchTrace()
        roots = tuple(_canonical(root) for root in effective_roots(scope, self.second_brain.allowed_roots))
        self._note_results = NoteResults((), ())
        results = self.second_brain.search_notes(query, scope=scope, trace=trace)
        sources = []
        for item in results:
            read = self.second_brain.read_note(item.path, scope=scope)
            sources.append(SourceReference.file(read.canonical_path, read.content or '', roots) if read.success else None)
        self._note_results = NoteResults(tuple(item.path for item in results), roots)
        for root in trace.used_roots:
            relative = self._audit_relative_root(root)
            if relative is not None:
                self.memory.add_used_root(relative)
        evidence = {'kind':'search', 'sources':tuple(sources), 'matches':[{'path':item.path,'snippet':item.snippet} for item in results]}
        self._last_tool_evidence = {'kind':'search', 'term':query, 'matches':evidence['matches']}
        self._language_focus = 'notes'
        message = (f'Encontrei {len(results)} resultado(s) para {query}.' if results else f'Não encontrei resultados para {query} no escopo permitido.')
        message += ''.join(f'\n{i+1}. {item.path}\n{item.snippet}' for i,item in enumerate(results))
        return OrchestrationResult(status='success', message=message, speech_message=f'Encontrei {len(results)} resultado(s) para {query}.'), evidence
