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


if __name__ == "__main__":
    unittest.main()
