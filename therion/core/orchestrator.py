"""Módulo central de orquestração da V0 com integração à memória de trabalho."""

from dataclasses import dataclass
from typing import Optional

from therion.actions.executor import ActionExecutor
from therion.actions.verifier import ActionVerifier
from therion.config import AliasManager
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
        self.alias_manager = AliasManager()
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

    def _finalize_session_result(self, result: OrchestrationResult) -> None:
        """Registra turno do Therion e atualiza contexto operacional na sessão."""
        self.memory.add_turn("therion", result.message)
        self.memory.last_result = result.message
        self.memory.last_status = result.status
        if result.intent is not None:
            self.memory.last_intent = result.intent.action
            self.memory.last_target = result.intent.target

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

    def process_command(self, command: str) -> OrchestrationResult:
        """Processa um comando textual registrando todas as etapas na memória de trabalho."""
        mode = "simulado" if self.simulate else "real"
        self.memory.start_task(command=command, execution_mode=mode)
        self.memory.add_turn("user", command)

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

        intent = self.intent_recognizer.parse(command)
        if not intent:
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
            result = self.read_context(intent.target)
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
            results = self.second_brain.search_notes(intent.target)
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

        # Resolve alias antes da verificação de permissão
        resolved_target = self.alias_manager.resolve(intent.target)
        # Cria nova Intent com alvo resolvido (não muta a original)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
            requires_confirmation=intent.requires_confirmation,
        )

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
