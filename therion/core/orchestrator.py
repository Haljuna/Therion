"""Módulo central de orquestração da V0 com integração à memória de trabalho."""

import os
import re
import unicodedata
import threading
import uuid
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from therion.actions.executor import ActionExecutor
from therion.autonomy.integration import CatalogSupport
from therion.actions.verifier import ActionVerifier
from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.dialogue import event_datetimes, extract_fields, parse_day, parse_time, partition_events, event_start
from therion.config import AliasManager
from therion.context.language import control as language_control, prohibited_action, explicit_user_item, time_correction as interpret_time_correction
from therion.context.note_references import NoteResults, reference_request, selection, named_reference_request, title_candidates
from therion.context.read_scope import ReadScope, effective_roots, _canonical
from therion.context.second_brain import ReadResult, SearchTrace, SecondBrainReader
from therion.context.source_education import formation_context
from therion.context.knowledge_review import KnowledgeReview, review_request
from therion.core.ai_core import AICore
from therion.core.ai_provider import PlanContent, CONTEXT_REQUEST, AIResponse
from therion.context.conversation_frame import ConversationFrame, conversation_turns, personal_request, has_explicit_action, capabilities_request, email_capability_request, current_date_request, current_time_request
from therion.core.personal_context import PersonalContextSupport
from therion.core.intent import Intent, IntentRecognizer, search_term
from therion.core.plan_state import PlanAckResult, PlanSessionState
from therion.core.planner import Plan, Planner
from therion.core.workflow_support import WorkflowSupport
from therion.core.workflow_runtime import render_workflow
from therion.governance.confirmation import ConfirmationHandler
from therion.governance.permissions import PermissionManager
from therion.logging.audit import AuditLogger
from therion.memory.coordinator import MemoryCoordinator
from therion.memory.supervised import MemorySupport, SupervisedMemory
from therion.memory.commands import memory_request
from therion.memory.review import review_preview
from therion.memory.knowledge import MemoryError as KnowledgeError, SourceReference, preview
from therion.memory.working_memory import WorkingMemory
from therion.memory.session_tasks import SessionTasks, task_request, TEMPORARY_NOTICE
from therion.memory.session_recall import context_turns, recall_answer, spoken_recall
from therion.skills.registry import get_skill
from therion.skills.proposals import skill_proposals
from therion.agent.host import AgentSupport


_DURATION_RE = re.compile(
    r'(\d+)\s*(horas?|h|min(?:utos?)?)',
    re.IGNORECASE,
)


def _is_first_message_query(command: str) -> bool:
    """Reconhece consultas à primeira mensagem, sem capturar comandos compostos."""
    normalized = " ".join(command.casefold().split()).rstrip(".!?").strip()
    return re.fullmatch(
        r"qual (?:foi|é|e|era) (?:a|minha|a minha) primeira "
        r"(?:mensagem(?: que (?:eu )?enviei(?: (?:a você|a voce|para você|para voce))?)?"
        r"|coisa que eu te pedi) "
        r"(?:dessa|desta|nessa|nesta|da|na) sess[aã]o",
        normalized,
    ) is not None

_AMBIGUOUS_PREFIX_RE = re.compile(
    r'(?:umas?\s+|mais\s+ou\s+menos\s+|cerca\s+de\s+|aproximadamente\s+)$',
    re.IGNORECASE,
)

_AMBIGUOUS_SUFFIX_RE = re.compile(
    r'^\s*(?:e\s+meia|e\s+quarenta|e\s+um\s+quarto)',
    re.IGNORECASE,
)

_STUDY_SIGNALS = ("estudar", "estudo", "pomodoro")

_AI_INVALID_RESPONSE_STATUS = "ai_invalid_response"
_AI_INVALID_RESPONSE_MESSAGE = "Não consegui interpretar seu pedido com segurança. Pode dizer qual informação ou ação você deseja? Nenhuma ação foi executada."

PLAN_TEXT_MAX_CHARS = 5500
PLAN_TOO_LARGE_MESSAGE = (
    "O plano gerado ficou extenso demais para esta sessão. "
    "Tente pedir um plano mais conciso."
)

# Motivo interno (ClassifyOutcome.failure) → status externo + mensagem não técnica.
_AI_FAILURE_DIAGNOSTICS: dict[str, tuple[str, str]] = {
    "plan_blocks_invalid": (
        "plan_blocks_invalid",
        "O plano não foi exibido porque os blocos de estudo e pausa não respeitam "
        "a distribuição definida. Você pode pedir um novo plano.",
    ),
    "plan_content_invalid": (
        "plan_content_invalid",
        "O plano não foi exibido porque sua estrutura ou o texto de algum bloco "
        "está inválido. Todos os blocos, inclusive pausas, precisam de título e descrição.",
    ),
    "plan_duration_invalid": (
        "plan_duration_invalid",
        "O plano não foi exibido porque os tempos dos blocos estão ausentes, inválidos "
        "ou não somam a duração solicitada. Você pode pedir um novo plano.",
    ),
    "provider_unavailable": (
        "ai_unavailable",
        "O serviço de IA auxiliar está indisponível no momento.",
    ),
    "provider_timeout": (
        "ai_timeout",
        "O serviço de IA auxiliar demorou demais para responder.",
    ),
    "invalid_response": (
        _AI_INVALID_RESPONSE_STATUS,
        _AI_INVALID_RESPONSE_MESSAGE,
    ),
    "rejected_by_policy": (
        _AI_INVALID_RESPONSE_STATUS,
        _AI_INVALID_RESPONSE_MESSAGE,
    ),
}

_PENDING_CLARIFICATION_MAX = 500


def _parse_duration_minutes(text: str) -> Optional[int]:
    """Extrai duração em minutos de um texto V1 (formatos inequívocos)."""
    m = _DURATION_RE.search(text)
    if not m:
        return None

    start, end = m.span()
    unit = m.group(2).lower()

    # Rejeitar se há dígitos imediatamente após a unidade (ex: "1h30")
    if end < len(text) and text[end].isdigit():
        return None

    # Rejeitar se há letras imediatamente após "h" (ex: "1h30")
    if unit == "h" and end < len(text) and text[end].isalpha():
        return None

    # Rejeitar sufixos ambíguos como "e meia" (ex: "2 horas e meia")
    if unit in ("h", "hora", "horas") and end < len(text):
        suffix_match = _AMBIGUOUS_SUFFIX_RE.match(text[end:])
        if suffix_match:
            return None

    # Rejeitar prefixos ambíguos como "umas", "mais ou menos"
    prefix = text[:start]
    if _AMBIGUOUS_PREFIX_RE.search(prefix):
        return None

    value = int(m.group(1))
    if unit in ("h", "hora", "horas"):
        return value * 60
    if unit in ("min", "minuto", "minutos"):
        return value
    return None


def _compute_pomodoro_budget(
    available_minutes: int,
    focus_minutes: int = 25,
    break_minutes: int = 5,
) -> Optional[dict]:
    """Calcula orçamento Pomodoro determinístico. Retorna None se não couber 1 bloco."""
    if available_minutes < focus_minutes:
        return None
    blocks = (available_minutes + break_minutes) // (focus_minutes + break_minutes)
    planned = blocks * focus_minutes + max(0, blocks - 1) * break_minutes
    return {
        "available_minutes": available_minutes,
        "blocks": blocks,
        "focus_minutes": focus_minutes,
        "break_minutes": break_minutes,
        "planned_minutes": planned,
        "remaining_minutes": available_minutes - planned,
    }


def _has_study_signal(text: str) -> bool:
    """Verifica se o texto contém sinal explícito de estudo/Pomodoro V1."""
    lower = text.lower()
    return any(signal in lower for signal in _STUDY_SIGNALS)


def _extract_pomodoro_budget(
    command: str,
    recent_turns: list[dict],
) -> Optional[dict]:
    """Extrai orçamento Pomodoro do command ou do último turno anterior do usuário.

    Regra V1:
    1. Buscar duração no command atual.
    2. Se ausente, usar SOMENTE o último turno anterior do usuário em recent_turns,
       ignorando explicitamente o turno que corresponde ao command atual.
    3. Não percorrer histórico mais profundo.
    4. Gerar budget somente se houver duração + sinal de estudo/Pomodoro.
    """
    duration = _parse_duration_minutes(command)
    if duration is not None and _has_study_signal(command):
        return _compute_pomodoro_budget(duration)

    last_user_turn = None
    for turn in reversed(recent_turns):
        if not isinstance(turn, dict) or turn.get("role") != "user":
            continue
        text = turn.get("text", "")
        if text == command:
            continue
        last_user_turn = text
        break

    if last_user_turn is not None:
        duration = _parse_duration_minutes(last_user_turn)
        if duration is not None and _has_study_signal(last_user_turn):
            return _compute_pomodoro_budget(duration)

    return None


@dataclass
class OrchestrationResult:
    """Resultado de uma etapa do ciclo de orquestração."""

    status: str  # "awaiting_confirmation", "success", "executed_simulated", "cancelled", "unknown_intent", "forbidden", "execution_failed", "verification_failed"
    intent: Optional[Intent] = None
    plan: Optional[Plan] = None
    message: str = ""
    plan_candidate_id: Optional[str] = None
    registered_plan_id: Optional[str] = None
    speech_message: Optional[str] = None
    confirmation_id: Optional[str] = None
    ui_action: Optional[str] = None
    ui_payload: Optional[dict] = None


@dataclass(frozen=True)
class _ScopeSyntax:
    present: bool
    malformed: bool
    reason: str
    command: str
    roots: tuple[str, ...]


@dataclass(frozen=True)
class _ScopeRoots:
    accepted: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]
    invalid: tuple[tuple[str, str], ...]


def _parse_scope_syntax(command: str) -> _ScopeSyntax:
    stripped = command.strip()
    if not stripped.startswith("raízes:"):
        return _ScopeSyntax(False, False, "", command, ())
    rest = stripped[len("raízes:"):]
    if " :: " not in rest:
        return _ScopeSyntax(True, True, "falta o separador ' :: '", command, ())
    left, right = rest.split(" :: ", 1)
    left = left.strip()
    if not left:
        return _ScopeSyntax(True, False, "", right.strip(), ())
    roots = tuple(part.strip() for part in left.split(","))
    if any(not part for part in roots):
        return _ScopeSyntax(True, True, "root vazia na lista", command, ())
    return _ScopeSyntax(True, False, "", right.strip(), roots)


class Orchestrator(WorkflowSupport, MemorySupport, PersonalContextSupport, CatalogSupport, AgentSupport):
    def mailbox_request(self,operation,arguments,token):
        """Leitura da caixa pelo orquestrador; widgets não acessam o provedor."""
        token.check()
        if operation=='status':return self._mailbox.status()
        if operation=='page':return self._mailbox.page(arguments.get('query','in:inbox'),arguments.get('page'),token,force=arguments.get('force') is True)
        if operation=='body':return self._mailbox.body(arguments['id'],token,force=arguments.get('force') is True)
        if operation=='focus':
            self._mailbox.focus_list(arguments['query'],arguments.get('ids',[]),arguments.get('selected'),
                                     visible=arguments.get('visible',True),touch=arguments.get('touch',True))
            return {'state':'ready'}
        if operation=='hide':self._mailbox.hide();return {'state':'ready'}
        raise ValueError('Operação de correio não cadastrada.')

    def dashboard_action(self, operation, arguments, token):
        """Pedidos visuais explícitos usam os mesmos serviços e confirmações."""
        from therion.interface.dashboard_data import dashboard_action
        return dashboard_action(self, operation, arguments, token)

    """Orquestrador do ciclo básico da V0 integrado à memória de trabalho da sessão."""

    def __init__(
        self,
        simulate: bool = False,
        log_dir: Optional[str] = None,
        vault_root: Optional[str] = None,
        calendar_adapter: Optional[CalendarAdapter] = None,
        ai_core: Optional[AICore] = None,
        calendar_time_zone: str = 'America/Sao_Paulo',
        memory_repository=None,
        memory_policy=None,
        memory_source_resolver=None,
        memory_evidence_store=None,
        knowledge_runtime=None,
        user_profile_path=None,
        assistant_identity=None,
        autonomy_runtime=None,
        autonomy_runtime_factory=None,
        agent_config=None,
        agent_state_root=None,
        agent_provider=None,
    ) -> None:
        self._operation_lock = threading.RLock()
        self._init_agent(agent_config, agent_state_root, agent_provider)
        self._session_id = uuid.uuid4().hex
        self._confirmation_id = None
        self._pending_action_plan = None
        self._pending_action_fingerprint = None
        self.simulate = simulate
        self.intent_recognizer = IntentRecognizer()
        self.planner = Planner()
        self.permission_manager = PermissionManager()
        self.confirmation_handler = ConfirmationHandler()
        self.executor = ActionExecutor()
        self.verifier = ActionVerifier()
        self.memory = WorkingMemory()
        self.second_brain = SecondBrainReader(vault_root=vault_root)
        self.audit_logger = AuditLogger(log_dir=log_dir)
        self.alias_manager = AliasManager()
        self._init_autonomy(autonomy_runtime if autonomy_runtime is not None else
            autonomy_runtime_factory() if autonomy_runtime_factory is not None else None)
        self.calendar_adapter = calendar_adapter
        self.ai_core = ai_core
        self.voice_conversation = False
        self._last_tool_evidence = None
        self._note_results = None
        self._note_results_created = None
        self._pending_note_selection = None
        self._search_snapshot = None
        self._pending_search_summary = False
        self._calendar_tz_error = None
        try:
            self._calendar_tz = ZoneInfo(calendar_time_zone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            self._calendar_tz = None
            self._calendar_tz_error = 'Fuso horário configurado inválido ou não suportado. Confira a configuração do calendário.'
        self._now_func = None  # injetável para testes
        # Estado do fluxo conversacional de substituir alias
        self._replace_alias_flow_step: Optional[str] = None
        self._pending_replace_alias: Optional[str] = None
        self._pending_replace_old_target: Optional[str] = None
        self._pending_replace_new_target: Optional[str] = None
        # Estado do fluxo conversacional de adicionar alias
        self._alias_flow_step: Optional[str] = None
        self._pending_alias_keyword: Optional[str] = None
        self._pending_alias_target: Optional[str] = None
        # Estado do fluxo conversacional de excluir alias
        self._delete_alias_flow_step: Optional[str] = None
        self._pending_delete_alias: Optional[str] = None
        # Estado do fluxo de alvo desconhecido
        self._unknown_target_flow_step: Optional[str] = None
        self._pending_unknown_original: Optional[str] = None
        self._pending_unknown_explained: Optional[str] = None
        # Estado do fluxo de criação de evento
        self._pending_event_draft: Optional[dict] = None
        self._calendar_query_context = None
        self._pending_reminder_choice = False
        # Estado do fluxo de abertura contextual (target vago)
        self._open_app_flow_active: bool = False
        self._pending_open_app_target: Optional[str] = None
        self._pending_open_app_result: Optional[Intent] = None
        self._scope_note: str = ""
        self._pending_clarification: Optional[str] = None
        # Estado efêmero de planos da sessão (E1/M5)
        self._plan_state = PlanSessionState()
        self._session_tasks = SessionTasks()
        self._task_turn_ids = set()
        self._language_focus = None
        self._recent_note_index = None
        self._previous_language_focus = None
        self._recent_task_ids = ()
        self._pending_task_reference = None
        self._language_clock = time.monotonic
        self._last_exchange_time = None
        self._last_result_personal = False
        self._conversation_frame = ConversationFrame()
        self._request_deadline = None
        self._format_repair_budget = {'remaining': 1}
        self._init_personal_context(user_profile_path, assistant_identity)
        self.knowledge = MemoryCoordinator(self._session_id, policy=memory_policy,
            clock=lambda: datetime.now(self._calendar_tz or timezone.utc))
        self._knowledge_repository = memory_repository
        self._knowledge_source_resolver = memory_source_resolver
        self._knowledge_read_roots = tuple(self.second_brain.allowed_roots)
        self._selected_memory_id = None
        self._selected_memory_time = None
        self._pending_memory_plan = None
        self._memory_plan_fingerprint = None
        self._supervised_memory = SupervisedMemory(self.knowledge, memory_repository, memory_evidence_store,
            source_resolver=lambda source: self.knowledge._operation_source_valid(source),
            cancelled=lambda: self._workflow_cancel_event.is_set())
        self._init_workflows()
        self._knowledge_review = KnowledgeReview()
        self._knowledge_runtime = knowledge_runtime
        self._knowledge_policy_epoch = 0
        if knowledge_runtime is not None:
            knowledge_runtime.install(self)

    def _sync_knowledge_access(self):
        if self._knowledge_runtime is not None:
            self._knowledge_runtime.synchronize(self)

    def _process_memory_request(self, command, request):
        """Checagem antecipada: não consome confirmação de calendário/app/alias."""
        operation = request['operation']
        if operation in {'list_reviews','show_review','discard_review','classify_review'}:
            try:
                self.second_brain._check_access()
                roots=tuple(self.second_brain.allowed_roots)
                if operation=='list_reviews':
                    rows=self.knowledge.learning_reviews(roots)
                    message=('Revisões de aprendizados (sensibilidade incerta; não são memórias salváveis):\n'
                        +'\n'.join(f'{r.id} — {r.candidate.title}' for r in rows)
                        if rows else 'Não há revisões de aprendizados válidas nesta sessão.')
                elif operation=='show_review':
                    row=next((r for r in self.knowledge.learning_reviews(roots) if r.id==request['identifier']),None)
                    if row is None:raise KnowledgeError('Revisão não encontrada ou vencida. Consulte revisões de aprendizados.')
                    message=review_preview(row)
                elif operation=='classify_review':
                    if self._confirmation_id is not None:
                        raise KnowledgeError('Resolva a confirmação pendente antes de classificar uma revisão.')
                    candidate=self.knowledge.resolve_review(request['identifier'],roots,classify=True)
                    self._selected_memory_id=candidate.id
                    self._selected_memory_time=time.monotonic()
                    message='Classificação de sensibilidade registrada nesta sessão. Ainda não salvei.\n'+preview(candidate,supervised=self._supervised_memory.evidence is not None)
                else:
                    self.knowledge.resolve_review(request['identifier'],roots)
                    message='Revisão descartada; nenhuma nota foi gravada.'
                self.second_brain._check_access()
                return OrchestrationResult(status='success',message=message,confirmation_id=self._confirmation_id)
            except (KnowledgeError,PermissionError,OSError) as error:
                return OrchestrationResult(status='clarification',message=str(error),confirmation_id=self._confirmation_id)
        if operation not in {'status', 'stored'}:
            self._cancel_memory_save()
        try:
            if operation in {'correct', 'retire'}:
                return self._prepare_memory_lifecycle(request)
            elif operation == 'clarify_correction':
                raise KnowledgeError('Informe o ID: "corrija a memória RAS-AAAAMMDD-001: novo conteúdo" ou "desconsidere a memória RAS-AAAAMMDD-001". Nenhuma nota será apagada.')
            elif operation == 'add':
                candidate, state = self.knowledge.explicit(request['text'])
                self._selected_memory_id = candidate.id
                self._selected_memory_time = time.monotonic()
                message = preview(candidate, supervised=self._supervised_memory.evidence is not None)
                if state == 'existing':
                    message = 'Esse candidato já está na lista; não dupliquei.\n' + message
            elif operation in {'revoke_write', 'revoke_access'}:
                if self._knowledge_runtime is None:
                    raise KnowledgeError('Não há política persistente de conhecimento conectada nesta instância.')
                self._knowledge_runtime.revoke(read_all=operation == 'revoke_access')
                self._sync_knowledge_access()
                message = ('Revoguei a gravação de memória na configuração persistente. '
                    + ('A leitura voltou ao escopo padrão do projeto e Sistema da IA. ' if operation == 'revoke_access' else '')
                    + 'Propostas e contexto anteriores foram invalidados. Não apaguei notas.')
            elif operation == 'status':
                message = ('Memória: ' + self.knowledge.policy.mode
                           + ('. Gravação supervisionada mediante confirmação por proposta. ' if self._supervised_memory.evidence is not None
                              else '. Gravação real desativada. ')
                           + 'Limpar apaga candidatos da sessão; não apaga rascunhos persistentes autorizados.')
            elif operation == 'pause':
                self.knowledge.pause()
                self._selected_memory_id = None
                message = 'Pausei a captura e descartei trabalhos pendentes. Não alterei notas existentes.'
            elif operation == 'list':
                self._selected_memory_id = None
                rows = self.knowledge.snapshot()
                message = ('Candidatos de memória desta sessão:\n' + '\n'.join(
                    f'{index}. {item.id} — {item.title}' for index, item in enumerate(rows, 1))
                    if rows else 'Não há candidatos de memória nesta sessão.')
                message += ('\nCandidatos não são registros salvos. Peça salve para preparar uma gravação.'
                    if self._supervised_memory.evidence is not None else '\nAinda não salvei. A gravação real está desativada.')
            elif operation in {'show', 'discard'}:
                selector = request.get('selector')
                rows = self.knowledge.snapshot()
                if operation == 'discard' and not rows:
                    self.knowledge.cancel_pending(discard_candidates=True)
                    return OrchestrationResult(status='success', message='Cancelei candidatos ainda em preparação. Não apaguei notas.', confirmation_id=self._confirmation_id)
                if selector is None:
                    if (self._selected_memory_time is None or time.monotonic()-self._selected_memory_time > 300
                            or self._selected_memory_id is None):
                        raise KnowledgeError('Qual candidato? Indique o identificador ou número da lista.')
                    selector = self._selected_memory_id
                if selector.isdigit():
                    index = int(selector)
                    if not 1 <= index <= len(rows):
                        raise KnowledgeError('Número de candidato inválido.')
                    selector = rows[index-1].id
                item = next((item for item in rows if item.id.casefold() == selector.casefold()), None)
                if item is None:
                    raise KnowledgeError('Candidato não encontrado nesta sessão.')
                if operation == 'show':
                    self._selected_memory_id = item.id
                    self._selected_memory_time = time.monotonic()
                    message = preview(item, supervised=self._supervised_memory.evidence is not None)
                else:
                    self.knowledge.discard(item.id)
                    self._selected_memory_id = None
                    message = 'Descartei o candidato ainda não salvo. Não apaguei notas.'
            elif operation == 'stored':
                if self._supervised_memory.evidence is not None:
                    rows = self._supervised_memory.retrieve('', self._knowledge_read_roots)
                    message = ('Rascunhos válidos recuperados (até três):\n'
                        + '\n'.join(row['content'] for row in rows) if rows else
                        'Nenhum rascunho válido recuperado no escopo e política atuais.')
                else:
                    message = 'Não salvei memórias no cofre nesta fase. A gravação real está desativada.'
            elif operation == 'save':
                if self._supervised_memory.evidence is not None and self._knowledge_repository is not None:
                    return self._prepare_memory_save()
                message = 'Ainda não salvei. A gravação real está desativada; posso apenas preparar prévias.'
            elif operation == 'forget':
                message = ('Não apaguei nenhuma nota. Informe qual registro e a alteração desejada '
                           'para preparar uma proposta de descarte separada; exclusão não está habilitada nesta fase.')
            elif operation == 'ambiguous':
                raise KnowledgeError('Você quer guardar uma informação na memória ou criar um lembrete no calendário?')
            else:
                raise KnowledgeError('Qual informação você quer que eu lembre? Escreva o conteúdo explicitamente; não vou presumir um aprendizado da minha resposta.')
            result = OrchestrationResult(status='success', message=message,
                speech_message='Ainda não salvei; preparei uma prévia.' if operation in {'add', 'show'} else message)
        except KnowledgeError as error:
            result = OrchestrationResult(status='clarification', message=str(error), speech_message=str(error))
        # Não copiar possíveis segredos nem prévias para o contexto probabilístico ou a auditoria em disco.
        self.memory.add_turn('user', 'Pedido de memória: ' + operation, origin='memory_preview')
        self.memory.add_turn('therion', result.message, origin='memory_preview')
        result.confirmation_id = self._confirmation_id
        return result

    def memory_notifications(self):
        ids = self.knowledge.notifications()
        reviews=self.knowledge.review_notifications()
        rows=[]
        if ids:
            rows.append('Preparei ' + str(len(ids)) + ' candidato(s) de aprendizado. Ainda não salvei. '
                'Peça “o que você pretende guardar?” para revisar.')
        if reviews:
            rows.append(f'{len(reviews)} aprendizado(s) útil(is) exige(m) revisão de sensibilidade. '
                'Não são candidatos salváveis. Peça “revisões de aprendizados”. Nada foi salvo.')
        return '\n'.join(rows)

    def close(self):
        self.close_agent()
        self._cancel_memory_save()
        self.cancel_workflow()
        self._workflows.clear()
        self.knowledge.close()

    def _complete_task(self) -> None:
        """Conclui a tarefa na memória de trabalho e audita o registro."""
        if self.memory.current_task:
            try:
                task = self.memory.current_task
                # Auditoria operacional não é um segundo histórico sem retenção.
                # O transcript opcional fica exclusivamente no SessionStore.
                task = replace(task, command='[Conteúdo da conversa omitido da auditoria]',
                    target=None,plan_steps=[],execution_result=None,verification_result=None,
                    error=None,context_queries=[{'path':query.get('path'),'success':query.get('success'),'error':None}
                        for query in task.context_queries])
                self.audit_logger.log_task(task)
            except Exception as err:
                import sys
                sys.stderr.write(f"[AVISO] Falha ao registrar log de auditoria: {err}\n")
            self.memory.complete_task()

    def read_context(
        self, path: str, scope: Optional[ReadScope] = None
    ) -> ReadResult:
        """Lê seletivamente uma nota autorizada do Segundo Cérebro e registra na memória."""
        result = self.second_brain.read_note(path, scope=scope)
        self.memory.record_context_query(
            path=path,
            success=result.success,
            error=result.error,
        )
        return result

    def _handle_session_tasks(self, request):
        self.memory.record_intent('tarefas da sessão', None)
        operation = request['operation']
        self._language_focus = 'tasks'
        self._recent_task_ids = ()
        try:
            if operation == 'add':
                items = self._session_tasks.add(request['text'])
                heading = f'Adicionei {len(items)} tarefa(s) à lista desta sessão.'
            elif operation in {'complete', 'reopen'}:
                item = self._session_tasks.update(request['id'], operation == 'complete')
                items = (item,)
                heading = f"Tarefa {item.id} {'concluída' if item.completed else 'reaberta'} na lista desta sessão."
            elif operation == 'show':
                items = tuple(item for item in self._session_tasks.list() if item.id == int(request['id']))
                heading = 'Tarefa selecionada:'
            else:
                items = self._session_tasks.list(request['filter'])
                heading = 'Tarefas desta sessão:' if items else 'Não há tarefas nesse filtro da lista desta sessão.'
            self._recent_task_ids = tuple(item.id for item in items)
            lines = [f"{item.id}. [{'concluída' if item.completed else 'pendente'}] {item.description}" for item in items]
            message = heading + ('\n' + '\n'.join(lines) if lines else '') + '\n\n' + TEMPORARY_NOTICE
            spoken = heading + (' ' + ' '.join(f'{item.id}: {item.description}.' for item in items[:5]) if items else '')
            if len(items) > 5:
                spoken += ' A lista completa está no chat.'
            return OrchestrationResult(status='success', message=message, speech_message=spoken + ' Esta lista é temporária.')
        except ValueError as error:
            return OrchestrationResult(status='clarification', message=str(error) + '\n\n' + TEMPORARY_NOTICE)

    def _read_note_result(self, path, command, scope, *, summarize=False, raw=False):
        self._pending_search_summary = False
        read = self.read_context(path, scope)
        if not read.success:
            return OrchestrationResult(status="execution_failed", message=read.error)
        if read.matched_root is not None:
            used_root = self._audit_relative_root(read.matched_root)
            if used_root is not None:
                self.memory.add_used_root(used_root)
        content = read.content or ''
        evidence = {'kind': 'note', 'path': path, 'content': content[:5000],
                    'partial': len(content) > 5000, 'formation_context': formation_context(content)}
        fallback = ('Não consegui gerar um resumo. Mostrei o conteúdo da nota abaixo.' if summarize else
                    'Li a nota no Segundo Cérebro. Posso resumir ou explicar o conteúdo para você.')
        if raw:
            self._last_tool_evidence = evidence
            summary = 'Aqui está o texto original da nota solicitada.'
        else:
            summary = self._describe_read_result(command, evidence, fallback)
        try:
            self.second_brain._check_access()
        except PermissionError:
            self._last_tool_evidence = None
            return OrchestrationResult(status='cancelled', message='A política de leitura mudou durante a consulta. Não exibi o conteúdo.')
        provider = getattr(self.ai_core, '_provider', None) if self.ai_core else None
        if len(content) >= 80 and re.search(r'(?i)\b(?:procedimento|limitaç[ãa]o|erro recorrente|aprendizado)\b', content):
            try:
                source = SourceReference.file(read.canonical_path, content,
                    effective_roots(scope, self.second_brain.allowed_roots))
                self.knowledge.offer_verified(source, provider,
                    effective_roots(scope, self.second_brain.allowed_roots), reusable=True)
            except (KnowledgeError, OSError, TypeError):
                pass
        partial = '\nConteúdo parcial para o resumo: somente os primeiros 5.000 caracteres.' if evidence['partial'] and not raw else ''
        return OrchestrationResult(status='success',
            message=f"{summary}\n\nFonte: {path}{partial}"
                + (f'\n\n{content}' if raw or summary == fallback else ''),
            speech_message=summary + (' O resumo considera somente parte da nota.' if evidence['partial'] and not raw else ''))

    def _handle_search_followup(self, command, scope):
        control = language_control(command)
        explicit = control in {'resuma os trechos disponiveis', 'resuma os resultados',
                               'resuma os trechos encontrados', 'resuma esses resultados'}
        accepted = control in {'sim', 'pode resumir', 'sim pode resumir'} and self._pending_search_summary
        if not explicit and not accepted:
            return None
        self._pending_search_summary = False
        if self._search_snapshot is None:
            return OrchestrationResult(status='clarification', message='Faça uma busca antes de pedir o resumo dos resultados.')
        evidence, results, created = self._search_snapshot
        if self._language_clock() - created > 300:
            self._search_snapshot = None
            return OrchestrationResult(status='clarification', message='A busca anterior venceu. Busque novamente antes de resumir.')
        restricted = results.restricted_scope(self.memory.current_task.task_id,
                                             effective_roots(scope, self.second_brain.allowed_roots))
        sources = []
        try:
            for match in evidence['matches']:
                read = self.read_context(match['path'], restricted)
                if not read.success:
                    raise KnowledgeError('Uma fonte não está mais disponível no escopo atual.')
                source = SourceReference.file(read.canonical_path, read.content, restricted.roots)
                if match.get('version') and source.version != match['version']:
                    raise KnowledgeError('Uma fonte mudou desde a busca. Busque novamente para resumir a versão atual.')
                sources.append(source)
            fallback = 'Trechos da busca (conteúdo parcial):\n' + '\n'.join(
                f'{i}. {match["snippet"]}' for i, match in enumerate(evidence['matches'], 1))
            summary = self._describe_read_result('Resuma os trechos disponíveis da busca.', evidence, fallback)
            self.second_brain._check_access()
            if self._workflow_cancel_event.is_set() or any(not source.valid(
                    effective_roots(scope, self.second_brain.allowed_roots)) for source in sources):
                raise KnowledgeError('A fonte ou o acesso mudou durante o resumo.')
        except (KnowledgeError, OSError, ValueError, PermissionError) as error:
            self._search_snapshot = None
            self._last_tool_evidence = None
            return OrchestrationResult(status='cancelled', message=str(error))
        self._language_focus = 'notes'
        return OrchestrationResult(status='success', message=summary+'\n\nResumo dos trechos; não é leitura integral das notas.',
                                   speech_message=summary)

    def _handle_note_reference(self, command, scope):
        request = reference_request(command)
        named = named_reference_request(command) if request is None else None
        if named is not None:
            if (self._note_results is None or self._note_results_created is None
                    or self._language_clock() - self._note_results_created > 300):
                return OrchestrationResult(status='clarification', message=(
                    'Faça uma busca ou selecione as notas novamente para eu identificar esse título.'))
            operation, title = named
            matches = title_candidates(title, self._note_results.paths)
            if len(matches) != 1:
                self._pending_note_selection = operation
                self._language_focus = 'notes'
                return OrchestrationResult(status='clarification', message=(
                    'Não identifiquei uma única nota por esse título. Qual número dos resultados você quer?'))
            request = (operation, matches[0], 'note')
        if request is None and self._previous_language_focus == 'notes' and selection(command) is not None:
            request = ('read', selection(command), 'note')
        if request is not None and self._note_results is None and not request[2] and command.casefold().startswith(('abra ', 'abre ', 'abrir ')):
            return None
        if request is not None and request[1] is None and self._previous_language_focus != 'notes' and self._pending_note_selection is None:
            self._pending_note_selection = request[0]
            self._language_focus = 'notes'
            return OrchestrationResult(status='clarification', message='Você se refere a uma nota da última busca? Indique o número da nota.')
        if request is None and self._pending_note_selection is not None:
            index = selection(command)
            if index is not None:
                request = (self._pending_note_selection, index, 'note')
        self._pending_note_selection = None
        if request is None:
            return None
        operation, index, explicit = request
        if index is None and self._previous_language_focus == 'notes' and self._recent_note_index is not None:
            index = self._recent_note_index
        if self._note_results is None:
            if not explicit and index is None and command.casefold().startswith(('abra ', 'abre ', 'abrir ')):
                return None
            return OrchestrationResult(status='clarification', message='Faça uma busca no Segundo Cérebro antes de selecionar uma nota.')
        if explicit != 'note' and (self._last_tool_evidence or {}).get('kind') not in {'search', 'note'}:
            self._pending_note_selection = operation
            self._language_focus = 'notes'
            return OrchestrationResult(status='clarification', message='Você se refere a uma nota da última busca? Indique o número da nota.')
        paths = self._note_results.paths
        if not paths:
            return OrchestrationResult(status='clarification', message='A última busca não apresentou notas. Faça outra busca.')
        if index is None and len(paths) == 1:
            index = 1
        if index == -1:
            index = len(paths)
        if index is None or not 1 <= index <= len(paths):
            self._pending_note_selection = operation
            self._language_focus = 'notes'
            return OrchestrationResult(status='clarification', message=f'Qual nota da última busca? Escolha um número de 1 a {len(paths)}.')
        restricted = self._note_results.restricted_scope(self.memory.current_task.task_id,
            effective_roots(scope, self.second_brain.allowed_roots))
        roots = [self._audit_relative_root(root) for root in restricted.roots]
        task = self.memory.current_task
        self.memory.record_read_scope(task.declared_roots, task.accepted_roots, roots, [])
        self._language_focus = 'notes'
        result = self._read_note_result(paths[index-1], 'Resuma esta nota selecionada da última busca.' if operation == 'summary' else command, restricted,
            summarize=operation == 'summary', raw=operation == 'raw')
        self._recent_note_index = index if result.status == 'success' else None
        return result

    def _audit_relative_root(self, root: str) -> Optional[str]:
        """Converte uma root absoluta validada para forma relativa ao vault."""
        if not os.path.isabs(root):
            return None
        vault = os.path.normcase(
            os.path.abspath(os.path.realpath(self.second_brain.vault_root))
        )
        canonical = os.path.normcase(os.path.abspath(os.path.realpath(root)))
        try:
            if os.path.commonpath([vault, canonical]) != vault:
                return None
        except ValueError:
            return None
        return os.path.relpath(canonical, vault).replace("\\", "/")

    def _resolve_scope_roots(self, roots: tuple[str, ...]) -> _ScopeRoots:
        if not roots:
            return _ScopeRoots((), (), ())
        vault_root = self.second_brain.vault_root
        vault_canon = os.path.normcase(os.path.abspath(os.path.realpath(vault_root)))
        allowed_canon = [
            os.path.normcase(os.path.abspath(os.path.realpath(root)))
            for root in self.second_brain.allowed_roots
        ]
        accepted: list[str] = []
        rejected: list[tuple[str, str]] = []
        invalid: list[tuple[str, str]] = []
        for root in roots:
            if os.path.isabs(root):
                invalid.append((root, "caminho absoluto"))
                continue
            if os.path.splitdrive(root)[0]:
                invalid.append((root, "drive-relative"))
                continue
            segments = root.replace("/", "\\").split("\\")
            if any(segment == ".." for segment in segments):
                invalid.append((root, "segmento '..'"))
                continue
            joined = os.path.normpath(os.path.join(vault_root, root))
            canon = os.path.normcase(os.path.abspath(os.path.realpath(joined)))
            if canon != vault_canon and not canon.startswith(vault_canon + os.sep):
                rejected.append((root, "fora do vault"))
                continue
            within_ceiling = any(
                canon == allowed or canon.startswith(allowed + os.sep)
                for allowed in allowed_canon
            )
            if not within_ceiling:
                rejected.append((root, "fora do teto permitido"))
                continue
            accepted.append(canon)
        return _ScopeRoots(tuple(accepted), tuple(rejected), tuple(invalid))

    def _reset_alias_flow(self) -> None:
        """Limpa o estado do fluxo de adicionar alias."""
        self._alias_flow_step = None
        self._pending_alias_keyword = None
        self._pending_alias_target = None

    def _reset_delete_alias_flow(self) -> None:
        """Limpa o estado do fluxo de excluir alias."""
        self._delete_alias_flow_step = None
        self._pending_delete_alias = None

    def _reset_replace_alias_flow(self) -> None:
        """Limpa o estado do fluxo de substituir alias."""
        self._replace_alias_flow_step = None
        self._pending_replace_alias = None
        self._pending_replace_old_target = None
        self._pending_replace_new_target = None

    def _reset_unknown_target_flow(self) -> None:
        """Limpa o estado do fluxo de alvo desconhecido."""
        self._unknown_target_flow_step = None
        self._pending_unknown_original = None
        self._pending_unknown_explained = None

    def _reset_calendar_create_flow(self) -> None:
        """Limpa o estado do fluxo de criação de evento."""
        self._pending_event_draft = None
        self._pending_reminder_choice = False

    @staticmethod
    def _calendar_control(command: str) -> str:
        text = ''.join(char for char in unicodedata.normalize('NFD', command.casefold())
                       if not unicodedata.combining(char))
        return ' '.join(text.split()).rstrip('.!?').strip()

    def _handle_reminder_flow(self, command: str) -> Optional[OrchestrationResult]:
        control = self._calendar_control(command)
        reminder_request = bool(re.search(r'\blembrete\b', control) and re.match(
            r'^(?:(?:therion|na verdade)[, ]+)?(?:eu )?(?:quero|queria|preciso|pode|adicione|adicionar|crie|cria|criar|marque|marcar|agende|agendar)\b',
            control))
        if reminder_request:
            self._reset_calendar_create_flow()
            self._pending_reminder_choice = True
        elif not self._pending_reminder_choice:
            return None
        elif control in {'n', 'nao', 'cancelar', 'cancele', 'cancela'}:
            self._reset_calendar_create_flow()
            return OrchestrationResult(status='cancelled', message='Cancelei o pedido de lembrete.')
        elif control in {'compromisso', 'evento', 'novo compromisso', 'um novo compromisso',
                         'outro compromisso', 'novo evento', 'um novo evento'}:
            self._reset_calendar_create_flow()
            self._pending_event_draft = {'duration_minutes': 60}
            return OrchestrationResult(status='awaiting_confirmation', message='Qual é o título do novo compromisso?')
        elif re.fullmatch(r'(?:adicionar )?(?:um |o )?(?:aviso|alerta)(?: (?:a|de|em|no|para) (?:um )?evento(?: existente)?)?', control):
            self._reset_calendar_create_flow()
            return OrchestrationResult(status='success', message=(
                'Ainda não consigo configurar avisos de eventos existentes. '
                'Posso criar um novo compromisso, se você quiser.'))
        elif self.intent_recognizer.parse(command) is not None:
            self._reset_calendar_create_flow()
            return None
        return OrchestrationResult(status='awaiting_confirmation', message=(
            'Você quer criar um novo compromisso ou adicionar um aviso a um evento existente?'))

    def _reset_open_app_flow(self) -> None:
        """Limpa o estado do fluxo de abertura contextual."""
        self._open_app_flow_active = False
        self._pending_open_app_target = None
        self._pending_open_app_result = None

    def _set_pending_clarification(self, question: str) -> None:
        """Armazena a pergunta de clarification pendente, limitada a 500 caracteres."""
        cleaned = question.strip()
        self._pending_clarification = cleaned[:_PENDING_CLARIFICATION_MAX]

    @property
    def session_id(self):
        return self._session_id

    @property
    def confirmation_id(self):
        return self._confirmation_id

    @staticmethod
    def _plan_fingerprint(plan):
        intent = plan.intent
        return (intent.action, intent.target, intent.raw_command, intent.requires_confirmation, tuple(plan.steps),bool((intent.entities or {}).get('new_window')))

    @staticmethod
    def _stale_confirmation():
        return OrchestrationResult(status='cancelled', message=(
            'Essa proposta foi alterada, encerrada ou já recebeu uma resposta. '
            'Nenhuma nova ação foi executada.'))

    def process_session_command(self, command, session_id, confirmation_id, cancelled=None, presentation=None):
        """Entrada do worker: valida o contexto capturado antes de processar."""
        with self._operation_lock:
            self._sync_knowledge_access()
            if ((cancelled is not None and cancelled.is_set())
                    or session_id != self._session_id or confirmation_id != self._confirmation_id):
                return self._stale_confirmation()
            self._workflow_cancel_event=cancelled if cancelled is not None else threading.Event()
            navigation=self._mail_navigation(command,cancelled,presentation)
            if navigation is not None:return navigation
            agent_result = self._dispatch_agent(command, cancelled)
            if agent_result is not None:
                return agent_result
            confirmation=self._confirmation_id
            self._agent_begin_legacy(confirmation)
            try:result = self._process_command(command, cancelled=cancelled)
            except BaseException:
                self._agent_finish_legacy(confirmation);raise
            self._agent_finish_legacy(confirmation,result)
            self._record_legacy_history(command, result)
            return result

    def confirm_session_proposal(self, plan, confirmed, session_id, confirmation_id, cancelled=None):
        with self._operation_lock:
            self._sync_knowledge_access()
            if ((cancelled is not None and cancelled.is_set())
                    or session_id != self._session_id or confirmation_id != self._confirmation_id):
                return self._stale_confirmation()
            self._workflow_cancel_event = cancelled if cancelled is not None else threading.Event()
            return self.confirm_and_execute(plan, confirmed)

    def clear_session(self) -> None:
        self.cancel_agent()
        self.cancel_workflow()
        with self._operation_lock:
            self._session_id = uuid.uuid4().hex
            self._confirmation_id = None
            self._pending_action_plan = None
            self._pending_action_fingerprint = None
            self._clear_session()

    def _clear_session(self) -> None:
        self._agent_turn_sources.clear()
        self._agent_waiting_for_answer=False
        self._agent_legacy_pending.clear()
        if self._agent_proposals:self._agent_proposals.clear()
        self._pending_catalog_app = None
        self._pending_catalog_decision = None
        self._clear_personal_context()
        self._conversation_frame.clear()
        self._last_result_personal = False
        self._cancel_memory_save()
        self._workflows.clear()
        """Encerra a sessão volátil, inclusive tarefas e fluxos intermediários."""
        self._pending_clarification = None
        self._last_tool_evidence = None
        self._note_results = None
        self._note_results_created = None
        self._pending_note_selection = None
        self.memory.clear_session()
        self._search_snapshot = None
        self._pending_search_summary = False
        self.memory.clear()
        self._plan_state.clear_session()
        self._session_tasks.clear()
        self.knowledge.reset(self._session_id)
        self._supervised_memory.corrections.clear()
        self._supervised_memory.corrections_overflow = False
        self._supervised_memory.committed_candidates.clear()
        self._knowledge_review.clear()
        self._selected_memory_id = None
        self._selected_memory_time = None
        self._task_turn_ids.clear()
        self._language_focus = None
        self._recent_note_index = None
        self._previous_language_focus = None
        self._recent_task_ids = ()
        self._pending_task_reference = None
        self._last_exchange_time = None
        self._reset_alias_flow()
        self._reset_delete_alias_flow()
        self._reset_replace_alias_flow()
        self._reset_unknown_target_flow()
        self._reset_calendar_create_flow()
        self._reset_open_app_flow()

    def _parse_event_datetimes(self, draft: dict) -> tuple[datetime, datetime]:
        """Converte data/hora do rascunho em datetimes timezone-aware.

        Returns:
            Tupla (start, end) com fuso horário configurado.

        Raises:
            CalendarError: Se data ou hora não puderem ser interpretadas.
        """
        resolved = dict(draft)
        if draft.get('_resolved_date'):
            resolved['date'] = draft['_resolved_date']
        return event_datetimes(resolved, self._calendar_now())

    def _calendar_now(self):
        if self._calendar_tz_error:
            raise CalendarError(self._calendar_tz_error)
        tz = self._calendar_tz or ZoneInfo('America/Sao_Paulo')
        now = self._now_func() if self._now_func else datetime.now(tz)
        return now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)

    def _format_calendar_event(self, event, index: int) -> str:
        """Formata um evento de calendário para exibição."""
        if event.all_day:
            time_str = "Dia inteiro"
        else:
            start = event_start(event, self._calendar_now().tzinfo)
            time_str = f"{start.hour:02d}:{start.minute:02d}"
        return f"{index}. {event.summary} — {time_str}"

    def _handle_calendar_today(self, intent: Intent) -> OrchestrationResult:
        """Processa consulta de eventos de hoje (somente leitura, sem confirmação)."""
        return self._handle_calendar_query(intent, {'date': 'hoje', 'days': 1})

    def _calendar_followup_request(self, command):
        context = self._calendar_query_context
        if (not context or context[0] != self.session_id or
                self._language_clock() - context[1] > 300 or not self._personal_flow_is_free()):
            return None
        candidate = re.sub(r'^(?:e quanto a|e para|e)\s+', '', language_control(command))
        if (len(context)>2 and re.fullmatch(r'qual (?:e )?(?:o )?compromisso|quais (?:sao )?(?:os )?compromissos',candidate)):
            return dict(context[2])
        try:
            parse_day(candidate, self._calendar_now())
        except CalendarError:
            return None
        return {'date': candidate, 'days': 1}

    def _handle_calendar_query(self, intent, request):
        if self.calendar_adapter is None:
            return OrchestrationResult(
                status="success",
                intent=intent,
                message="Calendário não disponível.",
            )
        try:
            now = self._calendar_now()
            first_day = parse_day(request.get('date', 'hoje'), now)
        except CalendarError as err:
            return OrchestrationResult(status='execution_failed', message=str(err))
        days = min(7, max(1, request.get('days', 1)))
        if request.get('week'):
            days = 7 - first_day.weekday()
        events, failed, seen = [], [], set()
        for offset in range(days):
            day = first_day + timedelta(days=offset)
            try:
                retrieved = self.calendar_adapter.list_events_for_day(day)
            except Exception:
                failed.append(day.isoformat())
                continue
            for event in retrieved:
                identity = event.event_id or (event.summary, str(event.start), str(event.end))
                if identity not in seen:
                    seen.add(identity)
                    events.append(event)
        if len(failed) == days:
            self._offer_verified_memory_result('calendar_query_failed')
            self._last_tool_evidence = {'kind': 'calendar', 'events': [], 'failed_days': failed, 'partial': True}
            return OrchestrationResult(status='execution_failed', message='Erro ao acessar calendário. Não consegui consultar esse período. Não posso dizer que esses dias estão livres.')
        events.sort(key=lambda event: (event_start(event, now.tzinfo), event.summary, event.event_id))
        label = 'hoje' if first_day == now.date() and days == 1 else first_day.strftime('%d/%m/%Y')
        if days > 1:
            label = f"{label} a {(first_day + timedelta(days=days-1)).strftime('%d/%m/%Y')}"
        lines = [self._format_calendar_event(evt, i + 1) for i, evt in enumerate(events)]
        if days > 1:
            lines = [f"{event_start(evt, now.tzinfo).strftime('%d/%m/%Y')} — {line}" for evt, line in zip(events, lines)]
        if request.get('next'):
            parts = partition_events(events, now)
            lines = [f'Em andamento: {event.summary}' for event in parts['ongoing']]
            if parts['future']:
                upcoming = parts['future'][0]
                lines.append(f"Próximo compromisso: {upcoming.summary} — {event_start(upcoming, now.tzinfo).strftime('%d/%m/%Y %H:%M')}")
            else:
                lines.append('Não encontrei compromisso futuro com horário nos dias consultados.')
            lines.extend(f'Dia inteiro: {event.summary} — {event.start}' for event in parts['all_day'])
        elif not lines:
            lines = [f'Nenhum compromisso para {label}.']
        if failed:
            lines.append('Consulta parcial. Dias não consultados: ' + ', '.join(failed) + '. Não sei se estão livres; o próximo compromisso pode estar em um desses dias.')
        evidence = {'kind': 'calendar', 'date': first_day.isoformat(), 'days': days,
                    'events': lines[:20], 'titles': [evt.summary for evt in events][:20],
                    'failed_days': failed, 'partial': bool(failed) or len(lines) > 20}
        from therion.calendar.spoken import plural_compromissos, spoken_agenda
        fallback = (' '.join(lines) if request.get('next') or failed or not events else
                    f'Consultei seu calendário e encontrei {plural_compromissos(len(events))} para {label}.')
        self._last_tool_evidence = evidence
        self._calendar_query_context = (self.session_id, self._language_clock(),
                                        dict(request,date=first_day.strftime('%d/%m/%Y'),days=days))
        summary = fallback
        # Uma interpretação do modelo não pode ocultar falhas de cobertura.
        if failed and 'Dias não consultados:' not in summary:
            summary += ' Consulta parcial; há dias não consultados, que podem conter compromissos.'
        if request.get('next') or failed:
            speech = summary
        else:
            # A voz diz os compromissos; antes falava só a contagem e a lista ficava muda.
            speech = spoken_agenda(
                [(event_start(evt, now.tzinfo).date(), evt.summary,
                  None if evt.all_day else (event_start(evt, now.tzinfo).hour, event_start(evt, now.tzinfo).minute))
                 for evt in events], first_day, days, now.date())
        message = summary if not events and not request.get('next') and not failed else (
            summary + f"\n\nEventos de {label}:\n" + "\n".join(lines))
        return OrchestrationResult(
            status="success",
            intent=intent,
            message=message,
            speech_message=speech,
        )

    def _offer_verified_memory_result(self, code):
        # Falha da memória não pode alterar o resultado da operação principal.
        try:
            provider = getattr(self.ai_core, '_provider', None) if self.ai_core else None
            self.knowledge.observe_result(code, provider)
        except Exception:
            pass

    def _finalize_session_result(self, result: OrchestrationResult, *, session_recall: bool = False) -> None:
        """Registra turno do Therion e atualiza contexto operacional na sessão."""
        self._last_exchange_time = self._language_clock()
        self._confirmation_id = uuid.uuid4().hex if result.status == 'awaiting_confirmation' else None
        result.confirmation_id = self._confirmation_id
        if result.speech_message is None and result.plan is not None:
            intent = result.plan.intent
            if intent.action == 'abrir aplicativo':
                spoken_results = {
                    'awaiting_confirmation': (
                        f"Posso abrir o {intent.target}?"
                        if not self.simulate else
                        f"Posso simular a abertura do {intent.target}? O aplicativo não será aberto de verdade."
                    ),
                    'cancelled': 'Cancelei. Não executei a ação.',
                    'executed_simulated': f"Simulei a abertura do {intent.target}. Não abri o aplicativo de verdade.",
                    'success': f"Abri o {intent.target} e confirmei que o processo iniciou.",
                    'execution_failed': f"Não consegui abrir o {intent.target}. Os detalhes do erro estão na tela.",
                    'verification_failed': f"Tentei abrir o {intent.target}, mas não consegui confirmar se o processo iniciou.",
                }
                result.speech_message = spoken_results.get(result.status)
        if self._scope_note:
            if result.message:
                result.message = f"{result.message}\n\n{self._scope_note}"
            else:
                result.message = self._scope_note
            if result.speech_message:
                result.speech_message += f" {self._scope_note}"
        if not self.memory.add_turn(
            "therion", result.message,
            origin="session_recall" if session_recall else "personal_context" if self._personal_reply_active else "original",
        ):
            result.message += (
                "\n\nEsta resposta não foi registrada na memória: limite da sessão atingido. "
                "Use Limpar conversa para iniciar outra sessão."
            )
            if result.speech_message:
                result.speech_message += ' Esta resposta não ficou na memória porque a sessão atingiu o limite.'
        self.memory.last_result = result.message
        self.memory.last_status = result.status
        self._last_result_personal = self._personal_reply_active
        command = getattr(self.memory.current_task, 'command', '')
        self._conversation_frame.finish(command, result.message, self._language_clock(),
            protected=result.plan is not None or result.confirmation_id is not None,
            clarification=self._pending_clarification is not None)
        if result.intent is not None:
            self.memory.last_intent = result.intent.action
            self.memory.last_target = result.intent.target
        self._scope_note = ""

    def _describe_read_result(self, command: str, evidence: dict, fallback: str) -> str:
        self._last_tool_evidence = evidence
        if self.ai_core is None:
            return fallback
        text = self.ai_core.describe_result(command, evidence, self._build_ai_context(command))
        return text if isinstance(text, str) and text.strip() and len(text) <= 1400 else fallback

    def _handle_replace_alias_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo conversacional de substituir alias.
        
        Retorna OrchestrationResult se está no fluxo, None caso contrário.
        """
        cleaned = command.strip()
        
        # Etapa 1: Iniciar fluxo - pedir qual alias substituir
        if self._replace_alias_flow_step is None:
            return None
        
        # Etapa 2: Aguardando alias para substituir
        if self._replace_alias_flow_step == "awaiting_alias":
            alias = cleaned
            if not alias:
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Normaliza a palavra-chave (lowercase, strip)
            alias = alias.strip().lower()
            if not alias:
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Verifica se existe
            aliases = self.alias_manager.list_aliases()
            if alias not in aliases:
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message=f"Alias '{alias}' não encontrado. Nenhum alias foi alterado.",
                )
            # Encontrou - mostra o alvo atual e pergunta o novo alvo
            old_target = aliases[alias]
            self._pending_replace_alias = alias
            self._pending_replace_old_target = old_target
            self._replace_alias_flow_step = "awaiting_new_target"
            return OrchestrationResult(
                status="awaiting_confirmation",
                message=(
                    f"Atualmente:\n"
                    f"'{alias}' → '{old_target}'\n\n"
                    f"Qual deve ser o novo alvo?"
                ),
            )
        
        # Etapa 3: Aguardando novo alvo
        if self._replace_alias_flow_step == "awaiting_new_target":
            new_target = cleaned
            if not new_target:
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alvo não pode ser vazio. Operação cancelada.",
                )
            # Valida se o novo alvo é permitido pela arquitetura (mesmo mecanismo do adicionar)
            allowed_targets = self.permission_manager.ALLOWED_TARGETS
            if new_target not in allowed_targets:
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="forbidden",
                    message=f"Alvo '{new_target}' não é um aplicativo autorizado. Apenas alvos permitidos podem ter aliases.",
                )
            self._pending_replace_new_target = new_target
            self._replace_alias_flow_step = "awaiting_confirmation"
            alias = self._pending_replace_alias
            old_target = self._pending_replace_old_target
            return OrchestrationResult(
                status="awaiting_confirmation",
                message=(
                    f"Confirmar substituição:\n"
                    f"'{alias}'\n"
                    f"'{old_target}' → '{new_target}'?\n"
                    f"Responda 'sim' para confirmar ou 'não' para cancelar."
                ),
            )
        
        # Etapa 4: Aguardando confirmação
        if self._replace_alias_flow_step == "awaiting_confirmation":
            confirmation = self.confirmation_handler.evaluate_response(cleaned)
            if confirmation is True:
                # Confirmação positiva - substitui o alias
                alias = self._pending_replace_alias
                new_target = self._pending_replace_new_target
                self._reset_replace_alias_flow()
                try:
                    result = self.alias_manager.replace_alias(alias, new_target, confirm=True)
                except Exception:
                    return self._uncertain_alias_write()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Atualizei o alias com sucesso.",
                    )
                else:
                    return OrchestrationResult(
                        status="execution_failed",
                        message=f"Falha ao substituir alias: {result.message}",
                    )
            elif confirmation is False:
                # Confirmação negativa - cancela
                self._reset_replace_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Operação cancelada pelo usuário.",
                )
            else:
                # Resposta ambígua - pede novamente
                alias = self._pending_replace_alias
                old_target = self._pending_replace_old_target
                new_target = self._pending_replace_new_target
                return OrchestrationResult(
                    status="awaiting_confirmation",
                    message=(
                        f"Resposta não reconhecida. "
                        f"Confirmar substituição:\n"
                        f"'{alias}'\n"
                        f"'{old_target}' → '{new_target}'?\n"
                        f"Responda 'sim' para confirmar ou 'não' para cancelar."
                    ),
                )
        
        return None

    def _handle_delete_alias_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo conversacional de excluir alias.
        
        Retorna OrchestrationResult se está no fluxo, None caso contrário.
        """
        cleaned = command.strip()
        
        # Etapa 1: Iniciar fluxo - pedir qual alias excluir
        if self._delete_alias_flow_step is None:
            return None
        
        # Etapa 2: Aguardando alias para excluir
        if self._delete_alias_flow_step == "awaiting_alias":
            alias = cleaned
            if not alias:
                self._reset_delete_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Normaliza a palavra-chave (lowercase, strip)
            alias = alias.strip().lower()
            if not alias:
                self._reset_delete_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Verifica se existe
            aliases = self.alias_manager.list_aliases()
            if alias not in aliases:
                self._reset_delete_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message=f"Alias '{alias}' não encontrado. Nenhum alias foi removido.",
                )
            # Encontrou - mostra o que será excluído e pede confirmação
            target = aliases[alias]
            self._pending_delete_alias = alias
            self._delete_alias_flow_step = "awaiting_confirmation"
            return OrchestrationResult(
                status="awaiting_confirmation",
                message=(
                    f"Encontrei:\n"
                    f"'{alias}' → '{target}'\n\n"
                    f"Deseja realmente excluir esse alias?\n"
                    f"Responda 'sim' para confirmar ou 'não' para cancelar."
                ),
            )
        
        # Etapa 3: Aguardando confirmação
        if self._delete_alias_flow_step == "awaiting_confirmation":
            confirmation = self.confirmation_handler.evaluate_response(cleaned)
            if confirmation is True:
                # Confirmação positiva - remove o alias
                alias = self._pending_delete_alias
                self._reset_delete_alias_flow()
                try:
                    result = self.alias_manager.remove_alias(alias, confirm=True)
                except Exception:
                    return self._uncertain_alias_write()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Removi o alias com sucesso.",
                    )
                else:
                    return OrchestrationResult(
                        status="execution_failed",
                        message=f"Falha ao remover alias: {result.message}",
                    )
            elif confirmation is False:
                # Confirmação negativa - cancela
                self._reset_delete_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Operação cancelada pelo usuário.",
                )
            else:
                # Resposta ambígua - pede novamente
                alias = self._pending_delete_alias
                return OrchestrationResult(
                    status="awaiting_confirmation",
                    message=(
                        f"Resposta não reconhecida. "
                        f"Deseja realmente excluir o alias '{alias}'?\n"
                        f"Responda 'sim' para confirmar ou 'não' para cancelar."
                    ),
                )
        
        return None

    def _handle_alias_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo conversacional de adicionar alias.
        
        Retorna OrchestrationResult se está no fluxo, None caso contrário.
        """
        cleaned = command.strip()
        
        # Etapa 1: Iniciar fluxo - pedir palavra-chave
        if self._alias_flow_step is None:
            return None
        
        # Etapa 2: Aguardando palavra-chave do alias
        if self._alias_flow_step == "awaiting_keyword":
            keyword = cleaned
            if not keyword:
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Normaliza a palavra-chave (lowercase, strip)
            self._pending_alias_keyword = keyword.strip().lower()
            if not self._pending_alias_keyword:
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alias não pode ser vazio. Operação cancelada.",
                )
            # Verifica se já existe
            if self._pending_alias_keyword in self.alias_manager.list_aliases():
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message=f"Alias '{self._pending_alias_keyword}' já existe. Não é possível sobrescrever.",
                )
            self._alias_flow_step = "awaiting_target"
            return OrchestrationResult(
                status="awaiting_confirmation",
                message="Para qual aplicativo ou alvo conhecido?",
            )
        
        # Etapa 3: Aguardando alvo
        if self._alias_flow_step == "awaiting_target":
            target = cleaned
            if not target:
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Alvo não pode ser vazio. Operação cancelada.",
                )
            # Valida se o alvo é permitido pela arquitetura
            allowed_targets = self.permission_manager.ALLOWED_TARGETS
            if target not in allowed_targets:
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="forbidden",
                    message=f"Alvo '{target}' não é um aplicativo autorizado. Apenas alvos permitidos podem ter aliases.",
                )
            self._pending_alias_target = target
            self._alias_flow_step = "awaiting_confirmation"
            return OrchestrationResult(
                status="awaiting_confirmation",
                message=(
                    f"Confirmar criação do alias:\n"
                    f"'{self._pending_alias_keyword}' → '{self._pending_alias_target}'?\n"
                    f"Responda 'sim' para confirmar ou 'não' para cancelar."
                ),
            )
        
        # Etapa 4: Aguardando confirmação
        if self._alias_flow_step == "awaiting_confirmation":
            confirmation = self.confirmation_handler.evaluate_response(cleaned)
            if confirmation is True:
                # Confirmação positiva - adiciona o alias
                keyword, target = self._pending_alias_keyword, self._pending_alias_target
                self._reset_alias_flow()
                try:
                    result = self.alias_manager.add_alias(keyword, target)
                except Exception:
                    return self._uncertain_alias_write()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Adicionei o alias com sucesso.",
                    )
                else:
                    return OrchestrationResult(
                        status="execution_failed",
                        message=f"Falha ao adicionar alias: {result.message}",
                    )
            elif confirmation is False:
                # Confirmação negativa - cancela
                self._reset_alias_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Operação cancelada pelo usuário.",
                )
            else:
                # Resposta ambígua - pede novamente
                return OrchestrationResult(
                    status="awaiting_confirmation",
                    message=(
                        f"Resposta não reconhecida. "
                        f"Confirmar criação do alias:\n"
                        f"'{self._pending_alias_keyword}' → '{self._pending_alias_target}'?\n"
                        f"Responda 'sim' para confirmar ou 'não' para cancelar."
                    ),
                )
        
        return None

    def _handle_unknown_target_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo de alvo desconhecido: perguntar o que significa → oferecer salvar alias.
        
        Retorna OrchestrationResult se está no fluxo, None caso contrário.
        SKILL-001 aplicada: estado explícito, validação, resumo, confirmação real, limpeza.
        """
        cleaned = command.strip()
        
        # Fora do fluxo
        if self._unknown_target_flow_step is None:
            return None
        
        # Etapa 1: Aguardando explicação do usuário
        if self._unknown_target_flow_step == "awaiting_explanation":
            if not cleaned:
                self._reset_unknown_target_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Resposta vazia. Operação cancelada.",
                )
            # Validar se a explicação é um alvo autorizado
            allowed_targets = self.permission_manager.ALLOWED_TARGETS
            if cleaned not in allowed_targets:
                self._reset_unknown_target_flow()
                return OrchestrationResult(
                    status="forbidden",
                    message=f"O alvo '{cleaned}' não é um aplicativo autorizado. Apenas alvos permitidos podem ser utilizados.",
                )
            # Avançar para confirmação
            self._pending_unknown_explained = cleaned
            self._unknown_target_flow_step = "awaiting_confirmation"
            original = self._pending_unknown_original
            return OrchestrationResult(
                status="awaiting_confirmation",
                message=(
                    f"Entendi:\n"
                    f"'{original}' → '{cleaned}'\n\n"
                    f"Deseja salvar essa associação como alias?"
                ),
            )
        
        # Etapa 2: Aguardando confirmação para salvar alias
        if self._unknown_target_flow_step == "awaiting_confirmation":
            confirmation = self.confirmation_handler.evaluate_response(cleaned)
            if confirmation is True:
                # Confirmação positiva - salvar alias
                original = self._pending_unknown_original
                explained = self._pending_unknown_explained
                self._reset_unknown_target_flow()
                try:
                    result = self.alias_manager.add_alias(original, explained)
                except Exception:
                    return self._uncertain_alias_write()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message=f"Salvei o alias '{original}' → '{explained}' com sucesso.",
                    )
                else:
                    return OrchestrationResult(
                        status="execution_failed",
                        message=f"Falha ao salvar alias: {result.message}",
                    )
            elif confirmation is False:
                # Confirmação negativa - cancelar
                self._reset_unknown_target_flow()
                return OrchestrationResult(
                    status="cancelled",
                    message="Operação cancelada. Nenhum alias foi salvo.",
                )
            else:
                # Resposta ambígua - repetir confirmação
                original = self._pending_unknown_original
                explained = self._pending_unknown_explained
                return OrchestrationResult(
                    status="awaiting_confirmation",
                    message=(
                        f"Resposta não reconhecida. "
                        f"Deseja salvar a associação:\n"
                        f"'{original}' → '{explained}'?"
                    ),
                )
        
        return None

    @staticmethod
    def _uncertain_alias_write():
        return OrchestrationResult(status='execution_failed', message=(
            'Não consegui confirmar se a alteração do alias foi salva. '
            'O estado pode ter mudado. Confira os aliases antes de fazer um novo pedido; '
            'não vou repetir a alteração automaticamente.'))

    def _present_calendar_summary(self, ambiguous: bool = False) -> OrchestrationResult:
        draft = self._pending_event_draft
        draft.pop('_presented', None)
        try:
            start, end = self._parse_event_datetimes(draft)
        except CalendarError as err:
            return OrchestrationResult(status='awaiting_confirmation', message=str(err))
        prefix = "Resposta ambígua.\n\n" if ambiguous else ""
        time_display = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        if start.date() != end.date():
            time_display += f" (término em {end.strftime('%d/%m/%Y')})"
        minutes = int((end - start).total_seconds() // 60)
        default = ' (padrão)' if not draft.get('duration_explicit') and 'end_time' not in draft else ''
        draft['_presented'] = True
        # Fixar a data interpretada: uma confirmação após a meia-noite não move "hoje".
        draft['_resolved_date'] = start.strftime('%d/%m/%Y')
        message = (
            f"{prefix}Vou criar:\n"
            f"Título: {draft['title']}\n"
            f"Data: {draft['date']}\n"
            f"Horário: {time_display}\n\n"
            f"Duração: {minutes} minutos{default}\n\n"
            f"Confirmar? [s/n]"
        )
        spoken_time = time_display.replace('–', ' às ')
        date = draft['date']
        spoken_date = date if date.casefold() in {'hoje', 'amanhã', 'amanha'} else f"em {date}"
        speech_message = (
            f"{'Resposta ambígua. ' if ambiguous else ''}"
            f"Vou criar {draft['title']} {spoken_date}, das {spoken_time}. Confirmar?"
        )
        return OrchestrationResult(
            status="awaiting_confirmation", message=message, speech_message=speech_message,
        )

    @staticmethod
    def _merge_event_fields(draft, fields):
        fields = dict(fields)
        if 'date' in fields:
            draft.pop('_resolved_date', None)
        issues = dict(draft.get('_issues', {}))
        for key in fields:
            issues.pop(key, None)
        issues.update(fields.pop('_issues', {}))
        if 'duration_minutes' in fields and 'end_time' not in fields:
            draft.pop('end_time', None)
        if 'end_time' in fields and 'duration_minutes' not in fields:
            draft.pop('duration_explicit', None)
        draft.update(fields)
        draft.pop('_presented', None)
        if issues:
            draft['_issues'] = issues
        else:
            draft.pop('_issues', None)

    def _handle_calendar_create_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo conversacional de criar evento."""
        if self._pending_event_draft is None:
            return None
            
        cleaned = command.strip()
        draft = self._pending_event_draft
        control = self._calendar_control(command)
        if control in {'n', 'nao', 'no', 'cancelar', 'cancele', 'cancela'}:
            self._reset_calendar_create_flow()
            return OrchestrationResult(status='cancelled', message='Operação cancelada pelo usuário.')
        # Uma substituição pede um rascunho novo, nunca herda a proposta anterior.
        if (re.match(r'^(?:na verdade[, ]+)?(?:eu )?(?:quero|queria|preciso|crie|cria|criar|marque|marcar|agende|agendar|outro|novo)\b', control)
                and re.search(r'\b(?:outro|novo|outra|nova)\s+(?:compromisso|evento|reuniao)\b', control)):
            self._reset_calendar_create_flow()
            self._pending_event_draft = {'duration_minutes': 60}
            return OrchestrationResult(status='awaiting_confirmation', message='Qual é o título do novo compromisso?')
        
        corrected_time = interpret_time_correction(command)
        if corrected_time is not None:
            if 'error' in corrected_time:
                draft.pop('_presented', None)
                draft.setdefault('_issues', {})['start_time'] = corrected_time['error']
                return OrchestrationResult(status='awaiting_confirmation', message=corrected_time['error'])
            self._merge_event_fields(draft, corrected_time)
            if all(key in draft for key in ('title', 'date', 'start_time')):
                return self._present_calendar_summary()
        if re.match(r'^(?:ola\b|oi\b|bom dia\b|boa tarde\b|boa noite\b|estou |mudando de assunto|outro assunto|como |qual )', language_control(command)):
            self._reset_calendar_create_flow()
            return None
        title_change = re.fullmatch(r'(?:muda|mude|troca|troque|altera|altere)\s+(?:o\s+)?(?:assunto|titulo|nome)(?:\s+para\s+(.+))?',control)
        if title_change:
            draft.pop('_presented',None)
            if title_change[1]:
                draft.pop('_awaiting_title',None)
                self._merge_event_fields(draft,{'title':title_change[1].capitalize()})
                if all(key in draft for key in ('title','date','start_time')):
                    return self._present_calendar_summary()
                return OrchestrationResult(status='awaiting_confirmation',message=(
                    'Para qual data?' if 'date' not in draft else 'A que horas?'))
            else:
                draft['_awaiting_title']=True
                return OrchestrationResult(status='awaiting_confirmation',message='Qual é o novo assunto da reunião?')
        if draft.get('_awaiting_title'):
            if self.intent_recognizer.parse(cleaned) is not None:
                self._reset_calendar_create_flow()
                return None
            if self.confirmation_handler.evaluate_response(cleaned.rstrip('.!?')) is not None or not cleaned:
                return OrchestrationResult(status='awaiting_confirmation',message='Qual é o novo assunto da reunião? Nenhum evento foi criado.')
            _, temporal_fields = extract_fields(cleaned)
            if temporal_fields:
                self._merge_event_fields(draft,temporal_fields)
                return OrchestrationResult(status='awaiting_confirmation',message='Atualizei os campos informados no rascunho. Qual é o novo assunto da reunião?')
            draft.pop('_awaiting_title',None)
            self._merge_event_fields(draft,{'title':cleaned.rstrip('.!?').capitalize()})
            if all(key in draft for key in ('title','date','start_time')):
                return self._present_calendar_summary()
            return OrchestrationResult(status='awaiting_confirmation',message=(
                'Para qual data?' if 'date' not in draft else 'A que horas?'))
        # Uma resposta de horário pertence ao rascunho atual, inclusive após erro.
        # A validação integral evita extrair apenas "5" de "5 horas e 50 da tarde".
        try:
            hour, minute = parse_time(cleaned)
        except CalendarError:
            pass
        else:
            if 'start_time' not in draft or all(key in draft for key in ('title','date')):
                self._merge_event_fields(draft, {'start_time': f'{hour:02d}:{minute:02d}'})
                if all(key in draft for key in ('title','date','start_time')):
                    return self._present_calendar_summary()
                return OrchestrationResult(status='awaiting_confirmation',message=(
                    'Qual é o título do evento?' if 'title' not in draft else 'Para qual data?'))
        if selection(command) is not None and not re.fullmatch(r'\d{1,2}(?:(?:h|:)\d{2}|h)?', command.strip()):
            draft.pop('_presented', None)
            draft.setdefault('_issues', {})['date'] = 'Você quer mudar a data ou selecionar uma nota/tarefa? Informe o pedido completo.'
            return OrchestrationResult(status='awaiting_confirmation', message=draft['_issues']['date'])

        is_complete = "title" in draft and "date" in draft and "start_time" in draft

        # Respostas à coleta podem informar o assunto mesmo depois do título padrão.
        subject = re.fullmatch(r'(?:o\s+)?(?:assunto|título|titulo|nome)(?:\s+(?:da\s+reunião|do\s+evento))?\s+(?:é|e|será)\s+(.+?)[.!?]*', cleaned, re.I)
        if subject:
            title = re.sub(r'\s+e\s+o\s+participante\s+(?:vai\s+ser|será|é)\s+s[oó]\s+eu$', '', subject[1], flags=re.I).strip()
            self._merge_event_fields(draft, {'title': title.capitalize()})
            if is_complete:
                return self._present_calendar_summary()
            cleaned = ''
        
        if not is_complete:
            # --- Coleta segura: verificar antes de preencher campo ---

            # A. Entrada vazia — repetir pergunta atual
            if not cleaned:
                if "title" not in draft:
                    return OrchestrationResult(status="awaiting_confirmation", message="Qual é o título do evento?")
                if "date" not in draft:
                    return OrchestrationResult(status="awaiting_confirmation", message="Para qual data?")
                if "start_time" not in draft:
                    return OrchestrationResult(status="awaiting_confirmation", message="A que horas?")

            # B. Cancelamento explícito
            if cleaned.lower() in ("não", "nao", "cancelar", "cancele", "cancela", "no"):
                self._reset_calendar_create_flow()
                return OrchestrationResult(status="cancelled", message="Operação cancelada pelo usuário.")

            # C. Novo comando reconhecido pelo IntentRecognizer
            new_intent = self.intent_recognizer.parse(cleaned)
            if new_intent is not None:
                self._reset_calendar_create_flow()
                return None  # process_command principal processa normalmente

            # Campos explícitos podem preencher mais de uma resposta de coleta.
            if self.confirmation_handler.evaluate_response(cleaned.rstrip('.!?')) is not None:
                missing = ('Qual é o título do evento?' if 'title' not in draft else
                           'Para qual data?' if 'date' not in draft else 'A que horas?')
                return OrchestrationResult(status='awaiting_confirmation', message=missing)
            residual, fields = extract_fields(cleaned)
            if fields:
                self._merge_event_fields(draft, fields)
            elif "title" not in draft:
                draft["title"] = cleaned.capitalize()
            elif "date" not in draft:
                draft["date"] = cleaned
            elif "start_time" not in draft:
                draft["start_time"] = cleaned
                
            if "title" not in draft:
                return OrchestrationResult(status="awaiting_confirmation", message="Qual é o título do evento?")
            if "date" not in draft:
                return OrchestrationResult(status="awaiting_confirmation", message="Para qual data?")
            if "start_time" not in draft:
                return OrchestrationResult(status="awaiting_confirmation", message="A que horas?")
                
            return self._present_calendar_summary()
            
        # Is complete, waiting for confirmation or correction
        # 1. Cancelamento local explícito
        if cleaned.lower() in ("cancelar", "cancela", "cancele"):
            self._reset_calendar_create_flow()
            return OrchestrationResult(status="cancelled", message="Operação cancelada pelo usuário.")

        # 2. Novo comando determinístico reconhecido pelo IntentRecognizer
        new_intent = self.intent_recognizer.parse(cleaned)
        if new_intent is not None:
            self._reset_calendar_create_flow()
            return None  # process_command principal processa normalmente

        title_match = re.search(r'(?:o\s+nome\s+é|título\s+é|(?:mude|troque|altere|corrija)\s+o\s+título\s+para)\s+(.+)', cleaned, re.IGNORECASE)
        if title_match:
            draft['title'] = title_match.group(1).strip().capitalize()
            return self._present_calendar_summary()
        _, fields = extract_fields(cleaned)
        time_correction = re.fullmatch(r'(?:mude|troque|altere|corrija)(?:\s+(?:o\s+)?(?:horário|horario|início|inicio))?\s+para\s+(\d{1,2}(?:(?:h|:)\d{2}|h)?)', cleaned, re.I)
        end_correction = re.fullmatch(r'(?:mude|troque)\s+(?:o\s+)?(?:término|fim)\s+para\s+(\d{1,2}(?:(?:h|:)\d{2}|h)?)', cleaned, re.I)
        if time_correction:
            fields['start_time'] = time_correction.group(1)
        elif end_correction:
            fields['end_time'] = end_correction.group(1)
        elif re.fullmatch(r'\d{1,2}(?:(?:h|:)\d{2}|h)?', cleaned):
            fields['start_time'] = cleaned
        if fields:
            self._merge_event_fields(draft, fields)
            return self._present_calendar_summary()
            
        confirmation = self.confirmation_handler.evaluate_response(cleaned.rstrip('.!?').strip())
        if confirmation is True:
            if not draft.get('_presented'):
                return self._present_calendar_summary()
            if self.calendar_adapter is None:
                self._reset_calendar_create_flow()
                return OrchestrationResult(
                    status="execution_failed",
                    message="Calendário não disponível.",
                )
            try:
                start, end = self._parse_event_datetimes(draft)
            except CalendarError as err:
                draft.pop('_presented', None)
                return OrchestrationResult(
                    status="awaiting_confirmation",
                    message=f"Erro ao preparar evento: {err}",
                )
            if self._workflows.active and self._workflow_cancel_event.is_set():
                self._reset_calendar_create_flow()
                return OrchestrationResult(status='cancelled', message='Cancelei a criação antes de chamar o calendário.')
            # Consumir antes da chamada externa: uma falha não autoriza repetição.
            self._reset_calendar_create_flow()
            try:
                event = self.calendar_adapter.create_event(
                    summary=draft["title"],
                    start=start,
                    end=end,
                )
                event_summary = event.summary
            except Exception:
                self._reset_calendar_create_flow()
                return OrchestrationResult(
                    status="execution_failed",
                    message=('Erro ao criar evento: não consegui confirmar o resultado do serviço. '
                             'O evento pode ter sido criado. Confira seu calendário antes de fazer um novo pedido; '
                             'não vou repetir a criação automaticamente.'),
                )
            self._reset_calendar_create_flow()
            return OrchestrationResult(
                status="success",
                message=(
                    f"Criei o evento no calendário:\n"
                    f"{event_summary} — "
                    f"{start.strftime('%d/%m/%Y %H:%M')}–{end.strftime('%H:%M')}"
                ),
            )
        elif confirmation is False:
            self._reset_calendar_create_flow()
            return OrchestrationResult(status="cancelled", message="Operação cancelada pelo usuário.")
        else:
            if language_control(command) in {'talvez', 'nao sei', 'acho que sim', 'hmm', 'sim mas'}:
                return self._present_calendar_summary(ambiguous=True)
            draft.pop('_presented', None)
            return OrchestrationResult(status='awaiting_confirmation', message='Não reconheci essa correção. O rascunho foi mantido. Diga o horário, a data ou o assunto; diga cancelar para desistir.')

    def _handle_open_app_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo de abertura contextual quando target é vago ('isso'/'aquilo').
        
        Retorna OrchestrationResult se está no fluxo, None caso contrário.
        """
        if not self._open_app_flow_active:
            return None

        cleaned = command.strip()

        # A. Entrada vazia — repetir pergunta
        if not cleaned:
            return OrchestrationResult(
                status="awaiting_confirmation",
                message="Qual aplicativo você quer abrir?",
            )

        # B. Cancelamento explícito
        if cleaned.lower() in ("não", "nao", "cancelar", "cancele", "cancela", "no"):
            self._reset_open_app_flow()
            return OrchestrationResult(
                status="cancelled",
                message="Operação cancelada pelo usuário.",
            )

        # C. Novo comando determinístico — interrompe fluxo
        new_intent = self.intent_recognizer.parse(cleaned)
        if new_intent is not None:
            self._reset_open_app_flow()
            return None  # process_command principal processa normalmente

        # D. Target textual — construir Intent e limpar pending
        target = cleaned.capitalize() if cleaned.islower() else cleaned
        self._reset_open_app_flow()
        # Retornar Intent via variável auxiliar para process_command processar
        self._pending_open_app_result = Intent(
            action="abrir aplicativo",
            target=target,
            raw_command=command,
            requires_confirmation=True,
        )
        return None

    def _capability_app_mode(self):
        if self.application_catalog is None:
            return 'simulated' if self.simulate else 'real'
        try:
            return 'simulated' if self._catalog_simulated() else 'real'
        except (OSError,ValueError,TypeError):
            return 'unavailable'

    def _capabilities_summary(self) -> str:
        """Descreve a instalação atual sem prometer saúde de serviços externos."""
        lines = [
            "Posso buscar e consultar notas do Segundo Cérebro dentro do escopo permitido "
            "e consultar informações desta sessão.",
            "Posso listar e gerenciar aliases; alterações seguem as confirmações do sistema.",
            "Posso adicionar, listar, concluir e reabrir tarefas temporárias desta sessão. Limpar ou encerrar apaga a lista.",
        ]
        if self.ai_core is not None:
            lines.append("A IA está configurada para conversar e gerar planos textuais; depende da disponibilidade do modelo local.")
        else:
            lines.append("A conversa com o modelo de IA está desabilitada nesta instância.")
        app_mode=self._capability_app_mode()
        if app_mode=='simulated':
            lines.append("Abrir aplicativos está em modo de simulação: posso demonstrar o fluxo, mas não abro o aplicativo de verdade.")
        elif app_mode=='real':
            lines.append("Posso solicitar a abertura de aplicativos permitidos, com confirmação antes da execução.")
        else:
            lines.append('Não confirmei o modo de abertura dos aplicativos. Revise a configuração no painel Autonomia.')
        if self.calendar_adapter is None:
            lines.append("O calendário está indisponível nesta instância: não posso consultar nem criar eventos agora.")
        else:
            lines.append("O calendário está configurado para consultar e criar eventos, com confirmação na criação; o funcionamento depende da conexão e da autorização do serviço.")
        if self.application_catalog is not None:
            try:
                names = [app.name for app in self.application_catalog.entries()]
                lines.append('Catálogo aprovado: '+(', '.join(names) if names else 'nenhum aplicativo cadastrado')+
                    '. O painel Autonomia permite cadastro, testes e autorizações específicas por sete dias.')
            except (OSError,ValueError,TypeError):
                lines.append('Não confirmei o catálogo de aplicativos; nenhuma abertura adicional foi liberada.')
        if self._agent_config.get('enabled') is True:
            lines.append('O núcleo de ferramentas está ativo para acompanhar etapas, fontes, confirmações e recibos. '
                         'A abertura de um aplicativo do catálogo é separada da automação de páginas ou controles.')
            optional = [('gmail_enabled','Gmail e rascunhos'), ('browser_enabled','navegação em páginas'),
                        ('desktop_enabled','automação de controles Windows'), ('web_enabled','pesquisa web'),
                        ('documents_enabled','documentos locais'), ('tasks_enabled','tarefas persistentes'),
                        ('learning_enabled','propostas de procedimentos'), ('mcp_enabled','servidores MCP')]
            enabled=[label for key,label in optional if self._agent_config.get(key) is True]
            disabled=[label for key,label in optional if self._agent_config.get(key) is not True]
            if enabled:
                lines.append('Recursos opcionais habilitados: '+', '.join(enabled)+
                             '. Cada uso depende das fontes, permissões e dependências disponíveis; esta resposta não testou as conexões.')
            if disabled:
                lines.append('Recursos opcionais desativados nesta configuração: '+', '.join(disabled)+'.')
            persistent=self._agent_config.get('history_enabled') is True and not self._agent_temporary
            lines.append('Histórico persistente de conversa: '+('habilitado, sujeito à retenção configurada.' if persistent else
                         'desativado nesta conversa; posso consultar as mensagens da sessão atual.'))
        return "\n\n".join(lines)

    def _spoken_capabilities(self) -> str:
        parts = [
            'Posso ajudar você a buscar notas autorizadas no Segundo Cérebro, '
            'consultar esta conversa e gerenciar os apelidos dos aplicativos.'
        ]
        if self.ai_core is not None:
            parts.append('Também posso conversar e ajudar a planejar, quando o modelo local estiver disponível.')
        else:
            parts.append('A conversa com o modelo local está desativada agora.')
        app_mode=self._capability_app_mode()
        if app_mode=='simulated':
            parts.append('Por enquanto, só simulo a abertura dos aplicativos; não os abro de verdade.')
        elif app_mode=='real':
            parts.append('Posso abrir aplicativos permitidos depois da sua confirmação.')
        else:
            parts.append('O modo de abertura dos aplicativos precisa ser revisto no painel Autonomia.')
        if self.calendar_adapter is None:
            parts.append('O calendário está indisponível agora.')
        else:
            parts.append('O calendário está configurado para consultas e criação de eventos, '
                         'mas depende da conexão e da autorização. Antes de criar um evento, peço sua confirmação.')
        parts.append('Posso manter uma lista temporária de tarefas nesta sessão; Limpar ou encerrar apaga a lista.')
        parts.append('Alterações nos apelidos também precisam da sua confirmação.')
        return ' '.join(parts)

    def _build_ai_context(self, command: str = "") -> dict:
        """Cria snapshot somente leitura do contexto para o AICore."""
        # Excluir o pedido atual da busca; o provider o inclui integralmente uma vez.
        prior_turns = list(self.memory.turns)
        if prior_turns and prior_turns[-1].role == "user" and prior_turns[-1].text == command:
            prior_turns = prior_turns[:-1]
        prior_turns = [turn for turn in prior_turns if turn.turn_id not in self._task_turn_ids and turn.origin != 'memory_preview']
        if not self._personal_sources_valid():
            self._clear_personal_context()
        recent = conversation_turns(prior_turns, command)
        model = getattr(getattr(self.ai_core, '_provider', None), 'model', None)
        ctx = {
            "session_tasks": self._session_tasks.context(),
            "voice_conversation": self.voice_conversation,
            "last_tool_evidence": self._last_tool_evidence,
            "capabilities_summary": self._capabilities_summary(),
            "recent_turns": recent,
            "session_retrieval": True,
            "assistant_identity": dict(self._identity_facts, model=model if isinstance(model, str) else None),
            "conversation_frame": dict(self._conversation_frame.snapshot(self._language_clock()),
                topic=self._conversation_frame.topic_for(command, self._language_clock()),
                reply=language_control(command) if language_control(command) in {'sim', 'nao', 'nao obrigado', 'pode'} else None),
            "deadline_monotonic": self._request_deadline,
            "allow_format_repair": True,
            "format_repair_budget": self._format_repair_budget,
            "last_intent": self.memory.last_intent,
            "last_target": self.memory.last_target,
            "last_status": self.memory.last_status,
            "last_result_summary": (
                self.memory.last_result[:200]
                if self.memory.last_result and not self._last_result_personal and (not self.memory.turns or
                    (self.memory.turns[-1].turn_id not in self._task_turn_ids and self.memory.turns[-1].origin != 'personal_context'))
                else None
            ),
        }
        if self._knowledge_review.proposal is not None:
            try:
                ctx['selected_note_evidence'] = self._knowledge_review.conversation_evidence(
                    self.second_brain, self._session_id, self._knowledge_read_roots)
            except (KnowledgeError, OSError, ValueError, PermissionError):
                self._knowledge_review.clear()
        if self._knowledge_repository is not None and command:
            try:
                policy = self.knowledge.policy
                roots = tuple(effective_roots(ReadScope('memory', policy.read_roots), self._knowledge_read_roots))
                # Não existe repositório no caminho normal da interface nesta entrega.
                safe_policy = replace(policy, read_roots=roots)
                if self._supervised_memory.evidence is not None:
                    records = self._supervised_memory.retrieve(command, roots)
                else:
                    records = self._knowledge_repository.retrieve(command, safe_policy,
                        self.knowledge.clock(), self._knowledge_source_resolver)
                if records:
                    ctx['knowledge_context'] = records
            except (KnowledgeError, OSError, ValueError, TypeError):
                pass
        # Orçamento operacional continua usando apenas a janela recente original.
        budget = _extract_pomodoro_budget(command, [
            {"role": turn.role, "text": turn.text}
            for turn in self.memory.recent_turns(5)
        ])
        if budget is not None and ctx['conversation_frame']['topic'] != 'assistant':
            ctx["pomodoro_budget"] = budget
        if self._pending_clarification is not None:
            ctx["pending_clarification"] = self._pending_clarification
        return ctx

    def _ai_response_to_intent(self, response) -> Intent:
        """Converte AIResponse para Intent canônico existente."""
        intent_str = response.intent
        args = response.arguments or {}

        target = ""
        entities = None

        if intent_str == "abrir aplicativo":
            target = args.get("target", "")
        elif intent_str == "buscar segundo cérebro":
            target = args.get("term", "")
        elif intent_str == "consultar segundo cérebro":
            target = args.get("path", "")
        elif intent_str == "criar evento calendário":
            entities = args

        requires_confirmation = self.permission_manager.requires_confirmation(
            Intent(action=intent_str, target=target, raw_command="")
        )

        return Intent(
            action=intent_str,
            target=target,
            raw_command=response.message or "",
            requires_confirmation=requires_confirmation,
            entities=entities,
        )

    def _ai_action_matches_request(self, command, response):
        """Uma proposta do modelo não pode inventar campos sensíveis ou remover negações."""
        clean = language_control(command)
        if prohibited_action(command):
            return False
        args = response.arguments
        if response.intent == 'criar evento calendário':
            if not re.match(r'^(?:(?:voce )?pode |gostaria (?:de |que voce )|quero (?:que voce )?)?(?:agend\w*|marc\w*|cri\w*)\b', clean):
                return False
            _, fields = extract_fields(command)
            if not {'date', 'start_time'} <= fields.keys() or fields.get('_issues'):
                return False
            try:
                original = dict(fields, duration_minutes=fields.get('duration_minutes', 60))
                proposed = dict(args)
                if self._parse_event_datetimes(original) != self._parse_event_datetimes(proposed):
                    return False
            except CalendarError:
                return False
            residual, _ = extract_fields(command)
            title = re.sub(r'^(?:(?:voc[eê] )?pode |gostaria (?:de |que voc[eê] )|quero (?:que voc[eê] )?)?(?:agend\w*|marc\w*|cri\w*)\s+', '', residual.strip(), flags=re.I)
            return args['title'].casefold() == title.strip(' ,.!?').casefold()
        if response.intent == 'abrir aplicativo':
            return bool(re.match(r'^(?:(?:voce )?pode |quero que voce )?(?:abra|abre|abrir)\b', clean)
                        and args['target'].casefold() in command.casefold())
        if response.intent == 'calendário hoje':
            _, fields = extract_fields(command)
            if 'date' in fields:
                try:
                    return parse_day(fields['date'], self._calendar_now()) == self._calendar_now().date()
                except CalendarError:
                    return False
        return True

    def _voice_opening_review(self, command, intent):
        """Variantes orais conhecidas exigem alvo cadastrado único e confirmação."""
        catalog = self.application_catalog
        if not self.voice_conversation or catalog is None or prohibited_action(command):
            return intent
        try:
            if intent is not None and (intent.entities or {}).get('new_window'):
                if catalog.resolve(intent.target):return intent
                if language_control(intent.target) in {'tronco','cronico'}:
                    matches=catalog.resolve('chrome')
                    if len(matches)==1:
                        return Intent(action='abrir aplicativo',target=matches[0].name,raw_command=command,
                            requires_confirmation=True,entities={'new_window':True})
            # Um nome literal já cadastrado tem prioridade, inclusive se começa com E.
            if intent is not None and (intent.action != 'abrir aplicativo' or catalog.resolve(intent.target)):
                return intent
            candidate = re.sub(r'[.!?]+$', '', command.strip()).strip()
            from therion.context.language import APP_VOCATIVE
            match = re.fullmatch(
                r'(?:'+APP_VOCATIVE+r'[,\s]+)?(?:agora[,\s]+)?(?:abro|abri|abriu|admi|adriu|adding|abra|abre|abrir)(?:\s+e)?\s+'
                r'(?:o\s+)?([\wÀ-ÿ. -]+)', candidate, re.I)
            if match:
                target=match[1].strip()
                matches=catalog.resolve(target)
                if not matches and language_control(target)=='obsidio':
                    matches=catalog.resolve('Obsidian')
                if not matches and language_control(target)=='navigador':
                    matches=catalog.resolve('navegador')
                if len(matches)!=1:
                    return intent
                # O raw_command permanece incerto para CatalogSupport: a checagem
                # explícita não coincide e força confirmação, mesmo com política.
                return Intent(action='abrir aplicativo', target=matches[0].name,
                    raw_command=command, requires_confirmation=True)
        except (OSError, ValueError, TypeError):
            pass
        return intent

    def acknowledge_briefing(self,identifier):
        from therion.agent.briefing import acknowledge
        return acknowledge(self,identifier)

    def _mail_navigation(self,command,cancelled=None,presentation=None):
        from therion.agent.briefing import briefing_command,collect
        from therion.agent.contracts import CancellationToken,Cancelled
        if briefing_command(command) and self._confirmation_id is None:
            proposals=getattr(self,'_agent_proposals',None)
            if proposals and proposals.list():return None
            try:payload=collect(self,command,CancellationToken(cancelled),presentation)
            except Cancelled:return OrchestrationResult(status='cancelled',message='Panorama cancelado; nenhum marco foi alterado.')
            return OrchestrationResult(status='success',message=payload['message'],speech_message=payload['message'],
                                       ui_action='open_briefing',ui_payload=payload)
        from therion.integrations.task_query import task_query_request,render
        if task_query_request(command) and self._confirmation_id is None:
            # Mesma fonte do panorama: o modelo não pode negar uma tarefa que o panorama citou.
            from therion.interface.dashboard_data import DashboardSource
            try:row=DashboardSource(self).tasks(CancellationToken(cancelled))
            except Cancelled:return OrchestrationResult(status='cancelled',message='Consulta de tarefas cancelada.')
            except Exception:row=dict(state='error',message='Consulta indisponível agora.',saved=[],temporary=[])
            message,speech=render(row)
            return OrchestrationResult(status='success',message=message,speech_message=speech)
        from therion.agent.mailbox import mail_window_request
        if mail_window_request(command):
            return OrchestrationResult(status='success',message='A janela de e-mails está aberta.',
                ui_action='open_mail',confirmation_id=self._confirmation_id)
        return None

    def process_command(self, command: str) -> OrchestrationResult:
        with self._operation_lock:
            navigation=self._mail_navigation(command)
            if navigation is not None:return navigation
            self._sync_knowledge_access()
            agent_result = self._dispatch_agent(command)
            if agent_result is not None:
                return agent_result
            confirmation=self._confirmation_id
            self._agent_begin_legacy(confirmation)
            try:result = self._process_command(command)
            except BaseException:
                self._agent_finish_legacy(confirmation);raise
            self._agent_finish_legacy(confirmation,result)
            self._record_legacy_history(command, result)
            return result

    def _process_command(self, command: str, cancelled=None) -> OrchestrationResult:
        self._workflow_cancel_event = cancelled if cancelled is not None else threading.Event()
        provider_timeout = getattr(getattr(self.ai_core, '_provider', None), 'timeout', 90)
        self._request_deadline = time.monotonic() + (provider_timeout if type(provider_timeout) in (int, float) and provider_timeout > 0 else 90)
        self._format_repair_budget = {'remaining': 1}
        self._personal_reply_active = False
        """Processa um comando textual registrando todas as etapas na memória de trabalho."""
        submitted_command = command
        if re.match(r'^(?:correcao\b|na verdade\b|corrigindo\b|agora prefiro\b)', language_control(command)):
            self._supervised_memory.corrections.append(command[:1500])
            if len(self._supervised_memory.corrections) > 3:
                self._supervised_memory.corrections_overflow = True
            self._supervised_memory.corrections[:] = self._supervised_memory.corrections[-3:]
        fresh = self._last_exchange_time is not None and self._language_clock() - self._last_exchange_time <= 300
        self._previous_language_focus = self._language_focus if fresh else None
        if self._previous_language_focus != 'notes':
            self._pending_search_summary = False
        if self._previous_language_focus != 'notes':
            self._recent_note_index = None
        if not fresh:
            self._recent_task_ids = ()
        self._language_focus = None
        pending_task_reference = self._pending_task_reference if fresh else None
        self._pending_task_reference = None
        prior_user = next((turn.text for turn in reversed(self.memory.turns) if turn.role == 'user'), None) if fresh else None
        if not fresh or selection(command) is None:
            self._pending_note_selection = None
        # Contagem conservadora inclui uma possível cópia da sintaxe de escopo.
        if not self.memory.can_start_exchange(command) or (
            self.memory.session_characters + 2 * len(command)
            + 2 * self.memory.MAX_MESSAGE_CHARACTERS > self.memory.MAX_CHARACTERS
        ):
            return OrchestrationResult(
                status="session_limit",
                message=(
                    "Mensagem acima do limite de 16.000 caracteres. Reduza o texto."
                    if len(command) > self.memory.MAX_MESSAGE_CHARACTERS else
                    "Limite da sessão atingido. O histórico anterior foi preservado. "
                    "Use Limpar conversa para iniciar outra sessão."
                ),
            )
        request = memory_request(command)
        if request is not None:
            return self._process_memory_request(command, request)
        if language_control(command) in {'proponha melhorias de skills', 'proponha skills', 'mostre os padroes de erro'}:
            try:
                message = skill_proposals(self.second_brain, self.knowledge)
                return OrchestrationResult(status='success', message=message, confirmation_id=self._confirmation_id)
            except (KnowledgeError, OSError, ValueError, PermissionError):
                return OrchestrationResult(status='clarification', message='Não consegui revalidar as referências autorizadas de Skills. Nenhuma proposta foi ativada.', confirmation_id=self._confirmation_id)
        review = review_request(command)
        if review is not None:
            if self._confirmation_id is not None:
                return OrchestrationResult(status='clarification', message='Resolva a confirmação pendente antes de revisar notas.', confirmation_id=self._confirmation_id)
            try:
                operation, paths = review
                if operation == 'apply':
                    message = 'A consolidação é somente proposta. Nenhuma nota foi alterada. Revise o conteúdo e autorize a edição em uma tarefa específica.'
                elif operation == 'show':
                    message = self._knowledge_review.inspect(self.second_brain, self._session_id)
                else:
                    message = self._knowledge_review.prepare(operation, paths, self.second_brain, self._session_id,
                        provider=getattr(self.ai_core,'_provider',None) if self.ai_core else None,
                        cancelled=self._workflow_cancel_event.is_set)
                if operation != 'apply':
                    proposal = self._knowledge_review.valid(self.second_brain, self._session_id)
                    self._note_results = NoteResults(tuple(os.path.relpath(source.path, self.second_brain.vault_root)
                                                          for source in proposal.sources),
                                                    tuple(_canonical(root) for root in self.second_brain.allowed_roots))
                    self._recent_note_index = None
                    self._note_results_created = self._language_clock()
                    self._language_focus = 'notes'
                    self._last_exchange_time = self._language_clock()
                return OrchestrationResult(status='success', message=message)
            except (KnowledgeError, OSError, ValueError, PermissionError) as error:
                self._knowledge_review.clear()
                return OrchestrationResult(status='clarification', message=str(error))
        memory_control = self._memory_save_control(command)
        if memory_control is not None:
            return memory_control
        workflow_control = self._workflow_control(command)
        if workflow_control is not None:
            return workflow_control
        self._selected_memory_id = None
        self._selected_memory_time = None
        self._pending_action_plan = None
        self._pending_action_fingerprint = None
        self._confirmation_id = None
        self._scope_note = ""
        mode = "simulado" if self.simulate else "real"
        scope_syntax = _parse_scope_syntax(command)
        scope: Optional[ReadScope] = None
        scope_roots: Optional[_ScopeRoots] = None
        if scope_syntax.present and not scope_syntax.malformed:
            scope_roots = self._resolve_scope_roots(scope_syntax.roots)
            command = scope_syntax.command
            if scope_roots.rejected and not scope_roots.invalid:
                self._scope_note = "Raízes rejeitadas: " + "; ".join(
                    f"{root} ({reason})" for root, reason in scope_roots.rejected
                )
        self._knowledge_read_roots = tuple(scope_roots.accepted) if scope_roots is not None else (() if scope_syntax.present else tuple(self.second_brain.allowed_roots))
        new_search = self.intent_recognizer.parse(command)
        if new_search is not None and new_search.action == 'buscar segundo cérebro':
            self._knowledge_review.clear()
            self._search_snapshot = None
            self._pending_search_summary = False
            self._note_results = NoteResults((), ())
            self._recent_note_index = None
            self._pending_note_selection = None
            self._last_tool_evidence = {'kind': 'search', 'matches': []}
        self.memory.start_task(command=command, execution_mode=mode)
        self.memory.add_turn(
            "user", command,
            submitted_text=submitted_command if submitted_command != command else None,
        )
        if scope_syntax.present and not scope_syntax.malformed:
            scope = ReadScope(
                task_id=self.memory.current_task.task_id,
                roots=scope_roots.accepted,
            )
        if scope_syntax.malformed or (scope_roots is not None and scope_roots.invalid):
            self.memory.record_read_scope(None, None, None, [])
        elif scope is not None:
            declared = [os.path.normpath(root).replace("\\", "/") for root in scope_syntax.roots]
            accepted = [self._audit_relative_root(root) for root in scope_roots.accepted]
            effective = [
                self._audit_relative_root(root)
                for root in effective_roots(scope, self.second_brain.allowed_roots)
            ]
            if any(root is None for root in accepted + effective):
                self.memory.record_read_scope(None, None, None, [])
            else:
                self.memory.record_read_scope(declared, accepted, effective, [])
        if scope_syntax.malformed:
            self.memory.record_error(
                "Declaração de raízes inválida: "
                f"{scope_syntax.reason}. "
                "Formato esperado: raízes: <relativa-ao-vault>[, ...] :: <comando>"
            )
            self._complete_task()
            result = OrchestrationResult(
                status="invalid_scope",
                message=(
                    "Declaração de raízes inválida: "
                    f"{scope_syntax.reason}. "
                    "Formato esperado: raízes: <relativa-ao-vault>[, ...] :: <comando>"
                ),
            )
            self._finalize_session_result(result)
            return result
        if scope_roots is not None and scope_roots.invalid:
            details = "; ".join(
                f"{root} ({reason})" for root, reason in scope_roots.invalid
            )
            self.memory.record_error(f"Declaração de raízes inválida: {details}")
            self._complete_task()
            result = OrchestrationResult(
                status="invalid_scope",
                message=f"Declaração de raízes inválida: {details}",
            )
            self._finalize_session_result(result)
            return result

        calendar_followup = self._calendar_followup_request(command)
        if calendar_followup is not None:
            intent = Intent(action='consultar agenda',target='',raw_command=command,requires_confirmation=False,
                            entities=calendar_followup)
            result = self._handle_calendar_query(intent, calendar_followup)
            self._complete_task()
            self._finalize_session_result(result)
            return result
        self._calendar_query_context = None

        if self._personal_flow_is_free():
            from therion.context.conversation_frame import app_result_request
            if app_result_request(command):
                self._remember_status_prompt()
                result=OrchestrationResult(status='clarification',message='Qual aplicativo você quer conferir? Para abrir, diga “Abre” e o nome do aplicativo. Nenhuma ação foi executada.')
                self._complete_task();self._finalize_session_result(result)
                return result
            close_result=self._close_request(command)
            if close_result is not None:
                self._complete_task();self._finalize_session_result(close_result)
                return close_result
            app_status=self._catalog_status(command)
            if app_status is not None:
                self._complete_task()
                self._finalize_session_result(app_status)
                return app_status

        if current_time_request(command) and self._personal_flow_is_free():
            now = self._calendar_now()
            units = ((now.hour,'hora'),(now.minute,'minuto'),(now.second,'segundo'))
            spoken = [f'{value} {unit}' + ('' if value == 1 else 's') for value,unit in units]
            result = OrchestrationResult(status='success', message=f'Agora são {now:%H:%M:%S}.',
                speech_message=f'Agora são {spoken[0]}, {spoken[1]} e {spoken[2]}.')
            self._complete_task()
            self._finalize_session_result(result)
            return result

        if current_date_request(command) and self._personal_flow_is_free():
            now = self._calendar_now()
            weekday = ('segunda-feira','terça-feira','quarta-feira','quinta-feira',
                       'sexta-feira','sábado','domingo')[now.weekday()]
            result = OrchestrationResult(status='success',
                message=f'Hoje é {weekday}, {now:%d/%m/%Y}.')
            self._complete_task()
            self._finalize_session_result(result)
            return result

        personal_purpose = personal_request(command,voice=self.voice_conversation)
        if personal_purpose is not None and self._personal_flow_is_free():
            result = self._resolve_personal_context(personal_purpose, command, scope)
            self._complete_task()
            self._finalize_session_result(result)
            return result
        if not self._personal_sources_valid(scope):
            self._clear_personal_context()
        self._conversation_frame.snapshot(self._language_clock())
        conversational_answer = (self._conversation_frame.reply(command, self._language_clock())
            or (language_control(command) in {'nao', 'nao obrigado'}
                and self._conversation_frame.updated is not None and self._personal_flow_is_free()))
        assistant_topic = self._conversation_frame.topic_for(command, self._language_clock()) == 'assistant'
        conversational_decline = conversational_answer and language_control(command) in {'nao', 'nao obrigado'}
        if ((assistant_topic or conversational_decline) and not capabilities_request(command) and self._personal_flow_is_free()
                and not has_explicit_action(command)):
            result = self._answer_assistant_question(command)
            self._complete_task()
            self._finalize_session_result(result)
            return result
        workflow_result = self._try_workflow(command, scope)
        if workflow_result is not None:
            return workflow_result
        tasks_request = task_request(command)
        chosen = selection(command)
        if tasks_request is None and chosen is not None and self._previous_language_focus == 'tasks':
            ids = self._recent_task_ids
            numeric_id = any(char.isdigit() for char in command)
            selected_id = ((chosen if chosen in ids else None) if numeric_id else
                           ids[chosen-1] if chosen > 0 and chosen <= len(ids) else ids[-1] if chosen == -1 and ids else None)
            if selected_id is not None:
                tasks_request = {'operation': pending_task_reference or 'show', 'id': str(selected_id)}
            else:
                self._language_focus = 'tasks'
                self._pending_task_reference = pending_task_reference
                result = OrchestrationResult(status='clarification', message='Esse número não identifica uma tarefa da lista exibida. Informe o identificador mostrado ou uma posição por extenso.')
                self._complete_task()
                self._finalize_session_result(result)
                return result
        if tasks_request is not None and tasks_request['operation'] == 'task_reference':
            if self._previous_language_focus == 'tasks' and len(self._recent_task_ids) == 1:
                tasks_request = {'operation': tasks_request['action'], 'id': str(self._recent_task_ids[0])}
            else:
                if self._previous_language_focus != 'tasks':
                    self._recent_task_ids = ()
                self._pending_task_reference = tasks_request['action']
                self._language_focus = 'tasks'
                self._reset_calendar_create_flow()
                result = OrchestrationResult(status='clarification', message='Qual tarefa? Indique o número exibido na lista temporária.')
                self._complete_task()
                self._finalize_session_result(result)
                return result
        if tasks_request is not None and tasks_request['operation'] == 'add_reference':
            item = explicit_user_item(prior_user) if prior_user and self._previous_language_focus is None else None
            if item is None:
                self._reset_calendar_create_flow()
                result = OrchestrationResult(status='clarification', message='O que você quer adicionar à lista temporária? Diga a descrição da tarefa explicitamente.')
                self._complete_task()
                self._finalize_session_result(result)
                return result
            tasks_request = {'operation': 'add', 'text': item}
        if tasks_request is None and prohibited_action(command):
            self._reset_alias_flow()
            self._reset_delete_alias_flow()
            self._reset_replace_alias_flow()
            self._reset_unknown_target_flow()
            self._reset_open_app_flow()
            self._pending_clarification = None
            self._reset_calendar_create_flow()
            self._pending_note_selection = None
            result = OrchestrationResult(status='clarification', message='Não executei nem confirmei uma ação. Seu pedido contém uma negação ou condição; diga explicitamente o que deseja fazer.')
            self._complete_task()
            self._finalize_session_result(result)
            return result
        if tasks_request is not None:
            self._task_turn_ids.add(self.memory.turns[-1].turn_id)
            # Um novo comando explícito consome propostas anteriores, sem confirmá-las.
            self._reset_alias_flow()
            self._reset_delete_alias_flow()
            self._reset_replace_alias_flow()
            self._reset_unknown_target_flow()
            self._reset_calendar_create_flow()
            self._reset_open_app_flow()
            self._pending_note_selection = None
            self._pending_clarification = None
            result = self._handle_session_tasks(tasks_request)
            self._complete_task()
            self._finalize_session_result(result)
            self._task_turn_ids.add(self.memory.turns[-1].turn_id)
            return result

        # Cancelamento explícito consome a clarification pendente antes da IA
        cancelled_clarification = False
        if (
            self._pending_clarification is not None
            and not conversational_answer
            and language_control(command)
            in ("nao", "cancelar", "cancele", "cancela", "no")
        ):
            self._pending_clarification = None
            cancelled_clarification = True

        # Primeiro verifica se está no fluxo conversacional de substituir alias
        replace_alias_flow_result = self._handle_replace_alias_flow(command)
        if replace_alias_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(replace_alias_flow_result)
            return replace_alias_flow_result

        # Primeiro verifica se está no fluxo conversacional de excluir alias
        delete_alias_flow_result = self._handle_delete_alias_flow(command)
        if delete_alias_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(delete_alias_flow_result)
            return delete_alias_flow_result

        # Primeiro verifica se está no fluxo conversacional de adicionar alias
        alias_flow_result = self._handle_alias_flow(command)
        if alias_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(alias_flow_result)
            return alias_flow_result

        # Verifica se está no fluxo de alvo desconhecido
        unknown_target_flow_result = self._handle_unknown_target_flow(command)
        if unknown_target_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(unknown_target_flow_result)
            return unknown_target_flow_result

        reminder_result = self._handle_reminder_flow(command)
        if reminder_result is not None:
            self._complete_task()
            self._finalize_session_result(reminder_result)
            return reminder_result

        # Verifica se está no fluxo de criação de calendário
        calendar_create_flow_result = self._handle_calendar_create_flow(command)
        if calendar_create_flow_result is not None:
            snapshot = self._workflows.calendar_result(calendar_create_flow_result)
            if snapshot is not None:
                calendar_create_flow_result.message, calendar_create_flow_result.speech_message = render_workflow(snapshot)
            self._complete_task()
            self._finalize_session_result(calendar_create_flow_result)
            return calendar_create_flow_result
        if self._workflows.active:
            self._workflows.abandon()

        # Verifica se está no fluxo de abertura contextual (target vago)
        open_app_flow_result = self._handle_open_app_flow(command)
        if open_app_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(open_app_flow_result)
            return open_app_flow_result

        note_result = self._handle_search_followup(command, scope)
        if note_result is None:
            note_result = self._handle_note_reference(command, scope)
        if note_result is not None:
            self._complete_task()
            self._finalize_session_result(note_result)
            return note_result

        if conversational_answer and self.ai_core is None:
            self._complete_task()
            result = OrchestrationResult(status='success', message='Entendido.')
            self._finalize_session_result(result)
            return result
        if (self.confirmation_handler.evaluate_response(command.rstrip('.!?').strip()) is not None
                and not conversational_answer):
            if language_control(command) in {'cancela', 'cancelar', 'cancele'}:
                self._pending_clarification = None
                self._pending_note_selection = None
                self._pending_task_reference = None
                self._pending_search_summary = False
            self._complete_task()
            # "Não" a uma oferta da IA (que não deixa proposta) é só uma recusa educada.
            declined = language_control(command) in {'nao', 'nao obrigado'}
            result = OrchestrationResult(status='success' if cancelled_clarification or declined else 'cancelled', message=(
                'Desconsiderei a pergunta anterior. Nenhuma ação foi executada.' if cancelled_clarification else
                'Tudo bem.' if declined else
                'Não há uma proposta pendente para confirmar ou cancelar.'))
            self._finalize_session_result(result)
            return result

        # Consulta literal somente fora dos fluxos interativos; nunca concede permissão.
        if _is_first_message_query(command):
            self.memory.turns[-1].origin = "session_recall"
            first_message = self.memory.first_user_message()
            result = OrchestrationResult(
                status="success",
                message=("Sua primeira mensagem nesta sessão foi:\n" + first_message
                         if first_message is not None else
                         "Não há mensagem de usuário registrada nesta sessão."),
            )
            self._complete_task()
            self._finalize_session_result(result, session_recall=True)
            return result

        recall = recall_answer(list(self.memory.turns)[:-1], command)
        if recall is not None:
            self.memory.turns[-1].origin = "session_recall"
            result = OrchestrationResult(
                status="success", message=recall, speech_message=spoken_recall(recall),
            )
            self._complete_task()
            self._finalize_session_result(result, session_recall=True)
            return result

        if capabilities_request(command):
            self._complete_task()
            result = OrchestrationResult(
                status="success", message=self._capabilities_summary(),
                speech_message=self._spoken_capabilities(),
            )
            self._finalize_session_result(result)
            return result

        if email_capability_request(command):
            self._complete_task()
            message = ('Sim, senhor. O Gmail está habilitado no Therion. Posso consultar mensagens da conta '
                'autorizada quando o senhor pedir; verificarei a conexão nessa consulta.'
                if self._agent_config.get('enabled') is True and self._agent_config.get('gmail_enabled') is True
                else 'O Gmail está desativado no painel Capacidades, senhor. Não consultei mensagens.')
            result = OrchestrationResult(status='success', message=message)
            self._finalize_session_result(result)
            return result

        # Se o fluxo de abertura retornou uma Intent via variável auxiliar
        if self._pending_open_app_result is not None:
            intent = self._pending_open_app_result
            self._pending_open_app_result = None
            self.memory.record_intent(intent.action, intent.target)
        else:
            # --- IntentRecognizer primeiro (determinístico) ---
            intent = self.intent_recognizer.parse(command)
            intent = self._voice_opening_review(command, intent)
            if intent is not None:
                self._pending_clarification = None

        if intent is None and self.ai_core is not None:
            # Intent não reconhecida → consulta AICore/Ollama (diagnóstico detalhado)
            ai_context = self._build_ai_context(command)
            personal_snapshot_before_ai = (self._personal_snapshot
                if (ai_context.get('last_tool_evidence') or {}).get('kind') == 'personal_context' else None)
            outcome = self.ai_core.classify_detailed(command, ai_context)
            if personal_snapshot_before_ai is not None:
                sources, created = personal_snapshot_before_ai
                if (self._personal_snapshot is None or self._workflow_cancel_event.is_set()
                        or self._language_clock() - created > 300
                        or not all(source.valid(effective_roots(scope, self.second_brain.allowed_roots)) for source in sources)):
                    self._clear_personal_context()
                    self._complete_task()
                    result = OrchestrationResult(status='cancelled', message='As fontes pessoais mudaram ou o acesso foi revogado durante a resposta. Consulte o perfil novamente.')
                    self._finalize_session_result(result)
                    return result
            if 'selected_note_evidence' in ai_context:
                try:
                    self._knowledge_review.conversation_evidence(
                        self.second_brain, self._session_id, self._knowledge_read_roots)
                    if self._workflow_cancel_event.is_set():
                        raise KnowledgeError('Pedido cancelado.')
                except (KnowledgeError, OSError, ValueError, PermissionError):
                    self._knowledge_review.clear()
                    self._complete_task()
                    result = OrchestrationResult(status='cancelled', message=(
                        'A seleção de notas mudou, venceu ou foi revogada durante a resposta. '
                        'Selecione as fontes novamente; não exibi a interpretação anterior.'))
                    self._finalize_session_result(result)
                    return result
            ai_response = outcome.response

            # Uma recusa conversacional nunca vira pedido de ferramenta ou plano.
            if conversational_answer and language_control(command) in {'nao', 'nao obrigado'}:
                if ai_response is None or ai_response.type not in {'chat', 'clarification'}:
                    ai_response = AIResponse(type='chat', message='Tudo bem, deixo essa sugestão de lado.')
            if ai_response is not None and ai_response.type == CONTEXT_REQUEST:
                result = self._resolve_personal_context(ai_response.arguments['purpose'], command, scope,
                    ai_response.arguments.get('query', ''))
                self._complete_task()
                self._finalize_session_result(result)
                return result

            if ai_response is not None and ai_response.type == "action":
                if not self._ai_action_matches_request(command, ai_response):
                    self._complete_task()
                    result = OrchestrationResult(status='clarification', message='Não consegui validar essa interpretação sem adivinhar dados. Diga explicitamente a ação e os dados necessários.')
                    self._finalize_session_result(result)
                    return result
                self._pending_clarification = None
                intent = self._ai_response_to_intent(ai_response)
                self.memory.record_intent(intent.action, intent.target)
            elif ai_response is not None and ai_response.type == "plan_request":
                pending_msg = "Já existe um plano pendente nesta sessão."
                if self._plan_state.candidate is not None:
                    self._complete_task()
                    result = OrchestrationResult(
                        status="success",
                        message=pending_msg,
                    )
                    self._finalize_session_result(result)
                    return result
                plan, failure = self.ai_core.generate_plan_detailed(
                    command, ai_context
                )
                if failure is not None:
                    ai_status, ai_message = _AI_FAILURE_DIAGNOSTICS.get(
                        failure,
                        (_AI_INVALID_RESPONSE_STATUS, _AI_INVALID_RESPONSE_MESSAGE),
                    )
                    self.memory.record_error(ai_message)
                    self._complete_task()
                    result = OrchestrationResult(
                        status=ai_status,
                        message=ai_message,
                    )
                    self._finalize_session_result(result)
                    return result
                texto = self._render_plan_content(plan)
                if len(texto) > PLAN_TEXT_MAX_CHARS:
                    self._complete_task()
                    result = OrchestrationResult(
                        status="plan_too_large",
                        message=PLAN_TOO_LARGE_MESSAGE,
                    )
                    self._finalize_session_result(result)
                    return result
                candidate_id = self._plan_state.set_candidate(texto)
                if candidate_id is None:
                    self._complete_task()
                    result = OrchestrationResult(
                        status="success",
                        message=pending_msg,
                    )
                    self._finalize_session_result(result)
                    return result
                self._complete_task()
                result = OrchestrationResult(
                    status="success",
                    intent=None,
                    plan=None,
                    message=texto,
                    plan_candidate_id=candidate_id,
                )
                self._finalize_session_result(result)
                return result
            elif ai_response is not None and ai_response.type == "plan_reference":
                reference = ai_response.arguments["reference"]
                plan_id = self._plan_state.resolve_plan_reference(reference)
                self._complete_task()
                if plan_id is None:
                    result = OrchestrationResult(
                        status="plan_reference_unavailable",
                        message=(
                            "Não há um plano disponível nesta sessão para essa "
                            "referência."
                        ),
                        registered_plan_id=None,
                    )
                    self._finalize_session_result(result)
                    return result
                registered_plan = self._plan_state.get_plan(plan_id)
                result = OrchestrationResult(
                    status="success",
                    message=registered_plan.text,
                    registered_plan_id=plan_id,
                )
                self._finalize_session_result(result)
                return result
            elif ai_response is not None and ai_response.type in ("chat", "clarification"):
                from therion.context.response_style import normalize_model_greeting
                ai_response = replace(ai_response, message=normalize_model_greeting(command, ai_response.message))
                from therion.agent.claims import unsupported_claim
                if unsupported_claim(ai_response.message,[]):
                    self._complete_task()
                    result=OrchestrationResult(status='clarification',message='Não há execução verificada para confirmar essa ação. Diga o pedido e o aplicativo; nenhuma ação foi executada por esta resposta.')
                    self._finalize_session_result(result)
                    return result
                # Uma pergunta escrita pelo modelo não é uma proposta executável.
                # Somente o fluxo de catálogo pode apresentar a abertura pendente.
                if (re.search(r'\b(?:posso|vou|irei)\s+abrir\b', ai_response.message, re.I)
                        and '?' in ai_response.message):
                    self._pending_clarification = None
                    self._complete_task()
                    result = OrchestrationResult(status='clarification', message=(
                        'Ainda não preparei uma abertura. Diga “Abra” seguido do nome '
                        'cadastrado em Autonomia → Aplicativos.'))
                    self._finalize_session_result(result)
                    return result
                if (self._last_tool_evidence or {}).get('kind') == 'personal_context':
                    if ai_response.type == 'chat':
                        description = self._describe_read_result(command, self._last_tool_evidence,
                            'Não consegui interpretar essas fontes agora. Reformule a pergunta ou consulte o perfil novamente.')
                        ai_response = AIResponse(type='chat', message=description)
                    if self._workflow_cancel_event.is_set() or not self._personal_sources_valid(scope):
                        self._clear_personal_context()
                        self._complete_task()
                        result = OrchestrationResult(status='cancelled', message='O contexto pessoal mudou ou ficou indisponível durante a resposta. Consulte as fontes novamente.')
                        self._finalize_session_result(result)
                        return result
                    self._personal_reply_active = True
                if ai_response.type == "clarification":
                    self._set_pending_clarification(ai_response.message)
                else:
                    self._pending_clarification = None
                self._complete_task()
                result = OrchestrationResult(
                    status="success",
                    message=ai_response.message,
                )
                self._finalize_session_result(result)
                return result
            elif outcome.failure is not None:
                ai_status, ai_message = _AI_FAILURE_DIAGNOSTICS.get(
                    outcome.failure,
                    (_AI_INVALID_RESPONSE_STATUS, _AI_INVALID_RESPONSE_MESSAGE),
                )
                self.memory.record_error(ai_message)
                self._complete_task()
                result = OrchestrationResult(
                    status=ai_status,
                    message=ai_message,
                )
                self._finalize_session_result(result)
                return result
        if not intent:
            # unknown_intent: somente recognizer sem match e sem diagnóstico de IA
            msg = "Não consegui identificar a intenção no comando recebido."
            self.memory.record_error(msg)
            self._complete_task()
            result = OrchestrationResult(
                status="unknown_intent",
                message=msg,
            )
            self._finalize_session_result(result)
            return result

        # Registra o alvo original para auditoria
        self.memory.record_intent(intent.action, intent.target)

        # Tratamento especial para listagem de aliases (somente leitura)
        if intent.action == "listar aliases":
            aliases = self.alias_manager.list_aliases()
            if aliases:
                lines = [f"- {alias} → {target}" for alias, target in aliases.items()]
                message = "Aliases cadastrados:\n" + "\n".join(lines)
            else:
                message = "Nenhum alias cadastrado."
            summary = self._describe_read_result(command,
                {'kind': 'aliases', 'aliases': dict(list(aliases.items())[:20]), 'partial': len(aliases) > 20},
                f"Consultei seus aliases. Você tem {len(aliases)} cadastrado(s).")
            self.memory.record_context_query(path="aliases", success=True)
            self._complete_task()
            result = OrchestrationResult(
                status="success",
                intent=intent,
                message=summary + "\n\n" + message,
                speech_message=summary,
            )
            self._finalize_session_result(result)
            return result

        # Tratamento especial para iniciar fluxo de excluir alias
        if intent.action == "excluir alias":
            self._delete_alias_flow_step = "awaiting_alias"
            self._complete_task()
            result = OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                message="Qual alias você quer excluir?",
            )
            self._finalize_session_result(result)
            return result

        # Tratamento especial para iniciar fluxo de substituir alias
        if intent.action == "substituir alias":
            self._replace_alias_flow_step = "awaiting_alias"
            self._complete_task()
            result = OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                message="Qual alias você quer substituir?",
            )
            self._finalize_session_result(result)
            return result

        # Tratamento especial para iniciar fluxo de adicionar alias
        if intent.action == "adicionar alias":
            self._alias_flow_step = "awaiting_keyword"
            self._complete_task()
            result = OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                message="Qual palavra ou expressão você quer usar como alias?",
            )
            self._finalize_session_result(result)
            return result

        # Tratamento especial para consulta ao Segundo Cérebro (somente leitura)
        if intent.action == "consultar segundo cérebro":
            orchestration_result = self._read_note_result(intent.target, command, scope)
            orchestration_result.intent = intent
            self._complete_task()
            self._finalize_session_result(orchestration_result)
            return orchestration_result

        # Tratamento especial para busca no Segundo Cérebro (somente leitura)
        if intent.action == "buscar segundo cérebro":
            self._knowledge_review.clear()
            # Pontuação da frase não faz parte do termo, seja ele reconhecido
            # pelo parser local ou retornado pela IA. Preservar pontos internos.
            intent.target = search_term(intent.target).rstrip('.!?').strip()
            self._search_snapshot = None
            self._pending_search_summary = False
            self._note_results = NoteResults((), ())
            self._recent_note_index = None
            self._pending_note_selection = None
            search_roots = tuple(_canonical(root) for root in effective_roots(scope, self.second_brain.allowed_roots))
            trace = SearchTrace()
            try:
                results = self.second_brain.search_notes(intent.target, scope=scope, trace=trace)
            except Exception:
                self._last_tool_evidence = {'kind': 'search', 'matches': [], 'partial': True}
                self._complete_task()
                failure = OrchestrationResult(status='execution_failed', message='Não consegui concluir a busca no Segundo Cérebro. Tente novamente.')
                self._finalize_session_result(failure)
                return failure
            self._note_results = NoteResults(tuple(r.path for r in results), search_roots)
            self._note_results_created = self._language_clock()
            self._language_focus = 'notes'
            for root in trace.used_roots:
                used_root = self._audit_relative_root(root)
                if used_root is not None:
                    self.memory.add_used_root(used_root)
            self._complete_task()
            if not results:
                self._last_tool_evidence = {'kind': 'search', 'term': intent.target, 'matches': []}
                orchestration_result = OrchestrationResult(
                    status="success",
                    intent=intent,
                    message=f"Busquei no Segundo Cérebro, mas não encontrei resultados para '{intent.target}' no escopo permitido.",
                )
            else:
                evidence = {'kind': 'search', 'term': intent.target, 'partial': True,
                            'matches': [{'path': r.path, 'snippet': (getattr(r, 'context', '') or r.snippet)[:700],
                                         'formation_context': getattr(r, 'formation_context', ''),
                                         'version': getattr(r, 'version', '')} for r in results[:5]]}
                fallback = f"Encontrei {len(results)} registro(s) no Segundo Cérebro sobre '{intent.target}'. Posso resumir os trechos encontrados para você."
                summary = self._describe_read_result(command, evidence, fallback)
                self._search_snapshot = (evidence, self._note_results, self._language_clock())
                self._pending_search_summary = bool(re.search(
                    r'(?:quer|posso|gostaria|deseja).{0,50}resum', language_control(summary)))
                try:
                    self.second_brain._check_access()
                except PermissionError:
                    self._last_tool_evidence = None
                    result = OrchestrationResult(status='cancelled', message='A política de leitura mudou durante a busca. Não exibi os resultados.')
                    self._finalize_session_result(result)
                    return result
                lines = [
                    f"{i + 1}. {r.path}" + (f'\n   {r.snippet}' if summary == fallback else '')
                    for i, r in enumerate(results)
                ]
                message = (
                    summary + "\n\nRegistros encontrados:\n"
                    + "\n".join(lines)
                    + f"\n\n{len(results)} resultado(s) encontrado(s)."
                )
                orchestration_result = OrchestrationResult(
                    status="success",
                    intent=intent,
                    message=message,
                    speech_message=summary,
                )
            self._finalize_session_result(orchestration_result)
            return orchestration_result

        # Tratamento especial para consulta de calendário (somente leitura)
        if intent.action in {"calendário hoje", "consultar agenda"}:
            calendar_result = (self._handle_calendar_today(intent) if intent.action == 'calendário hoje'
                               else self._handle_calendar_query(intent, intent.entities or {}))
            self.memory.record_context_query(path="calendario_hoje" if intent.action == 'calendário hoje' else 'calendario_consulta',
                                             success=calendar_result.status == 'success')
            self._complete_task()
            self._finalize_session_result(calendar_result)
            return calendar_result

        # Tratamento especial para planejar dia (Skill SKILL-002, somente leitura)
        if intent.action == "planejar dia":
            try:
                skill_cls = get_skill("SKILL-002")
            except KeyError:
                self._complete_task()
                result = OrchestrationResult(
                    status="execution_failed",
                    intent=intent,
                    message="Skill de planejamento não disponível.",
                )
                self._finalize_session_result(result)
                return result
            try:
                skill = skill_cls(
                    calendar=self.calendar_adapter,
                    second_brain=self.second_brain,
                )
                now = self._calendar_now()
                skill_result = skill.execute(today=now.date(), now=now)
            except Exception as err:
                self._complete_task()
                result = OrchestrationResult(
                    status="execution_failed",
                    intent=intent,
                    message=f"Erro ao executar planejamento: {err}",
                )
                self._finalize_session_result(result)
                return result
            status_map = {
                "success": "success",
                "partial": "success",
                "unavailable": "execution_failed",
            }
            result = OrchestrationResult(
                status=status_map.get(skill_result.status, "execution_failed"),
                intent=intent,
                message=skill_result.message,
            )
            self._complete_task()
            self._finalize_session_result(result)
            return result

        # Tratamento especial para criar evento
        if intent.action == "criar evento calendário":
            entities = intent.entities or {}
            self._pending_event_draft = {
                "duration_minutes": 60
            }
            self._merge_event_fields(self._pending_event_draft, {key: value for key, value in entities.items()
                if key in {'title', 'date', 'start_time', 'end_time', 'duration_minutes', 'duration_explicit', '_issues'}})
                
            draft = self._pending_event_draft
            if "title" not in draft:
                msg = "Qual é o título do evento?"
            elif "date" not in draft:
                msg = "Para qual data?"
            elif "start_time" not in draft:
                msg = "A que horas?"
            else:
                result = self._present_calendar_summary()
                self._complete_task()
                self._finalize_session_result(result)
                return result
                
            self._complete_task()
            result = OrchestrationResult(status="awaiting_confirmation", intent=intent, message=msg)
            self._finalize_session_result(result)
            return result

        # Resolve alias antes da verificação de permissão
        resolved_target = self.alias_manager.resolve(intent.target)
        # Cria nova Intent com alvo resolvido (não muta a original)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
            requires_confirmation=intent.requires_confirmation,
        )

        # Verificar se target é vago ("isso"/"aquilo") — iniciar fluxo de abertura contextual
        if (intent.action == "abrir aplicativo"
                and intent.target.lower() in IntentRecognizer.VAGUE_TARGETS):
            self._open_app_flow_active = True
            self._pending_open_app_target = intent.target
            self.memory.record_awaiting_confirmation()
            self._complete_task()
            result = OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                message="Qual aplicativo você quer abrir?",
            )
            self._finalize_session_result(result)
            return result

        catalog_result = self._catalog_request(intent, resolved_target)
        if catalog_result is not None:
            if catalog_result.status in {'awaiting_confirmation','unknown_intent','forbidden'}:
                self._complete_task()
                self._finalize_session_result(catalog_result)
            return catalog_result

        if not self.permission_manager.is_allowed(resolved_intent):
            # Alvo desconhecido: abrir aplicativo, sem alias resolvido, não autorizado
            if (intent.action == "abrir aplicativo"
                    and resolved_target == intent.target
                    and resolved_target not in self.permission_manager.ALLOWED_TARGETS):
                self._unknown_target_flow_step = "awaiting_explanation"
                self._pending_unknown_original = intent.target
                self._pending_unknown_explained = None
                self.memory.record_awaiting_confirmation()
                self._complete_task()
                result = OrchestrationResult(
                    status="awaiting_confirmation",
                    intent=intent,
                    message=f"Não reconheci '{intent.target}'. O que isso significa?",
                )
                self._finalize_session_result(result)
                return result
            msg = f"Ação '{resolved_intent.action}' para o alvo '{resolved_intent.target}' não está autorizada pela governança da V0."
            self.memory.record_error(msg)
            self._complete_task()
            result = OrchestrationResult(
                status="forbidden",
                intent=intent,  # Registra intent original na resposta
                message=msg,
            )
            self._finalize_session_result(result)
            return result

        plan = self.planner.create_plan(resolved_intent)
        self._pending_action_plan = plan
        self._pending_action_fingerprint = self._plan_fingerprint(plan)
        self.memory.record_plan(plan.steps)

        if self.permission_manager.requires_confirmation(intent):
            self.memory.record_awaiting_confirmation()
            steps_formatted = "\n".join(
                f"{i + 1}. {step}" for i, step in enumerate(plan.steps)
            )
            message = (
                f"Posso realizar esta ação após sua confirmação: {intent.action}\n"
                f"Alvo: {intent.target}\n\n"
                f"Plano:\n{steps_formatted}\n\n"
                "Esta ação exige confirmação.\n"
                "Continuar? [s/n]"
            )
            result = OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                plan=plan,
                message=message,
            )
            self._finalize_session_result(result)
            return result

        result = self.confirm_and_execute(plan, confirmed=True)
        self._finalize_session_result(result)
        return result

    @staticmethod
    def _render_plan_content(plan: PlanContent) -> str:
        """Converte PlanContent em texto final, sem alterar nem truncar."""
        parts: list[str] = []
        if plan.title is not None and plan.title != "":
            parts.append(plan.title)
        for section in plan.sections:
            heading = "Pausa" if section.block_type == "break" else section.heading
            if section.duration_minutes is not None:
                heading += f" — {section.duration_minutes} minutos"
            body = "Levante-se, alongue-se e descanse." if section.block_type == "break" else section.body
            parts.append(heading + "\n" + body)
        return "\n\n".join(parts)

    def ack_plan_displayed(self, candidate_id: str) -> PlanAckResult:
        """Registra o candidate exibido como plano da sessão (ACK)."""
        return self._plan_state.register_candidate(candidate_id)

    def ack_registered_plan_displayed(self, plan_id: str) -> bool:
        """Reconhece a exibição de um plano já registrado (ACK M6)."""
        return self._plan_state.ack_registered_plan_displayed(plan_id)

    def confirm_and_execute(
        self, plan: Plan, confirmed: bool, simulate: Optional[bool] = None
    ) -> OrchestrationResult:
        with self._operation_lock:
            if self._pending_memory_plan is not None:
                confirmation=self._confirmation_id
                self._agent_begin_legacy(confirmation)
                try:result=self._confirm_memory_save(plan,confirmed)
                except BaseException:
                    self._agent_finish_legacy(confirmation);raise
                self._agent_finish_legacy(confirmation,result)
                return result
            if (plan is None or plan is not self._pending_action_plan
                    or self._plan_fingerprint(plan) != self._pending_action_fingerprint):
                return self._stale_confirmation()
            confirmation=self._confirmation_id
            self._agent_begin_legacy(confirmation)
            self._pending_action_plan = None
            self._pending_action_fingerprint = None
            self._confirmation_id = None
            try:result=self._confirm_and_execute(plan, confirmed, simulate)
            except BaseException:
                self._agent_finish_legacy(confirmation);raise
            self._agent_finish_legacy(confirmation,result)
            return result

    def _confirm_and_execute(
        self, plan: Plan, confirmed: bool, simulate: Optional[bool] = None
    ) -> OrchestrationResult:
        """Executa ou cancela a ação conforme a decisão do usuário, registrando na memória."""
        self.memory.record_confirmation(confirmed)

        if not confirmed:
            self._pending_catalog_app = None
            self._pending_close_app = None
            self._pending_catalog_decision = None
            msg = "Operação cancelada pelo usuário."
            self._complete_task()
            result = OrchestrationResult(
                status="cancelled",
                intent=plan.intent,
                plan=plan,
                message=msg,
            )
            self._finalize_session_result(result)
            return result

        is_simulated = self.simulate if simulate is None else simulate

        close_result=self._execute_close(plan,is_simulated)
        if close_result is not None:
            self.memory.record_execution_result(close_result.message,success=close_result.status=='success')
            self._complete_task();self._finalize_session_result(close_result)
            return close_result

        catalog_result = self._execute_catalog(plan, is_simulated)
        if catalog_result is not None:
            return catalog_result

        if is_simulated:
            exec_msg = self.executor.execute_simulated(plan.intent)
            verif_msg = self.verifier.verify_simulated(plan.intent)
            self.memory.record_execution_result(exec_msg, success=True)
            self.memory.record_verification_result(verif_msg, success=True)
            self._complete_task()
            result = OrchestrationResult(
                status="executed_simulated",
                intent=plan.intent,
                plan=plan,
                message=f"Simulei esta ação; não executei a operação de verdade.\n{exec_msg}\n{verif_msg}",
            )
            self._finalize_session_result(result)
            return result

        # Execução Real no Windows
        exec_result = self.executor.execute_real(plan.intent)
        if not exec_result.success:
            self.memory.record_execution_result(exec_result.message, success=False)
            self.memory.record_error(exec_result.message)
            self._complete_task()
            result = OrchestrationResult(
                status="execution_failed",
                intent=plan.intent,
                plan=plan,
                message=f"Não consegui concluir a ação: {exec_result.message}",
            )
            self._finalize_session_result(result)
            return result

        self.memory.record_execution_result(exec_result.message, success=True)

        verif_result = self.verifier.verify_real(plan.intent)
        if not verif_result.success:
            self._offer_verified_memory_result('action_verification_failed')
            self.memory.record_verification_result(verif_result.message, success=False)
            self.memory.record_error(verif_result.message)
            self._complete_task()
            result = OrchestrationResult(
                status="verification_failed",
                intent=plan.intent,
                plan=plan,
                message=f"Tentei executar a ação, mas não consegui confirmar o resultado.\n{exec_result.message}\nAlerta de verificação: {verif_result.message}",
            )
            self._finalize_session_result(result)
            return result

        self.memory.record_verification_result(verif_result.message, success=True)
        self._complete_task()
        result = OrchestrationResult(
            status="success",
            intent=plan.intent,
            plan=plan,
            message=f"Concluí a ação e confirmei o resultado.\n{exec_result.message}\n{verif_result.message}",
        )
        self._finalize_session_result(result)
        return result
