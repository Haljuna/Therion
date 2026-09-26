"""Testes de integração da memória de sessão com o Orchestrator (V1)."""

import unittest
from unittest.mock import MagicMock, patch

from therion.core.ai_provider import PlanContent, PlanSection
from therion.core.orchestrator import Orchestrator, OrchestrationResult


class TestSessionMemoryIntegration(unittest.TestCase):
    """Valida registro de turnos e contexto operacional no ciclo completo do Orchestrator."""

    def setUp(self) -> None:
        self.orch = Orchestrator(simulate=True)

    # --- process_command: turnos ---

    def test_process_command_registers_one_user_turn(self) -> None:
        """1. process_command registra exatamente um Turn de usuário."""
        self.orch.process_command("Therion, abra o Obsidian")
        user_turns = [t for t in self.orch.memory.turns if t.role == "user"]
        self.assertEqual(len(user_turns), 1)
        self.assertEqual(user_turns[0].text, "Therion, abra o Obsidian")

    def test_process_command_registers_one_therion_turn(self) -> None:
        """2. process_command registra exatamente um Turn do Therion com text == result.message."""
        result = self.orch.process_command("Therion, abra o Obsidian")
        therion_turns = [t for t in self.orch.memory.turns if t.role == "therion"]
        self.assertEqual(len(therion_turns), 1)
        self.assertEqual(therion_turns[0].text, result.message)

    # --- last_intent / last_target ---

    def test_valid_intent_updates_last_intent_and_target(self) -> None:
        """3. Comando com intent/target válidos atualiza last_intent e last_target."""
        self.orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(self.orch.memory.last_intent, "abrir aplicativo")
        self.assertEqual(self.orch.memory.last_target, "Obsidian")

    def test_result_without_intent_does_not_overwrite_previous(self) -> None:
        """4. Resultado sem intent/target NÃO apaga last_intent/last_target previamente válidos."""
        self.orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(self.orch.memory.last_intent, "abrir aplicativo")

        # Segundo comando: fluxo de alias (tem intent, não sobrescreve com None)
        self.orch.process_command("adicione um alias")
        # last_intent continua válido (fluxo de alias tem intent)
        self.assertIsNotNone(self.orch.memory.last_intent)

        # Comando desconhecido — intent é None no OrchestrationResult
        self.orch.process_command("blablabla")
        # last_intent NÃO deve ter sido apagado
        self.assertEqual(self.orch.memory.last_intent, "adicionar alias")

    # --- last_result / last_status ---

    def test_last_result_receives_message(self) -> None:
        """5. last_result recebe result.message."""
        result = self.orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(self.orch.memory.last_result, result.message)

    def test_last_status_receives_status(self) -> None:
        """6. last_status recebe result.status."""
        result = self.orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(self.orch.memory.last_status, result.status)

    # --- múltiplos comandos ---

    def test_multiple_commands_accumulate_turns_in_order(self) -> None:
        """7. Múltiplos comandos acumulam turnos na ordem correta."""
        self.orch.process_command("Therion, abra o Obsidian")
        self.orch.process_command("liste meus aliases")

        turns = list(self.orch.memory.turns)
        self.assertEqual(len(turns), 4)
        # Par 1
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[0].text, "Therion, abra o Obsidian")
        self.assertEqual(turns[1].role, "therion")
        # Par 2
        self.assertEqual(turns[2].role, "user")
        self.assertEqual(turns[2].text, "liste meus aliases")
        self.assertEqual(turns[3].role, "therion")

    # --- confirm_and_execute ---

    def test_confirm_and_execute_adds_only_therion_turn(self) -> None:
        """8. confirm_and_execute registra nova resposta sem duplicar user turn."""
        result = self.orch.process_command("Therion, abra o Obsidian")
        turns_after_process = len(self.orch.memory.turns)

        self.orch.confirm_and_execute(result.plan, confirmed=True)

        turns_after_confirm = len(self.orch.memory.turns)
        # Deve adicionar apenas 1 turn (therion), não duplicar user
        self.assertEqual(turns_after_confirm, turns_after_process + 1)
        # Último turn é do therion
        self.assertEqual(self.orch.memory.turns[-1].role, "therion")

    def test_cancellation_maintains_coherent_history(self) -> None:
        """9. Cancelamento mantém histórico coerente e atualiza last_status."""
        result = self.orch.process_command("Therion, abra o Obsidian")
        self.orch.confirm_and_execute(result.plan, confirmed=False)

        self.assertEqual(self.orch.memory.last_status, "cancelled")
        # Turns: user (process) + therion (process) + therion (cancel) = 3
        self.assertEqual(len(self.orch.memory.turns), 3)
        self.assertEqual(self.orch.memory.turns[-1].role, "therion")
        self.assertIn("cancelada", self.orch.memory.turns[-1].text)

    # --- fluxos conversacionais ---

    def test_list_aliases_flow_registers_user_and_therion(self) -> None:
        """10. Listagem de aliases registra user + therion corretamente."""
        self.orch.process_command("liste meus aliases")

        turns = list(self.orch.memory.turns)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[0].text, "liste meus aliases")
        self.assertEqual(turns[1].role, "therion")
        self.assertIn("alias", turns[1].text.lower())


class TestAICoreAliasRouting(unittest.TestCase):
    """Valida que action via AICore roteia corretamente para listagem de aliases."""

    def test_ai_action_listar_aliases_returns_actual_aliases(self) -> None:
        """Action 'listar aliases' via AICore retorna aliases reais, não mensagem genérica."""
        from therion.core.ai_provider import AIResponse

        # --- Arrange ---
        # Provider fake que retorna AIResponse de action
        fake_provider = MagicMock()
        fake_ai_response = AIResponse(
            type="action",
            intent="listar aliases",
            arguments={},
            message="Processando listagem de aliases.",
        )
        fake_provider.generate.return_value = fake_ai_response

        # AICore com o provider fake
        from therion.core.ai_core import AICore

        ai_core = AICore(
            provider=fake_provider,
            available_intents=[
                "abrir aplicativo",
                "listar aliases",
                "buscar segundo cérebro",
                "calendário hoje",
                "criar evento calendário",
            ],
        )

        # Orchestrator com AICore fake e AliasManager mockado
        orch = Orchestrator(simulate=True, ai_core=ai_core)
        orch.alias_manager = MagicMock()
        orch.alias_manager.list_aliases.return_value = {
            "obsidian": "Obsidian",
            "navegador": "Chrome",
        }

        # --- Act ---
        result = orch.process_command("Mostre quais são meus aliases cadastrados")

        # --- Assert ---
        # 1. Resultado contém os aliases conhecidos
        self.assertIn("obsidian", result.message.lower())
        self.assertIn("navegador", result.message.lower())
        self.assertIn("Obsidian", result.message)
        self.assertIn("Chrome", result.message)

        # 2. Resposta NÃO é a mensagem genérica do provider
        self.assertNotEqual(result.message, "Processando listagem de aliases.")
        self.assertNotEqual(result.message, "Listando aliases...")

        # 3. Status é success
        self.assertEqual(result.status, "success")

        # 4. Intent foi registrada corretamente
        self.assertEqual(result.intent.action, "listar aliases")

        # 5. Nenhuma escrita occurceu (somente leitura)
        orch.alias_manager.add_alias.assert_not_called()
        orch.alias_manager.remove_alias.assert_not_called()
        orch.alias_manager.replace_alias.assert_not_called()


class TestDeterministicRoutingPriority(unittest.TestCase):
    """Valida que IntentRecognizer é priorizado sobre AICore para comandos conhecidos."""

    def test_deterministic_command_skips_ai(self) -> None:
        """'liste meus aliases' é processado pelo IntentRecognizer sem consultar AICore."""
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="action",
            intent="listar aliases",
            arguments={},
            message="NÃO deveria ser chamado.",
        )

        from therion.core.ai_core import AICore

        ai_core = AICore(
            provider=fake_provider,
            available_intents=["listar aliases"],
        )

        orch = Orchestrator(simulate=True, ai_core=ai_core)
        orch.alias_manager = MagicMock()
        orch.alias_manager.list_aliases.return_value = {"obsidian": "Obsidian"}

        result = orch.process_command("liste meus aliases")

        fake_provider.generate.assert_not_called()
        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent.action, "listar aliases")
        self.assertIn("obsidian", result.message)

    def test_unknown_command_consults_ai(self) -> None:
        """Comando não reconhecido pelo IntentRecognizer consulta AICore."""
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="chat",
            intent=None,
            arguments={},
            message="Olá! Sou o Therion.",
        )

        from therion.core.ai_core import AICore

        ai_core = AICore(
            provider=fake_provider,
            available_intents=["listar aliases"],
        )

        orch = Orchestrator(simulate=True, ai_core=ai_core)

        result = orch.process_command("Olá, tudo bem?")

        fake_provider.generate.assert_called_once()
        self.assertEqual(result.status, "success")
        self.assertIn("Olá", result.message)

    def test_ai_action_routed_when_recognizer_unknown(self) -> None:
        """Action válida do AICore é roteada quando IntentRecognizer não reconhece."""
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="action",
            intent="calendário hoje",
            arguments={},
            message="Consultando calendário.",
        )

        from therion.core.ai_core import AICore

        ai_core = AICore(
            provider=fake_provider,
            available_intents=["calendário hoje"],
        )

        orch = Orchestrator(simulate=True, ai_core=ai_core)

        result = orch.process_command("O que tenho hoje no calendário?")

        fake_provider.generate.assert_called_once()
        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent.action, "calendário hoje")

    def test_pending_flow_priority_over_recognizer_and_ai(self) -> None:
        """Pending flows continuam tendo prioridade sobre recognizer e IA."""
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="chat",
            intent=None,
            arguments={},
            message="NÃO deveria ser chamado.",
        )

        from therion.core.ai_core import AICore

        ai_core = AICore(
            provider=fake_provider,
            available_intents=["listar aliases"],
        )

        orch = Orchestrator(simulate=True, ai_core=ai_core)
        orch.alias_manager = MagicMock()

        orch.process_command("adicione um alias")
        fake_provider.generate.assert_not_called()

        result = orch.process_command("sim")
        fake_provider.generate.assert_not_called()


class TestCalendarSafeCollection(unittest.TestCase):
    """Valida coleta segura de evento incompleto durante draft pendente."""

    def test_cancel_clears_draft(self):
        """'não' cancela draft incompleto e limpa estado."""
        orch = Orchestrator(simulate=True)
        # Iniciar draft com título preenchido, faltando date
        orch.process_command("crie uma reunião")

        result = orch.process_command("não")

        self.assertEqual(result.status, "cancelled")
        self.assertIn("cancelada", result.message.lower())
        self.assertIsNone(orch._pending_event_draft)

    def test_empty_repeats_question(self):
        """Resposta vazia repete a pergunta sem alterar draft."""
        orch = Orchestrator(simulate=True)
        orch.process_command("crie uma reunião")

        result = orch.process_command("")

        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("data", result.message.lower())

    def test_new_command_clears_draft(self):
        """Comando reconhecido limpa draft e é processado normalmente."""
        orch = Orchestrator(simulate=True)
        orch.process_command("crie uma reunião")
        self.assertIsNotNone(orch._pending_event_draft)

        result = orch.process_command("liste meus aliases")

        self.assertIsNone(orch._pending_event_draft)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent.action, "listar aliases")

    def test_normal_answer_fills_field(self):
        """Resposta normal preenche o próximo campo faltante."""
        orch = Orchestrator(simulate=True)
        orch.process_command("crie uma reunião")

        result = orch.process_command("amanhã")

        self.assertIsNotNone(orch._pending_event_draft)
        self.assertEqual(orch._pending_event_draft.get("date"), "amanhã")

    def test_cancel_variations(self):
        """Diversas variações de cancelamento limham o draft."""
        for cancel_word in ["não", "cancelar", "cancele", "cancela"]:
            orch = Orchestrator(simulate=True)
            orch.process_command("crie uma reunião")
            result = orch.process_command(cancel_word)
            self.assertEqual(result.status, "cancelled", msg=f"Falhou com: {cancel_word}")
            self.assertIsNone(orch._pending_event_draft)

    def test_natural_absence_clause_multiturn(self):
        """Cenário multi-turno real: pedido inicial com vírgula e ausência de hora seguido de título."""
        from unittest.mock import MagicMock
        orch = Orchestrator(simulate=True)
        mock_adapter = MagicMock()
        orch.calendar_adapter = mock_adapter

        # 1. Primeiro turno com Quero criar um evento, mas ainda não sei a hora.
        res1 = orch.process_command("Quero criar um evento, mas ainda não sei a hora.")
        # 2. Confirmar que o fluxo pendente é criado e Therion pergunta pelo título
        self.assertEqual(res1.status, "awaiting_confirmation")
        self.assertEqual(res1.message, "Qual é o título do evento?")
        self.assertIsNotNone(orch._pending_event_draft)
        self.assertNotIn("title", orch._pending_event_draft)

        # 3. Segundo turno teste
        res2 = orch.process_command("teste")
        # 4. Confirmar continuidade com title Teste e pergunta Para qual data?
        self.assertEqual(res2.status, "awaiting_confirmation")
        self.assertEqual(res2.message, "Para qual data?")
        self.assertIsNotNone(orch._pending_event_draft)
        self.assertEqual(orch._pending_event_draft.get("title"), "Teste")

        # 5. Confirmar que nenhuma criação externa de evento ocorreu
        mock_adapter.create_event.assert_not_called()

    def test_new_command_clears_complete_draft(self):
        """Novo comando determinístico durante confirmação final limpa draft e processa comando sem criar evento."""
        from unittest.mock import MagicMock
        orch = Orchestrator(simulate=True)
        mock_adapter = MagicMock()
        orch.calendar_adapter = mock_adapter

        # Evento completo aguardando confirmação
        res1 = orch.process_command("marque reunião amanhã às 15h")
        self.assertEqual(res1.status, "awaiting_confirmation")
        self.assertIsNotNone(orch._pending_event_draft)

        # Usuário envia novo comando determinístico
        res2 = orch.process_command("liste meus aliases")

        # Draft antigo é limpo e novo comando é processado normalmente
        self.assertIsNone(orch._pending_event_draft)
        self.assertEqual(res2.status, "success")
        self.assertEqual(res2.intent.action, "listar aliases")

        # Evento pendente NÃO é criado
        mock_adapter.create_event.assert_not_called()


class TestPlanDayIntegration(unittest.TestCase):
    """Testes de integração da SKILL-002 com o Orchestrator."""

    def test_returns_read_only_warning(self):
        """process_command('planeje meu dia') retorna mensagem com aviso read-only."""
        orch = Orchestrator(simulate=True)
        result = orch.process_command("planeje meu dia")
        self.assertIn("[Leitura apenas", result.message)

    def test_success_status(self):
        """SkillResult success vira OrchestrationResult success."""
        orch = Orchestrator(simulate=True)
        result = orch.process_command("planeje meu dia")
        self.assertEqual(result.status, "success")

    def test_last_intent_registered(self):
        """last_intent registra 'planejar dia'."""
        orch = Orchestrator(simulate=True)
        orch.process_command("planeje meu dia")
        self.assertEqual(orch.memory.last_intent, "planejar dia")

    def test_user_and_therion_turns(self):
        """Registra turnos user e therion."""
        orch = Orchestrator(simulate=True)
        orch.process_command("planeje meu dia")
        roles = [t.role for t in orch.memory.turns]
        self.assertIn("user", roles)
        self.assertIn("therion", roles)

    def test_no_ai_core_consulta(self):
        """IntentRecognizer processa sem consultar AICore."""
        orch = Orchestrator(simulate=True)
        orch.ai_core = MagicMock()
        orch.process_command("planeje meu dia")
        orch.ai_core.classify.assert_not_called()

    def test_with_prefix_therion(self):
        """'Therion, planeje meu dia' funciona igualmente."""
        orch = Orchestrator(simulate=True)
        result = orch.process_command("Therion, planeje meu dia")
        self.assertEqual(result.status, "success")
        self.assertIn("[Leitura apenas", result.message)

    def test_partial_status_becomes_success(self):
        """SkillResult partial vira success com mensagem."""
        from unittest.mock import MagicMock as Mock
        orch = Orchestrator(simulate=True)
        # calendar_adapter ausente → parcial
        orch.calendar_adapter = None
        result = orch.process_command("planeje meu dia")
        self.assertEqual(result.status, "success")
        self.assertIn("[Leitura apenas", result.message)

    def test_calendar_none_yields_success_with_message(self):
        """Calendar indisponível → Skill retorna parcial → Orchestrator mapeia para success."""
        orch = Orchestrator(simulate=True)
        orch.calendar_adapter = None
        result = orch.process_command("planeje meu dia")
        self.assertEqual(result.status, "success")
        self.assertIn("Calendário não disponível", result.message)

    def test_skill_not_registered_returns_error(self):
        """SKILL-002 ausente do registry gera erro controlado."""
        import therion.skills.registry as reg
        original = reg.SKILLS.copy()
        try:
            reg.SKILLS.clear()
            orch = Orchestrator(simulate=True)
            result = orch.process_command("planeje meu dia")
            self.assertEqual(result.status, "execution_failed")
            self.assertIn("não disponível", result.message)
        finally:
            reg.SKILLS.update(original)


class TestOpenAppContextualFlow(unittest.TestCase):
    """Testes do fluxo de abertura contextual com targets vagos."""

    def setUp(self) -> None:
        self.orch = Orchestrator(simulate=True)

    def test_abre_aquilo_starts_flow(self) -> None:
        """1. 'abre aquilo' inicia pending de abertura, NÃO fluxo de alias."""
        result = self.orch.process_command("abre aquilo")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual aplicativo", result.message)
        self.assertTrue(self.orch._open_app_flow_active)
        self.assertIsNone(self.orch._pending_unknown_original)

    def test_abre_isso_starts_flow(self) -> None:
        """2. 'abre isso' inicia pending de abertura."""
        result = self.orch.process_command("abre isso")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertTrue(self.orch._open_app_flow_active)

    def test_empty_repeats_question(self) -> None:
        """3. Resposta vazia repete pergunta e mantém pending."""
        self.orch.process_command("abre aquilo")
        result = self.orch.process_command("")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual aplicativo", result.message)
        self.assertTrue(self.orch._open_app_flow_active)

    def test_cancel_clears_flow(self) -> None:
        """4. Cancelamento limpa pending, não executa nada."""
        self.orch.process_command("abre aquilo")
        result = self.orch.process_command("não")
        self.assertEqual(result.status, "cancelled")
        self.assertFalse(self.orch._open_app_flow_active)

    def test_cancel_variations(self) -> None:
        """5. Diversas variações de cancelamento limham o pending."""
        for cancel_word in ["não", "nao", "cancelar", "cancele", "cancela", "no"]:
            orch = Orchestrator(simulate=True)
            orch.process_command("abre aquilo")
            result = orch.process_command(cancel_word)
            self.assertEqual(result.status, "cancelled", msg=f"Falhou com: {cancel_word}")
            self.assertFalse(orch._open_app_flow_active)

    def test_new_command_interrupts_flow(self) -> None:
        """6. Novo comando determinístico interrompe pending e processa normalmente."""
        self.orch.process_command("abre aquilo")
        self.assertTrue(self.orch._open_app_flow_active)
        result = self.orch.process_command("liste meus aliases")
        self.assertFalse(self.orch._open_app_flow_active)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent.action, "listar aliases")

    def test_obsidian_response_enters_pipeline(self) -> None:
        """7. 'obsidian' como resposta produz Intent e entra no pipeline normal."""
        self.orch.process_command("abre aquilo")
        result = self.orch.process_command("Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertEqual(result.intent.action, "abrir aplicativo")
        self.assertEqual(result.intent.target, "Obsidian")
        self.assertIn("Continuar?", result.message)

    def test_permission_confirmation_preserved(self) -> None:
        """8. Abertura continua exigindo permissão e confirmação."""
        self.orch.process_command("abre aquilo")
        result = self.orch.process_command("Obsidian")
        self.assertTrue(result.intent.requires_confirmation)
        self.assertIn("exige confirmação", result.message)

    def test_no_execution_before_confirmation(self) -> None:
        """9. Nenhuma execução real ocorre antes da confirmação."""
        self.orch.process_command("abre aquilo")
        result = self.orch.process_command("Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIsNone(self.orch.executor._ALLOWED_TARGETS if hasattr(self.orch.executor, '_pending') else None)

    def test_concrete_unknown_target_preserved(self) -> None:
        """10. Target desconhecido concreto continua com comportamento anterior."""
        result = self.orch.process_command("abra Photoshop")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertTrue(self.orch._unknown_target_flow_step)
        self.assertIn("Não reconheci", result.message)
        self.assertFalse(self.orch._open_app_flow_active)


class TestPomodoroBudget(unittest.TestCase):
    """Testes do orçamento temporal determinístico Pomodoro (Incremento 4A)."""

    def setUp(self) -> None:
        self.orch = Orchestrator(simulate=True)

    def test_A_duration_in_command_current(self) -> None:
        """A) Duração no command atual com sinal de estudo."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        budget = _extract_pomodoro_budget(
            "tenho 2 horas para estudar com pomodoro", []
        )
        self.assertIsNotNone(budget)
        self.assertEqual(budget["blocks"], 4)
        self.assertEqual(budget["planned_minutes"], 115)
        self.assertEqual(budget["remaining_minutes"], 5)

    def test_B_duration_in_minutes(self) -> None:
        """B) Formato minutos."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        budget = _extract_pomodoro_budget("tenho 120 minutos para estudar", [])
        self.assertIsNotNone(budget)
        self.assertEqual(budget["blocks"], 4)
        self.assertEqual(budget["planned_minutes"], 115)

    def test_C_duration_format_2h(self) -> None:
        """C) Formato 2h."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        budget = _extract_pomodoro_budget("tenho 2h para estudar", [])
        self.assertIsNotNone(budget)
        self.assertEqual(budget["blocks"], 4)
        self.assertEqual(budget["planned_minutes"], 115)

    def test_D_multiturno_com_sim(self) -> None:
        """D) Fluxo multiturno: recent_turns contém command atual 'sim'; turno anterior é usado."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        recent = [
            {"role": "user", "text": "tenho 2 horas para estudar Circuitos Lógicos"},
            {"role": "therion", "text": "Deseja que eu gere o plano?"},
            {"role": "user", "text": "sim"},
        ]
        budget = _extract_pomodoro_budget("sim", recent)
        self.assertIsNotNone(budget)
        self.assertEqual(budget["blocks"], 4)
        self.assertEqual(budget["available_minutes"], 120)
        self.assertEqual(budget["focus_minutes"], 25)
        self.assertEqual(budget["break_minutes"], 5)
        self.assertEqual(budget["planned_minutes"], 115)
        self.assertEqual(budget["remaining_minutes"], 5)

    def test_E_nao_busca_historico_profundo(self) -> None:
        """E) Não reutiliza duração de histórico profundo quando turno anterior não tem duração."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        recent = [
            {"role": "user", "text": "tenho 2 horas para estudar matemática"},
            {"role": "therion", "text": "Ok!"},
            {"role": "user", "text": "quero estudar circuitos lógicos"},
            {"role": "therion", "text": "Claro!"},
        ]
        budget = _extract_pomodoro_budget("sim", recent)
        self.assertIsNone(budget)

    def test_F_sem_contexto_estudo(self) -> None:
        """F) Sem contexto de estudo: não gerar budget."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        budget = _extract_pomodoro_budget("tenho 2 horas para jogar", [])
        self.assertIsNone(budget)

    def test_G_tempo_menor_25(self) -> None:
        """G) Tempo menor que 25 min: não gerar budget."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        budget = _extract_pomodoro_budget("tenho 20 minutos para estudar", [])
        self.assertIsNone(budget)

    def test_H_calculo_25_min(self) -> None:
        """H) Caso 25 min."""
        from therion.core.orchestrator import _compute_pomodoro_budget
        b = _compute_pomodoro_budget(25)
        self.assertEqual(b["blocks"], 1)
        self.assertEqual(b["planned_minutes"], 25)
        self.assertEqual(b["remaining_minutes"], 0)

    def test_H_calculo_30_min(self) -> None:
        """H) Caso 30 min."""
        from therion.core.orchestrator import _compute_pomodoro_budget
        b = _compute_pomodoro_budget(30)
        self.assertEqual(b["blocks"], 1)
        self.assertEqual(b["planned_minutes"], 25)
        self.assertEqual(b["remaining_minutes"], 5)

    def test_H_calculo_55_min(self) -> None:
        """H) Caso 55 min."""
        from therion.core.orchestrator import _compute_pomodoro_budget
        b = _compute_pomodoro_budget(55)
        self.assertEqual(b["blocks"], 2)
        self.assertEqual(b["planned_minutes"], 55)
        self.assertEqual(b["remaining_minutes"], 0)

    def test_H_calculo_60_min(self) -> None:
        """H) Caso 60 min."""
        from therion.core.orchestrator import _compute_pomodoro_budget
        b = _compute_pomodoro_budget(60)
        self.assertEqual(b["blocks"], 2)
        self.assertEqual(b["planned_minutes"], 55)
        self.assertEqual(b["remaining_minutes"], 5)

    def test_H_calculo_120_min(self) -> None:
        """H) Caso 120 min."""
        from therion.core.orchestrator import _compute_pomodoro_budget
        b = _compute_pomodoro_budget(120)
        self.assertEqual(b["blocks"], 4)
        self.assertEqual(b["planned_minutes"], 115)
        self.assertEqual(b["remaining_minutes"], 5)

    def test_I_context_unchanged_when_not_applicable(self) -> None:
        """I) ai_context não contém pomodoro_budget quando não aplicável."""
        ctx = self.orch._build_ai_context("abra o Obsidian")
        self.assertNotIn("pomodoro_budget", ctx)

    def test_I_context_contains_budget_when_applicable(self) -> None:
        """I) ai_context contém pomodoro_budget quando aplicável."""
        ctx = self.orch._build_ai_context("tenho 2 horas para estudar")
        self.assertIn("pomodoro_budget", ctx)
        self.assertEqual(ctx["pomodoro_budget"]["blocks"], 4)

    def test_J_parser_rejects_ambiguos_e_meia(self) -> None:
        """J) Parser rejeita '2 horas e meia'."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertIsNone(_parse_duration_minutes("2 horas e meia"))

    def test_J_parser_rejects_mais_ou_menos(self) -> None:
        """J) Parser rejeita 'mais ou menos 2 horas'."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertIsNone(_parse_duration_minutes("mais ou menos 2 horas"))

    def test_J_parser_rejects_umas(self) -> None:
        """J) Parser rejeita 'umas 2 horas'."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertIsNone(_parse_duration_minutes("umas 2 horas"))

    def test_J_parser_rejects_1h30(self) -> None:
        """J) Parser rejeita '1h30'."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertIsNone(_parse_duration_minutes("1h30"))

    def test_J_parser_rejects_a_tarde_toda(self) -> None:
        """J) Parser rejeita 'a tarde toda'."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertIsNone(_parse_duration_minutes("a tarde toda"))

    def test_J_parser_accepts_validos(self) -> None:
        """J) Parser continua aceitando formatos V1 válidos."""
        from therion.core.orchestrator import _parse_duration_minutes
        self.assertEqual(_parse_duration_minutes("tenho 2 horas para estudar"), 120)
        self.assertEqual(_parse_duration_minutes("tenho 120 minutos para estudar"), 120)
        self.assertEqual(_parse_duration_minutes("tenho 2h para estudar"), 120)
        self.assertEqual(_parse_duration_minutes("1 hora de estudo"), 60)
        self.assertEqual(_parse_duration_minutes("30 min de foco"), 30)

    def test_K_multiturno_real_comando_atual_no_recent(self) -> None:
        """K) recent_turns inclui command atual; turno anterior com duração é usado."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        recent = [
            {"role": "user", "text": "quero estudar circuitos lógicos"},
            {"role": "therion", "text": "Claro!"},
            {"role": "user", "text": "tenho 2 horas para estudar"},
            {"role": "therion", "text": "Deseja que eu gere o plano?"},
            {"role": "user", "text": "sim"},
        ]
        budget = _extract_pomodoro_budget("sim", recent)
        self.assertIsNotNone(budget)
        self.assertEqual(budget["blocks"], 4)

    def test_K_historico_antigo_nao_reaproveitado(self) -> None:
        """K) Último turno anterior sem duração: budget antigo não é reaproveitado."""
        from therion.core.orchestrator import _extract_pomodoro_budget
        recent = [
            {"role": "user", "text": "tenho 2 horas para estudar matemática"},
            {"role": "therion", "text": "Ok!"},
            {"role": "user", "text": "quero estudar circuitos lógicos"},
            {"role": "therion", "text": "Claro!"},
            {"role": "user", "text": "sim"},
        ]
        budget = _extract_pomodoro_budget("sim", recent)
        self.assertIsNone(budget)

    def test_L_integracao_build_ai_context(self) -> None:
        """L) _build_ai_context(command) produz budget correto no caminho real."""
        self.orch.memory.add_turn("user", "tenho 2 horas para estudar Circuitos Lógicos")
        self.orch.memory.add_turn("therion", "Deseja que eu gere o plano?")
        self.orch.memory.add_turn("user", "sim")
        ctx = self.orch._build_ai_context("sim")
        self.assertIn("pomodoro_budget", ctx)
        b = ctx["pomodoro_budget"]
        self.assertEqual(b["available_minutes"], 120)
        self.assertEqual(b["blocks"], 4)
        self.assertEqual(b["focus_minutes"], 25)
        self.assertEqual(b["break_minutes"], 5)
        self.assertEqual(b["planned_minutes"], 115)
        self.assertEqual(b["remaining_minutes"], 5)


class TestAckPlanDisplayed(unittest.TestCase):
    """ACK de plano exibido via ack_plan_displayed (E1/M5c)."""

    def test_correct_candidate_registers(self) -> None:
        orch = Orchestrator(simulate=True)
        text = "Plano verbatim\n  com acentuação e espaços  "
        candidate_id = orch._plan_state.set_candidate(text)
        result = orch.ack_plan_displayed(candidate_id)
        self.assertEqual(result.status, "registered")
        self.assertIsNotNone(result.plan_id)
        self.assertEqual(orch._plan_state.get_plan(result.plan_id).text, text)
        self.assertEqual(orch._plan_state.current_plan_id, result.plan_id)

    def test_wrong_id_keeps_candidate_and_registers_nothing(self) -> None:
        orch = Orchestrator(simulate=True)
        candidate_id = orch._plan_state.set_candidate("Candidato real")
        result = orch.ack_plan_displayed("id-errado")
        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "candidate_mismatch")
        self.assertIsNotNone(orch._plan_state.candidate)
        self.assertEqual(orch._plan_state.candidate.candidate_id, candidate_id)
        self.assertEqual(orch._plan_state.order, ())
        self.assertIsNone(orch._plan_state.current_plan_id)

    def test_clear_session_clears_plan_state(self) -> None:
        orch = Orchestrator(simulate=True)
        candidate_id = orch._plan_state.set_candidate("Pendente")
        orch.clear_session()
        result = orch.ack_plan_displayed(candidate_id)
        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "candidate_missing")
        self.assertIsNone(orch._plan_state.candidate)
        self.assertEqual(orch._plan_state.order, ())
        self.assertIsNone(orch._plan_state.current_plan_id)

    def test_ack_registered_plan_updates_current(self) -> None:
        orch = Orchestrator(simulate=True)
        id_one = orch._plan_state.set_candidate("Primeiro plano")
        plan_one = orch._plan_state.register_candidate(id_one).plan_id
        id_two = orch._plan_state.set_candidate("Segundo plano")
        plan_two = orch._plan_state.register_candidate(id_two).plan_id
        self.assertEqual(orch._plan_state.current_plan_id, plan_two)
        order_before = orch._plan_state.order
        plans_before = {
            p: orch._plan_state.get_plan(p).text for p in orch._plan_state.order
        }

        ok = orch.ack_registered_plan_displayed(plan_one)

        self.assertTrue(ok)
        self.assertEqual(orch._plan_state.current_plan_id, plan_one)
        self.assertEqual(orch._plan_state.order, order_before)
        self.assertEqual(
            {p: orch._plan_state.get_plan(p).text for p in orch._plan_state.order},
            plans_before,
        )
        self.assertEqual(len(orch._plan_state.order), 2)

    def test_ack_registered_plan_missing_id_keeps_state(self) -> None:
        orch = Orchestrator(simulate=True)
        id_one = orch._plan_state.set_candidate("Plano A")
        plan_one = orch._plan_state.register_candidate(id_one).plan_id
        current_before = orch._plan_state.current_plan_id
        order_before = orch._plan_state.order
        plans_before = {
            p: orch._plan_state.get_plan(p).text for p in orch._plan_state.order
        }

        ok = orch.ack_registered_plan_displayed("id-inexistente")

        self.assertFalse(ok)
        self.assertEqual(orch._plan_state.current_plan_id, current_before)
        self.assertEqual(orch._plan_state.order, order_before)
        self.assertEqual(
            {p: orch._plan_state.get_plan(p).text for p in orch._plan_state.order},
            plans_before,
        )
        self.assertEqual(orch._plan_state.get_plan(plan_one).text, "Plano A")


class TestRenderPlanContent(unittest.TestCase):
    """Renderização determinística PlanContent -> texto (E1/M5c3)."""

    def test_title_with_two_sections(self) -> None:
        plan = PlanContent(
            title="Meu plano",
            sections=[
                PlanSection(heading="Bloco 1", body="Conteúdo do bloco 1."),
                PlanSection(heading="Bloco 2", body="Conteúdo do bloco 2."),
            ],
        )
        expected = (
            "Meu plano\n\n"
            "Bloco 1\nConteúdo do bloco 1.\n\n"
            "Bloco 2\nConteúdo do bloco 2."
        )
        self.assertEqual(Orchestrator._render_plan_content(plan), expected)

    def test_title_none_starts_with_first_section(self) -> None:
        plan = PlanContent(
            title=None,
            sections=[
                PlanSection(heading="Bloco 1", body="Corpo um."),
                PlanSection(heading="Bloco 2", body="Corpo dois."),
            ],
        )
        expected = "Bloco 1\nCorpo um.\n\nBloco 2\nCorpo dois."
        self.assertEqual(Orchestrator._render_plan_content(plan), expected)

    def test_empty_title_omitted(self) -> None:
        plan = PlanContent(
            title="",
            sections=[
                PlanSection(heading="Bloco 1", body="Corpo um."),
                PlanSection(heading="Bloco 2", body="Corpo dois."),
            ],
        )
        expected = "Bloco 1\nCorpo um.\n\nBloco 2\nCorpo dois."
        self.assertEqual(Orchestrator._render_plan_content(plan), expected)

    def test_whitespace_preserved_exactly(self) -> None:
        plan = PlanContent(
            title="  título com espaços  ",
            sections=[
                PlanSection(heading="  H  ", body="  corpo  "),
                PlanSection(heading="H2", body="corpo2"),
            ],
        )
        expected = (
            "  título com espaços  \n\n"
            "  H  \n  corpo  \n\n"
            "H2\ncorpo2"
        )
        self.assertEqual(Orchestrator._render_plan_content(plan), expected)


class TestPlanRequestBranch(unittest.TestCase):
    """Ramo plan_request em process_command (E1/M5c3d)."""

    _COMMAND = "gere um plano de estudo sobre proporções"

    def _make_orch(self):
        from therion.core.ai_core import AICore
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="plan_request",
            intent=None,
            arguments={},
            message="Gerar plano.",
        )
        ai_core = AICore(
            provider=fake_provider,
            available_intents=["listar aliases"],
        )
        orch = Orchestrator(simulate=True, ai_core=ai_core)
        return orch, fake_provider

    @staticmethod
    def _valid_plan() -> PlanContent:
        return PlanContent(
            title="Plano de Estudo",
            sections=[
                PlanSection(heading="Bloco 1", body="Corpo um."),
                PlanSection(heading="Bloco 2", body="Corpo dois."),
            ],
        )

    def test_success_registers_candidate_and_returns_text(self) -> None:
        orch, fake_provider = self._make_orch()
        fake_provider.generate_plan.return_value = self._valid_plan()

        result = orch.process_command(self._COMMAND)

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.intent)
        self.assertIsNone(result.plan)
        self.assertIsNotNone(result.plan_candidate_id)
        self.assertIsNotNone(orch._plan_state.candidate)
        self.assertEqual(result.message, orch._plan_state.candidate.text)
        self.assertEqual(
            result.message,
            "Plano de Estudo\n\nBloco 1\nCorpo um.\n\nBloco 2\nCorpo dois.",
        )

    def test_pending_candidate_blocks_generation(self) -> None:
        orch, fake_provider = self._make_orch()
        orch._plan_state.set_candidate("Pendente antigo")
        fake_provider.generate_plan.return_value = self._valid_plan()

        result = orch.process_command(self._COMMAND)

        fake_provider.generate_plan.assert_not_called()
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.plan_candidate_id)
        self.assertIsNotNone(orch._plan_state.candidate)
        self.assertEqual(orch._plan_state.candidate.text, "Pendente antigo")

    def test_generation_failure_reuses_diagnostics(self) -> None:
        from therion.core.ai_provider import ProviderTimeoutError

        orch, fake_provider = self._make_orch()
        fake_provider.generate_plan.side_effect = ProviderTimeoutError()

        result = orch.process_command(self._COMMAND)

        self.assertEqual(result.status, "ai_timeout")
        self.assertEqual(
            result.message,
            "O serviço de IA auxiliar demorou demais para responder.",
        )
        self.assertIsNone(result.plan_candidate_id)
        self.assertIsNone(orch._plan_state.candidate)
        self.assertEqual(orch._plan_state.order, ())

    def test_planner_and_confirm_not_called(self) -> None:
        orch, fake_provider = self._make_orch()
        fake_provider.generate_plan.return_value = self._valid_plan()
        orch.planner.create_plan = MagicMock()
        orch.confirm_and_execute = MagicMock()

        result = orch.process_command(self._COMMAND)

        orch.planner.create_plan.assert_not_called()
        orch.confirm_and_execute.assert_not_called()
        self.assertEqual(result.status, "success")


class TestOrchestrationResultRegisteredPlanId(unittest.TestCase):
    """Campo opcional registered_plan_id (E1/M6e2)."""

    def test_default_registered_plan_id_is_none(self) -> None:
        result = OrchestrationResult(status="success")
        self.assertIsNone(result.registered_plan_id)
        self.assertIsNone(result.plan_candidate_id)

    def test_explicit_registered_plan_id_keeps_fields_independent(self) -> None:
        result = OrchestrationResult(
            status="success",
            registered_plan_id="plan-123",
        )
        self.assertEqual(result.registered_plan_id, "plan-123")
        self.assertIsNone(result.plan_candidate_id)


class TestPlanReferenceBranch(unittest.TestCase):
    """Ramo plan_reference em process_command (E1/M8b2)."""

    _COMMAND = "gere um plano de estudo sobre proporções"
    _UNAVAILABLE_MESSAGE = (
        "Não há um plano disponível nesta sessão para essa referência."
    )

    @staticmethod
    def _make_orch(reference: str):
        from therion.core.ai_core import AICore
        from therion.core.ai_provider import AIResponse

        fake_provider = MagicMock()
        fake_provider.generate.return_value = AIResponse(
            type="plan_reference",
            intent=None,
            arguments={"reference": reference},
            message="Referência a plano.",
        )
        ai_core = AICore(
            provider=fake_provider,
            available_intents=["listar aliases"],
        )
        return Orchestrator(simulate=True, ai_core=ai_core)

    @staticmethod
    def _register_plans(orch, texts) -> tuple:
        plan_ids = []
        for text in texts:
            candidate_id = orch._plan_state.set_candidate(text)
            result = orch._plan_state.register_candidate(candidate_id)
            plan_ids.append(result.plan_id)
        return tuple(plan_ids)

    def test_resolved_reference_returns_registered_text(self) -> None:
        orch = self._make_orch("first")
        texts = (
            "Plano A\nBloco 1\n  fim  ",
            "Plano B texto",
            "Plano C texto",
        )
        plan_ids = self._register_plans(orch, texts)
        current_before = orch._plan_state.current_plan_id

        result = orch.process_command(self._COMMAND)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, texts[0])
        self.assertEqual(result.registered_plan_id, plan_ids[0])
        self.assertIsNone(result.plan_candidate_id)
        self.assertEqual(orch._plan_state.current_plan_id, current_before)

    def test_unavailable_reference_reports_unavailable(self) -> None:
        orch = self._make_orch("second")
        self._register_plans(orch, ["Plano único"])
        current_before = orch._plan_state.current_plan_id

        result = orch.process_command(self._COMMAND)

        self.assertEqual(result.status, "plan_reference_unavailable")
        self.assertEqual(result.message, self._UNAVAILABLE_MESSAGE)
        self.assertIsNone(result.registered_plan_id)
        self.assertIsNone(result.plan_candidate_id)
        self.assertEqual(orch._plan_state.current_plan_id, current_before)


if __name__ == "__main__":
    unittest.main()
