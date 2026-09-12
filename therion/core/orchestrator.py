"""Módulo central de orquestração da V0 com integração à memória de trabalho."""

from dataclasses import dataclass
from typing import Optional

from therion.actions.executor import ActionExecutor
from therion.actions.verifier import ActionVerifier
from therion.context.second_brain import ReadResult, SecondBrainReader
from therion.core.intent import Intent, IntentRecognizer
from therion.core.planner import Plan, Planner
from therion.governance.confirmation import ConfirmationHandler
from therion.governance.permissions import PermissionManager
from therion.logging.audit import AuditLogger
from therion.memory.working_memory import WorkingMemory


@dataclass
class OrchestrationResult:
    """Resultado de uma etapa do ciclo de orquestração."""

    status: str  # "awaiting_confirmation", "success", "executed_simulated", "cancelled", "unknown_intent", "forbidden", "execution_failed", "verification_failed"
    intent: Optional[Intent] = None
    plan: Optional[Plan] = None
    message: str = ""


class Orchestrator:
    """Orquestrador do ciclo básico da V0 integrado à memória de trabalho da sessão."""

    def __init__(
        self,
        simulate: bool = False,
        log_dir: Optional[str] = None,
        vault_root: Optional[str] = None,
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

    def _complete_task(self) -> None:
        """Conclui a tarefa na memória de trabalho e audita o registro."""
        if self.memory.current_task:
            try:
                self.audit_logger.log_task(self.memory.current_task)
            except Exception as err:
                import sys
                sys.stderr.write(f"[AVISO] Falha ao registrar log de auditoria: {err}\n")
            self.memory.complete_task()

    def read_context(self, path: str) -> ReadResult:
        """Lê seletivamente uma nota autorizada do Segundo Cérebro e registra na memória."""
        result = self.second_brain.read_note(path)
        self.memory.record_context_query(
            path=path,
            success=result.success,
            error=result.error,
        )
        return result

    def process_command(self, command: str) -> OrchestrationResult:
        """Processa um comando textual registrando todas as etapas na memória de trabalho."""
        mode = "simulado" if self.simulate else "real"
        self.memory.start_task(command=command, execution_mode=mode)

        intent = self.intent_recognizer.parse(command)
        if not intent:
            msg = "Não consegui identificar a intenção no comando recebido."
            self.memory.record_error(msg)
            self._complete_task()
            return OrchestrationResult(
                status="unknown_intent",
                message=msg,
            )

        self.memory.record_intent(intent.action, intent.target)

        if not self.permission_manager.is_allowed(intent):
            msg = f"Ação '{intent.action}' para o alvo '{intent.target}' não está autorizada pela governança da V0."
            self.memory.record_error(msg)
            self._complete_task()
            return OrchestrationResult(
                status="forbidden",
                intent=intent,
                message=msg,
            )

        plan = self.planner.create_plan(intent)
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
            return OrchestrationResult(
                status="awaiting_confirmation",
                intent=intent,
                plan=plan,
                message=message,
            )

        return self.confirm_and_execute(plan, confirmed=True)

    def confirm_and_execute(
        self, plan: Plan, confirmed: bool, simulate: Optional[bool] = None
    ) -> OrchestrationResult:
        """Executa ou cancela a ação conforme a decisão do usuário, registrando na memória."""
        self.memory.record_confirmation(confirmed)

        if not confirmed:
            msg = "Operação cancelada pelo usuário."
            self._complete_task()
            return OrchestrationResult(
                status="cancelled",
                intent=plan.intent,
                plan=plan,
                message=msg,
            )

        is_simulated = self.simulate if simulate is None else simulate

        if is_simulated:
            exec_msg = self.executor.execute_simulated(plan.intent)
            verif_msg = self.verifier.verify_simulated(plan.intent)
            self.memory.record_execution_result(exec_msg, success=True)
            self.memory.record_verification_result(verif_msg, success=True)
            self._complete_task()
            return OrchestrationResult(
                status="executed_simulated",
                intent=plan.intent,
                plan=plan,
                message=f"{exec_msg}\n{verif_msg}",
            )

        # Execução Real no Windows
        exec_result = self.executor.execute_real(plan.intent)
        if not exec_result.success:
            self.memory.record_execution_result(exec_result.message, success=False)
            self.memory.record_error(exec_result.message)
            self._complete_task()
            return OrchestrationResult(
                status="execution_failed",
                intent=plan.intent,
                plan=plan,
                message=f"Falha na execução: {exec_result.message}",
            )

        self.memory.record_execution_result(exec_result.message, success=True)

        verif_result = self.verifier.verify_real(plan.intent)
        if not verif_result.success:
            self.memory.record_verification_result(verif_result.message, success=False)
            self.memory.record_error(verif_result.message)
            self._complete_task()
            return OrchestrationResult(
                status="verification_failed",
                intent=plan.intent,
                plan=plan,
                message=f"{exec_result.message}\nAlerta de verificação: {verif_result.message}",
            )

        self.memory.record_verification_result(verif_result.message, success=True)
        self._complete_task()
        return OrchestrationResult(
            status="success",
            intent=plan.intent,
            plan=plan,
            message=f"{exec_result.message}\n{verif_result.message}",
        )
