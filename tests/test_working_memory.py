"""Testes unitários da memória de trabalho volátil da V0."""

import unittest
from unittest.mock import MagicMock, patch

from therion.core.orchestrator import Orchestrator
from therion.memory.working_memory import TaskContext, WorkingMemory


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


if __name__ == "__main__":
    unittest.main()
