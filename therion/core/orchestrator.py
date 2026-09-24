"""Módulo central de orquestração da V0 com integração à memória de trabalho."""

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from therion.actions.executor import ActionExecutor
from therion.actions.verifier import ActionVerifier
from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.config import AliasManager
from therion.context.read_scope import ReadScope, effective_roots
from therion.context.second_brain import ReadResult, SearchTrace, SecondBrainReader
from therion.core.ai_core import AICore
from therion.core.intent import Intent, IntentRecognizer
from therion.core.planner import Plan, Planner
from therion.governance.confirmation import ConfirmationHandler
from therion.governance.permissions import PermissionManager
from therion.logging.audit import AuditLogger
from therion.memory.working_memory import WorkingMemory
from therion.skills.registry import get_skill


_DURATION_RE = re.compile(
    r'(\d+)\s*(horas?|h|min(?:utos?)?)',
    re.IGNORECASE,
)

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
_AI_INVALID_RESPONSE_MESSAGE = "A resposta da IA auxiliar não pôde ser validada."

# Motivo interno (ClassifyOutcome.failure) → status externo + mensagem não técnica.
_AI_FAILURE_DIAGNOSTICS: dict[str, tuple[str, str]] = {
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


class Orchestrator:
    """Orquestrador do ciclo básico da V0 integrado à memória de trabalho da sessão."""

    def __init__(
        self,
        simulate: bool = False,
        log_dir: Optional[str] = None,
        vault_root: Optional[str] = None,
        calendar_adapter: Optional[CalendarAdapter] = None,
        ai_core: Optional[AICore] = None,
    ) -> None:
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
        self.calendar_adapter = calendar_adapter
        self.ai_core = ai_core
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
        # Estado do fluxo de abertura contextual (target vago)
        self._open_app_flow_active: bool = False
        self._pending_open_app_target: Optional[str] = None
        self._pending_open_app_result: Optional[Intent] = None
        self._scope_note: str = ""
        self._pending_clarification: Optional[str] = None

    def _complete_task(self) -> None:
        """Conclui a tarefa na memória de trabalho e audita o registro."""
        if self.memory.current_task:
            try:
                self.audit_logger.log_task(self.memory.current_task)
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

    def _reset_open_app_flow(self) -> None:
        """Limpa o estado do fluxo de abertura contextual."""
        self._open_app_flow_active = False
        self._pending_open_app_target = None
        self._pending_open_app_result = None

    def _set_pending_clarification(self, question: str) -> None:
        """Armazena a pergunta de clarification pendente, limitada a 500 caracteres."""
        cleaned = question.strip()
        self._pending_clarification = cleaned[:_PENDING_CLARIFICATION_MAX]

    def clear_session(self) -> None:
        """Limpa a clarification pendente e o contexto de sessão da memória."""
        self._pending_clarification = None
        self.memory.clear_session()

    def _parse_event_datetimes(self, draft: dict) -> tuple[datetime, datetime]:
        """Converte data/hora do rascunho em datetimes timezone-aware.

        Returns:
            Tupla (start, end) com fuso horário configurado.

        Raises:
            CalendarError: Se data ou hora não puderem ser interpretadas.
        """
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Sao_Paulo")
        now = self._now_func() if self._now_func else datetime.now(tz)

        # --- Data ---
        raw_date = draft.get("date", "").strip().lower()
        if raw_date in ("hoje", ""):
            target_date = now.date()
        elif raw_date == "amanhã":
            target_date = now.date() + timedelta(days=1)
        else:
            m = re.match(r'^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$', raw_date)
            if not m:
                raise CalendarError(f"Data não reconhecida: '{draft['date']}'.")
            day, month = int(m.group(1)), int(m.group(2))
            year = int(m.group(3)) if m.group(3) else now.year
            target_date = date(year, month, day)

        # --- Hora ---
        raw_time = draft.get("start_time", "").strip()
        tm = re.search(r'(\d{1,2})(?:h|:(\d{2}))?', raw_time, re.IGNORECASE)
        if not tm:
            raise CalendarError(f"Hora não reconhecida: '{draft['start_time']}'.")
        hour = int(tm.group(1))
        minute = int(tm.group(2) or 0)

        start = datetime(target_date.year, target_date.month, target_date.day,
                         hour, minute, tzinfo=tz)
        duration = draft.get("duration_minutes", 60)
        end = start + timedelta(minutes=duration)

        return start, end

    def _format_calendar_event(self, event, index: int) -> str:
        """Formata um evento de calendário para exibição."""
        if event.all_day:
            time_str = "Dia inteiro"
        else:
            start = event.start
            time_str = f"{start.hour:02d}:{start.minute:02d}"
        return f"{index}. {event.summary} — {time_str}"

    def _handle_calendar_today(self, intent: Intent) -> OrchestrationResult:
        """Processa consulta de eventos de hoje (somente leitura, sem confirmação)."""
        if self.calendar_adapter is None:
            return OrchestrationResult(
                status="success",
                intent=intent,
                message="Calendário não disponível.",
            )
        try:
            today = date.today()
            events = self.calendar_adapter.list_events_for_day(today)
        except CalendarError as err:
            return OrchestrationResult(
                status="execution_failed",
                intent=intent,
                message=f"Erro ao acessar calendário: {err}",
            )
        if not events:
            return OrchestrationResult(
                status="success",
                intent=intent,
                message="Nenhum evento para hoje.",
            )

        def _sort_key(e):
            if isinstance(e.start, datetime):
                return e.start
            return datetime.combine(e.start, datetime.min.time())

        events.sort(key=_sort_key)
        lines = [
            self._format_calendar_event(evt, i + 1)
            for i, evt in enumerate(events)
        ]
        return OrchestrationResult(
            status="success",
            intent=intent,
            message="Eventos de hoje:\n" + "\n".join(lines),
        )

    def _finalize_session_result(self, result: OrchestrationResult) -> None:
        """Registra turno do Therion e atualiza contexto operacional na sessão."""
        if self._scope_note:
            if result.message:
                result.message = f"{result.message}\n\n{self._scope_note}"
            else:
                result.message = self._scope_note
        self.memory.add_turn("therion", result.message)
        self.memory.last_result = result.message
        self.memory.last_status = result.status
        if result.intent is not None:
            self.memory.last_intent = result.intent.action
            self.memory.last_target = result.intent.target
        self._scope_note = ""

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
                result = self.alias_manager.replace_alias(alias, new_target, confirm=True)
                self._reset_replace_alias_flow()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Alias atualizado com sucesso.",
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
                result = self.alias_manager.remove_alias(alias, confirm=True)
                self._reset_delete_alias_flow()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Alias removido com sucesso.",
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
                result = self.alias_manager.add_alias(
                    self._pending_alias_keyword, 
                    self._pending_alias_target
                )
                self._reset_alias_flow()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message="Alias adicionado com sucesso.",
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
                result = self.alias_manager.add_alias(original, explained)
                self._reset_unknown_target_flow()
                if result.success:
                    return OrchestrationResult(
                        status="success",
                        message=f"Alias '{original}' → '{explained}' salvo com sucesso.",
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

    def _format_time_range(self, start_time_str: str) -> str:
        import re
        match = re.search(r'(\d{1,2})(?:h|:(\d{2}))?', start_time_str, re.IGNORECASE)
        if match:
            h = int(match.group(1))
            m = int(match.group(2) or 0)
            end_h = (h + 1) % 24
            return f"{h:02d}:{m:02d}–{end_h:02d}:{m:02d}"
        return f"{start_time_str} (duração 1h)"

    def _present_calendar_summary(self, ambiguous: bool = False) -> OrchestrationResult:
        draft = self._pending_event_draft
        prefix = "Resposta ambígua.\n\n" if ambiguous else ""
        time_display = self._format_time_range(draft['start_time'])
        message = (
            f"{prefix}Vou criar:\n"
            f"Título: {draft['title']}\n"
            f"Data: {draft['date']}\n"
            f"Horário: {time_display}\n\n"
            f"Confirmar? [s/n]"
        )
        return OrchestrationResult(status="awaiting_confirmation", message=message)

    def _handle_calendar_create_flow(self, command: str) -> Optional[OrchestrationResult]:
        """Processa o fluxo conversacional de criar evento."""
        if self._pending_event_draft is None:
            return None
            
        cleaned = command.strip()
        draft = self._pending_event_draft
        
        is_complete = "title" in draft and "date" in draft and "start_time" in draft
        
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

            # D. Resposta comum — preencher próximo campo faltante
            if "title" not in draft:
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

        import re
        is_correction = False
        
        time_match = re.search(r'(?:mude|troque|para)\s+(?:as|às)?\s*(\d{1,2}(?:h|:\d{2})?)', cleaned, re.IGNORECASE)
        date_match = re.search(r'(?:mude|troque|para)\s+(amanhã|hoje|dia\s+\d+|\d{1,2}/\d{1,2})', cleaned, re.IGNORECASE)
        title_match = re.search(r'(?:o\s+nome\s+é|título\s+é|mude\s+o\s+título\s+para)\s+(.+)', cleaned, re.IGNORECASE)
        
        if time_match:
            draft['start_time'] = time_match.group(1)
            is_correction = True
        if date_match:
            draft['date'] = date_match.group(1)
            is_correction = True
        if title_match:
            draft['title'] = title_match.group(1).strip().capitalize()
            is_correction = True
            
        if is_correction:
            return self._present_calendar_summary()
            
        confirmation = self.confirmation_handler.evaluate_response(cleaned)
        if confirmation is True:
            if self.calendar_adapter is None:
                self._reset_calendar_create_flow()
                return OrchestrationResult(
                    status="execution_failed",
                    message="Calendário não disponível.",
                )
            try:
                start, end = self._parse_event_datetimes(draft)
            except CalendarError as err:
                self._reset_calendar_create_flow()
                return OrchestrationResult(
                    status="execution_failed",
                    message=f"Erro ao preparar evento: {err}",
                )
            try:
                event = self.calendar_adapter.create_event(
                    summary=draft["title"],
                    start=start,
                    end=end,
                )
            except CalendarError as err:
                self._reset_calendar_create_flow()
                return OrchestrationResult(
                    status="execution_failed",
                    message=f"Erro ao criar evento: {err}",
                )
            self._reset_calendar_create_flow()
            return OrchestrationResult(
                status="success",
                message=(
                    f"Evento criado:\n"
                    f"{event.summary} — "
                    f"{start.strftime('%d/%m/%Y %H:%M')}–{end.strftime('%H:%M')}"
                ),
            )
        elif confirmation is False:
            self._reset_calendar_create_flow()
            return OrchestrationResult(status="cancelled", message="Operação cancelada pelo usuário.")
        else:
            return self._present_calendar_summary(ambiguous=True)

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

    def _build_ai_context(self, command: str = "") -> dict:
        """Cria snapshot somente leitura do contexto para o AICore."""
        recent = [
            {"role": t.role, "text": t.text}
            for t in self.memory.recent_turns(5)
        ]
        ctx = {
            "recent_turns": recent,
            "last_intent": self.memory.last_intent,
            "last_target": self.memory.last_target,
            "last_status": self.memory.last_status,
            "last_result_summary": (
                self.memory.last_result[:200]
                if self.memory.last_result
                else None
            ),
        }
        budget = _extract_pomodoro_budget(command, recent)
        if budget is not None:
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

    def process_command(self, command: str) -> OrchestrationResult:
        """Processa um comando textual registrando todas as etapas na memória de trabalho."""
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
        self.memory.start_task(command=command, execution_mode=mode)
        self.memory.add_turn("user", command)
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

        # Cancelamento explícito consome a clarification pendente antes da IA
        if (
            self._pending_clarification is not None
            and command.strip().lower()
            in ("não", "nao", "cancelar", "cancele", "cancela", "no")
        ):
            self._pending_clarification = None

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

        # Verifica se está no fluxo de criação de calendário
        calendar_create_flow_result = self._handle_calendar_create_flow(command)
        if calendar_create_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(calendar_create_flow_result)
            return calendar_create_flow_result

        # Verifica se está no fluxo de abertura contextual (target vago)
        open_app_flow_result = self._handle_open_app_flow(command)
        if open_app_flow_result is not None:
            self._complete_task()
            self._finalize_session_result(open_app_flow_result)
            return open_app_flow_result

        # Se o fluxo de abertura retornou uma Intent via variável auxiliar
        if self._pending_open_app_result is not None:
            intent = self._pending_open_app_result
            self._pending_open_app_result = None
            self.memory.record_intent(intent.action, intent.target)
        else:
            # --- IntentRecognizer primeiro (determinístico) ---
            intent = self.intent_recognizer.parse(command)
            if intent is not None:
                self._pending_clarification = None

        if intent is None and self.ai_core is not None:
            # Intent não reconhecida → consulta AICore/Ollama (diagnóstico detalhado)
            ai_context = self._build_ai_context(command)
            outcome = self.ai_core.classify_detailed(command, ai_context)
            ai_response = outcome.response

            if ai_response is not None and ai_response.type == "action":
                self._pending_clarification = None
                intent = self._ai_response_to_intent(ai_response)
                self.memory.record_intent(intent.action, intent.target)
            elif ai_response is not None and ai_response.type in ("chat", "clarification"):
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
            self.memory.record_context_query(path="aliases", success=True)
            self._complete_task()
            result = OrchestrationResult(
                status="success",
                intent=intent,
                message=message,
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
            result = self.read_context(intent.target, scope)
            if result.success and result.matched_root is not None:
                used_root = self._audit_relative_root(result.matched_root)
                if used_root is not None:
                    self.memory.add_used_root(used_root)
            self._complete_task()
            if result.success:
                orchestration_result = OrchestrationResult(
                    status="success",
                    intent=intent,
                    message=result.content,
                )
            else:
                orchestration_result = OrchestrationResult(
                    status="execution_failed",
                    intent=intent,
                    message=result.error,
                )
            self._finalize_session_result(orchestration_result)
            return orchestration_result

        # Tratamento especial para busca no Segundo Cérebro (somente leitura)
        if intent.action == "buscar segundo cérebro":
            trace = SearchTrace()
            results = self.second_brain.search_notes(intent.target, scope=scope, trace=trace)
            for root in trace.used_roots:
                used_root = self._audit_relative_root(root)
                if used_root is not None:
                    self.memory.add_used_root(used_root)
            self._complete_task()
            if not results:
                orchestration_result = OrchestrationResult(
                    status="success",
                    intent=intent,
                    message=f"Nenhum resultado encontrado para '{intent.target}'.",
                )
            else:
                lines = [
                    f"{i + 1}. {r.path}\n   {r.snippet}"
                    for i, r in enumerate(results)
                ]
                message = (
                    f"Resultados da busca por '{intent.target}':\n"
                    + "\n".join(lines)
                    + f"\n\n{len(results)} resultado(s) encontrado(s)."
                )
                orchestration_result = OrchestrationResult(
                    status="success",
                    intent=intent,
                    message=message,
                )
            self._finalize_session_result(orchestration_result)
            return orchestration_result

        # Tratamento especial para consulta de calendário (somente leitura)
        if intent.action == "calendário hoje":
            calendar_result = self._handle_calendar_today(intent)
            self.memory.record_context_query(path="calendario_hoje", success=True)
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
                skill_result = skill.execute()
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
            if "title" in entities:
                self._pending_event_draft["title"] = entities["title"]
            if "date" in entities:
                self._pending_event_draft["date"] = entities["date"]
            if "start_time" in entities:
                self._pending_event_draft["start_time"] = entities["start_time"]
                
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
        self.memory.record_plan(plan.steps)

        if self.permission_manager.requires_confirmation(intent):
            self.memory.record_awaiting_confirmation()
            steps_formatted = "\n".join(
                f"{i + 1}. {step}" for i, step in enumerate(plan.steps)
            )
            message = (
                f"Intenção identificada: {intent.action}\n"
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

    def confirm_and_execute(
        self, plan: Plan, confirmed: bool, simulate: Optional[bool] = None
    ) -> OrchestrationResult:
        """Executa ou cancela a ação conforme a decisão do usuário, registrando na memória."""
        self.memory.record_confirmation(confirmed)

        if not confirmed:
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
                message=f"{exec_msg}\n{verif_msg}",
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
                message=f"Falha na execução: {exec_result.message}",
            )
            self._finalize_session_result(result)
            return result

        self.memory.record_execution_result(exec_result.message, success=True)

        verif_result = self.verifier.verify_real(plan.intent)
        if not verif_result.success:
            self.memory.record_verification_result(verif_result.message, success=False)
            self.memory.record_error(verif_result.message)
            self._complete_task()
            result = OrchestrationResult(
                status="verification_failed",
                intent=plan.intent,
                plan=plan,
                message=f"{exec_result.message}\nAlerta de verificação: {verif_result.message}",
            )
            self._finalize_session_result(result)
            return result

        self.memory.record_verification_result(verif_result.message, success=True)
        self._complete_task()
        result = OrchestrationResult(
            status="success",
            intent=plan.intent,
            plan=plan,
            message=f"{exec_result.message}\n{verif_result.message}",
        )
        self._finalize_session_result(result)
        return result
