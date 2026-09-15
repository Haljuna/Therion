"""Testes unitários da memória de trabalho volátil da V0/V1."""

import unittest
from unittest.mock import MagicMock, patch

from therion.core.orchestrator import Orchestrator
from therion.memory.working_memory import TaskContext, Turn, WorkingMemory


class TestWorkingMemory(unittest.TestCase):
    """Garante que a memória de trabalho registre com precisão o ciclo de vida da tarefa."""

    def setUp(self) -> None:
        self.memory = WorkingMemory()

    def test_initial_state_empty(self) -> None:
        """1. Memória começa vazia e previsível."""
        self.assertIsNone(self.memory.current_task)
        self.assertEqual(len(self.memory.history), 0)

    def test_record_command(self) -> None:
        """2. Comando é registrado na inicialização da tarefa."""
        task = self.memory.start_task("Therion, abra o Obsidian", execution_mode="simulado")
        self.assertEqual(task.command, "Therion, abra o Obsidian")
        self.assertEqual(task.execution_mode, "simulado")
        self.assertEqual(task.task_status, "iniciada")

    def test_record_intent_and_target(self) -> None:
        """3. Intenção e alvo são registrados."""
        self.memory.start_task("Therion, abra o Obsidian")
        self.memory.record_intent("abrir aplicativo", "Obsidian")
        self.assertEqual(self.memory.current_task.intent, "abrir aplicativo")
        self.assertEqual(self.memory.current_task.target, "Obsidian")

    def test_record_plan(self) -> None:
        """4. Plano de etapas é registrado."""
        self.memory.start_task("Therion, abra o Obsidian")
        steps = ["1. Abrir o Obsidian.", "2. Verificar se o processo iniciou."]
        self.memory.record_plan(steps)
        self.assertEqual(self.memory.current_task.plan_steps, steps)

    def test_record_awaiting_confirmation(self) -> None:
        """5. Estado 'aguardando confirmação' é registrado."""
        self.memory.start_task("Therion, abra o Obsidian")
        self.memory.record_awaiting_confirmation()
        self.assertEqual(self.memory.current_task.confirmation_status, "aguardando")
        self.assertEqual(self.memory.current_task.task_status, "aguardando_confirmacao")

    def test_positive_confirmation_updates_state(self) -> None:
        """6. Confirmação positiva atualiza o estado."""
        self.memory.start_task("Therion, abra o Obsidian")
        self.memory.record_awaiting_confirmation()
        self.memory.record_confirmation(confirmed=True)
        self.assertEqual(self.memory.current_task.confirmation_status, "confirmado")

    def test_cancellation_updates_state(self) -> None:
        """7. Cancelamento atualiza o estado para cancelado."""
        self.memory.start_task("Therion, abra o Obsidian")
        self.memory.record_awaiting_confirmation()
        self.memory.record_confirmation(confirmed=False)
        self.assertEqual(self.memory.current_task.confirmation_status, "cancelado")
        self.assertEqual(self.memory.current_task.task_status, "cancelado")

    def test_simulated_execution_flow_via_orchestrator(self) -> None:
        """8. Execução simulada registra resultados e conclui tarefa."""
        orchestrator = Orchestrator(simulate=True)
        result = orchestrator.process_command("Therion, abra o Obsidian")

        # Verifica memória intermediária
        task = orchestrator.memory.current_task
        self.assertIsNotNone(task)
        self.assertEqual(task.command, "Therion, abra o Obsidian")
        self.assertEqual(task.intent, "abrir aplicativo")
        self.assertEqual(task.target, "Obsidian")
        self.assertEqual(task.confirmation_status, "aguardando")
        self.assertEqual(task.task_status, "aguardando_confirmacao")

        # Confirmação e execução
        orchestrator.confirm_and_execute(result.plan, confirmed=True)
        self.assertEqual(task.confirmation_status, "confirmado")
        self.assertIn("[Simulação] Executado", task.execution_result)
        self.assertIn("[Simulação] Processo do 'Obsidian' verificado", task.verification_result)
        self.assertEqual(task.task_status, "concluido")
        self.assertEqual(len(orchestrator.memory.history), 1)

    @patch("therion.actions.executor.os.path.isfile", return_value=True)
    @patch("therion.actions.executor.subprocess.Popen")
    @patch("therion.actions.verifier.subprocess.run")
    def test_real_execution_mocked_records_results(
        self, mock_run: MagicMock, mock_popen: MagicMock, mock_isfile: MagicMock
    ) -> None:
        """9. Execução real mockada registra resultado na memória sem abrir processos."""
        mock_run.return_value = MagicMock(stdout="Obsidian.exe 1234\n", returncode=0)
        orchestrator = Orchestrator(simulate=False)

        res = orchestrator.process_command("Therion, abra o Obsidian")
        orchestrator.confirm_and_execute(res.plan, confirmed=True)

        task = orchestrator.memory.current_task
        self.assertEqual(task.execution_mode, "real")
        self.assertEqual(task.task_status, "concluido")
        self.assertIn("enviado com sucesso", task.execution_result)
        self.assertIn("verificado e ativo", task.verification_result)
        self.assertIsNone(task.error)

    def test_error_recording(self) -> None:
        """10. Erro pode ser registrado corretamente na memória."""
        self.memory.start_task("Comando desconhecido")
        self.memory.record_error("Comando não compreendido")
        self.assertEqual(self.memory.current_task.error, "Comando não compreendido")
        self.assertEqual(self.memory.current_task.task_status, "falhou")

    def test_new_task_does_not_reuse_previous_state(self) -> None:
        """11. Uma nova tarefa não reutiliza acidentalmente o estado de tarefa anterior."""
        orchestrator = Orchestrator(simulate=True)

        # Tarefa 1: cancelada
        res1 = orchestrator.process_command("Therion, abra o Obsidian")
        orchestrator.confirm_and_execute(res1.plan, confirmed=False)
        self.assertEqual(orchestrator.memory.history[-1].task_status, "cancelado")

        # Tarefa 2: comando desconhecido
        orchestrator.process_command("Therion, comando invalido")
        task2 = orchestrator.memory.current_task
        self.assertEqual(task2.command, "Therion, comando invalido")
        self.assertIsNone(task2.intent)
        self.assertIsNone(task2.target)
        self.assertEqual(task2.plan_steps, [])
        self.assertEqual(task2.task_status, "falhou")

        # Garante que o histórico preserva ambas isoladamente
        self.assertEqual(len(orchestrator.memory.history), 2)
        self.assertEqual(orchestrator.memory.history[0].command, "Therion, abra o Obsidian")
        self.assertEqual(orchestrator.memory.history[1].command, "Therion, comando invalido")


class TestWorkingMemorySession(unittest.TestCase):
    """Testes da memória de sessão (V1): turnos e contexto operacional."""

    def setUp(self) -> None:
        self.memory = WorkingMemory()

    def test_add_turn_stores_role_and_text(self) -> None:
        """12. Turn armazena role e text corretamente."""
        self.memory.add_turn("user", "Therion, abra o Obsidian")
        turns = self.memory.recent_turns()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[0].text, "Therion, abra o Obsidian")

    def test_recent_turns_returns_last_n(self) -> None:
        """13. recent_turns retorna os N turnos mais recentes."""
        self.memory.add_turn("user", "cmd1")
        self.memory.add_turn("therion", "res1")
        self.memory.add_turn("user", "cmd2")
        self.memory.add_turn("therion", "res2")
        recent = self.memory.recent_turns(n=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].text, "cmd2")
        self.assertEqual(recent[1].text, "res2")

    def test_recent_turns_empty(self) -> None:
        """14. recent_turns retorna lista vazia quando não há turnos."""
        self.assertEqual(self.memory.recent_turns(), [])

    def test_recent_turns_n_zero_or_negative(self) -> None:
        """15. recent_turns com n <= 0 retorna lista vazia."""
        self.memory.add_turn("user", "test")
        self.assertEqual(self.memory.recent_turns(n=0), [])
        self.assertEqual(self.memory.recent_turns(n=-1), [])

    def test_turns_fifo_limit(self) -> None:
        """16. deque(maxlen=50) descarta turnos mais antigos."""
        for i in range(55):
            self.memory.add_turn("user", f"cmd{i}")
        turns = list(self.memory.turns)
        self.assertEqual(len(turns), 50)
        self.assertEqual(turns[0].text, "cmd5")
        self.assertEqual(turns[-1].text, "cmd54")

    def test_last_fields_start_none(self) -> None:
        """17. Campos last_* começam None."""
        self.assertIsNone(self.memory.last_intent)
        self.assertIsNone(self.memory.last_target)
        self.assertIsNone(self.memory.last_result)
        self.assertIsNone(self.memory.last_status)

    def test_clear_session_resets_turns_and_context(self) -> None:
        """18. clear_session limpa turns e last_*, preserva history."""
        self.memory.add_turn("user", "test")
        self.memory.last_intent = "abrir"
        self.memory.last_target = "Obsidian"
        self.memory.last_result = "ok"
        self.memory.last_status = "success"
        self.memory.start_task("tarefa")
        self.memory.complete_task()

        self.memory.clear_session()

        self.assertEqual(len(self.memory.turns), 0)
        self.assertIsNone(self.memory.last_intent)
        self.assertIsNone(self.memory.last_target)
        self.assertIsNone(self.memory.last_result)
        self.assertIsNone(self.memory.last_status)
        self.assertEqual(len(self.memory.history), 1)

    def test_clear_session_preserves_current_task(self) -> None:
        """19. clear_session preserva current_task se existir."""
        self.memory.start_task("comando")
        self.memory.add_turn("user", "comando")
        self.memory.last_intent = "test"

        self.memory.clear_session()

        self.assertIsNotNone(self.memory.current_task)
        self.assertEqual(self.memory.current_task.command, "comando")


if __name__ == "__main__":
    unittest.main()
