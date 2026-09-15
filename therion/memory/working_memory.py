"""Memória de trabalho volátil da sessão e da tarefa (V0/V1)."""

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class TaskContext:
    """Contexto em memória de uma tarefa específica durante a sessão."""

    task_id: str = ""
    command: str = ""
    intent: Optional[str] = None
    target: Optional[str] = None
    plan_steps: List[str] = field(default_factory=list)
    confirmation_status: str = "nao_requerida"  # "aguardando", "confirmado", "cancelado", "nao_requerida"
    execution_mode: str = "simulado"  # "simulado" ou "real"
    execution_result: Optional[str] = None
    verification_result: Optional[str] = None
    error: Optional[str] = None
    task_status: str = "pendente"  # "iniciada", "aguardando_confirmacao", "concluido", "falhou", "cancelado"
    context_queries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Retorna representação em dicionário em memória para inspeção e depuração."""
        return {
            "task_id": self.task_id,
            "command": self.command,
            "intent": self.intent,
            "target": self.target,
            "plan_steps": list(self.plan_steps),
            "confirmation_status": self.confirmation_status,
            "execution_mode": self.execution_mode,
            "execution_result": self.execution_result,
            "verification_result": self.verification_result,
            "error": self.error,
            "task_status": self.task_status,
            "context_queries": list(self.context_queries),
        }


@dataclass
class Turn:
    """Um turno de conversa na sessão."""

    role: Literal["user", "therion"]
    text: str


class WorkingMemory:
    """Gerenciador de memória de trabalho estritamente volátil (sem persistência em disco)."""

    def __init__(self) -> None:
        self.current_task: Optional[TaskContext] = None
        self.history: List[TaskContext] = []
        # Memória de sessão (V1)
        self.turns: deque = deque(maxlen=50)
        self.last_intent: Optional[str] = None
        self.last_target: Optional[str] = None
        self.last_result: Optional[str] = None
        self.last_status: Optional[str] = None

    def start_task(
        self,
        command: str,
        execution_mode: str = "simulado",
        task_id: Optional[str] = None,
    ) -> TaskContext:
        """Inicia uma nova tarefa limpa, isolando o estado da tarefa anterior."""
        generated_id = task_id or str(uuid.uuid4())[:8]
        self.current_task = TaskContext(
            task_id=generated_id,
            command=command,
            execution_mode=execution_mode,
            task_status="iniciada",
        )
        return self.current_task

    def record_intent(self, intent: str, target: Optional[str]) -> None:
        """Registra a intenção interpretada e seu respectivo alvo."""
        if self.current_task:
            self.current_task.intent = intent
            self.current_task.target = target

    def record_plan(self, steps: List[str]) -> None:
        """Registra as etapas do mini-plano gerado."""
        if self.current_task:
            self.current_task.plan_steps = list(steps)

    def record_awaiting_confirmation(self) -> None:
        """Registra que a tarefa está pausada aguardando confirmação do usuário."""
        if self.current_task:
            self.current_task.confirmation_status = "aguardando"
            self.current_task.task_status = "aguardando_confirmacao"

    def record_confirmation(self, confirmed: bool) -> None:
        """Registra a resposta de confirmação do usuário."""
        if self.current_task:
            if confirmed:
                self.current_task.confirmation_status = "confirmado"
            else:
                self.current_task.confirmation_status = "cancelado"
                self.current_task.task_status = "cancelado"

    def record_execution_result(self, result: str, success: bool = True) -> None:
        """Registra o resultado retornado pelo executor de ações."""
        if self.current_task:
            self.current_task.execution_result = result
            if not success:
                self.current_task.task_status = "falhou"

    def record_verification_result(self, result: str, success: bool = True) -> None:
        """Registra a evidência obtida pelo verificador."""
        if self.current_task:
            self.current_task.verification_result = result
            if success:
                self.current_task.task_status = "concluido"
            else:
                self.current_task.task_status = "falhou"

    def record_context_query(
        self, path: str, success: bool, error: Optional[str] = None
    ) -> None:
        """Registra uma consulta ao Segundo Cérebro na tarefa atual."""
        if self.current_task:
            self.current_task.context_queries.append(
                {
                    "path": path,
                    "success": success,
                    "error": error,
                }
            )

    def record_error(self, error: str) -> None:
        """Registra um erro na tarefa atual e marca seu status como falha."""
        if self.current_task:
            self.current_task.error = error
            self.current_task.task_status = "falhou"

    def complete_task(self) -> None:
        """Arquiva a tarefa atual concluída ou encerrada no histórico da sessão."""
        if self.current_task:
            self.history.append(self.current_task)

    def clear(self) -> None:
        """Limpa toda a memória da sessão atual."""
        self.current_task = None
        self.history.clear()

    def add_turn(self, role: Literal["user", "therion"], text: str) -> None:
        """Adiciona um turno de conversa à sessão."""
        self.turns.append(Turn(role=role, text=text))

    def recent_turns(self, n: int = 10) -> List[Turn]:
        """Retorna os N turnos mais recentes."""
        if n <= 0:
            return []
        turns_list = list(self.turns)
        return turns_list[-n:]

    def clear_session(self) -> None:
        """Limpa turnos e contexto operacional, preservando history e current_task."""
        self.turns.clear()
        self.last_intent = None
        self.last_target = None
        self.last_result = None
        self.last_status = None
