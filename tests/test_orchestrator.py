"""Testes de integração da memória de sessão com o Orchestrator (V1)."""

import unittest
from unittest.mock import MagicMock, patch

from therion.core.orchestrator import Orchestrator


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


if __name__ == "__main__":
    unittest.main()
