"""Registro limitado e recuperação literal, sem Ollama nem ações reais."""

import tempfile
import unittest
from unittest.mock import MagicMock

from therion.core.orchestrator import (
    Orchestrator, OrchestrationResult, _is_first_message_query,
)
from therion.memory.working_memory import WorkingMemory


class TestSessionJournal(unittest.TestCase):
    def test_beginning_and_ids_survive_more_than_fifty_messages(self):
        memory = WorkingMemory()
        for index in range(120):
            self.assertTrue(memory.add_turn("user", f"mensagem {index}"))
        self.assertEqual(memory.first_user_message(), "mensagem 0")
        self.assertEqual([t.turn_id for t in memory.turns], list(range(1, 121)))
        self.assertEqual(len(memory.recent_turns(5)), 5)

    def test_count_limit_preserves_every_previous_message(self):
        memory = WorkingMemory()
        for index in range(memory.MAX_TURNS):
            self.assertTrue(memory.add_turn("user", str(index)))
        self.assertFalse(memory.add_turn("user", "não cabe"))
        self.assertEqual(len(memory.turns), memory.MAX_TURNS)
        self.assertEqual(memory.first_user_message(), "0")

    def test_character_limit_counts_original_submission_too(self):
        memory = WorkingMemory()
        memory.MAX_CHARACTERS = 10
        self.assertTrue(memory.add_turn("user", "abc", submitted_text="ABC"))
        self.assertFalse(memory.add_turn("therion", "12345"))
        self.assertEqual(memory.session_characters, 6)
        self.assertEqual(memory.first_user_message(), "ABC")

    def test_large_input_rejected_without_poisoning_session(self):
        memory = WorkingMemory()
        self.assertFalse(memory.can_start_exchange("x" * 16_001))
        self.assertFalse(memory.session_full)
        self.assertTrue(memory.can_start_exchange("oi"))

    def test_clear_restarts_counters_and_first_message(self):
        memory = WorkingMemory()
        memory.add_turn("user", "antes")
        memory.session_full = True
        memory.clear_session()
        self.assertEqual(memory.session_characters, 0)
        self.assertFalse(memory.session_full)
        self.assertIsNone(memory.first_user_message())
        memory.add_turn("user", "depois")
        self.assertEqual(memory.turns[0].turn_id, 1)
        self.assertEqual(memory.first_user_message(), "depois")

    def test_new_instances_do_not_share_session(self):
        first = WorkingMemory()
        first.add_turn("user", "privado")
        self.assertIsNone(WorkingMemory().first_user_message())

    def test_task_history_is_bounded(self):
        memory = WorkingMemory()
        for index in range(memory.MAX_TURNS + 1):
            memory.start_task(str(index))
            memory.complete_task()
        self.assertEqual(len(memory.history), memory.MAX_TURNS)
        self.assertEqual(memory.history[0].command, "0")

    def test_response_at_individual_limit_is_preserved(self):
        memory = WorkingMemory()
        text = "x" * memory.MAX_MESSAGE_CHARACTERS
        self.assertTrue(memory.add_turn("therion", text))
        self.assertEqual(memory.turns[0].text, text)

    def test_exchange_budget_reserves_confirmation(self):
        memory = WorkingMemory()
        memory.MAX_TURNS = 3
        self.assertTrue(memory.can_start_exchange("pedido"))
        memory.add_turn("user", "pedido")
        self.assertFalse(memory.can_start_exchange("outro pedido"))
        self.assertTrue(memory.add_turn("therion", "Confirmar?"))
        self.assertTrue(memory.add_turn("therion", "Cancelado."))


class TestSessionJournalIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.orch = Orchestrator(simulate=True, log_dir=self.temp.name)

    def test_exact_recovery_without_ai_or_execution(self):
        original = "Meu nome é Marcus.\nEstudo Circuitos Lógicos."
        self.orch.memory.add_turn("user", original)
        for _ in range(60):
            self.orch.memory.add_turn("therion", "outra resposta")
        self.orch.ai_core = MagicMock()
        self.orch.executor = MagicMock()
        result = self.orch.process_command(
            "Qual foi a primeira mensagem que enviei nesta sessão?"
        )
        self.assertEqual(result.message, "Sua primeira mensagem nesta sessão foi:\n" + original)
        self.orch.ai_core.classify_detailed.assert_not_called()
        self.assertEqual(self.orch.executor.mock_calls, [])

    def test_first_message_query_variations_use_exact_record_without_ai(self):
        original = "Esta é a primeira mensagem da nova sessão."
        self.orch.memory.add_turn("user", original)
        self.orch.ai_core = MagicMock()
        self.orch.executor = MagicMock()
        queries = (
            "qual foi a primeira mensagem dessa sessão?",
            "Qual foi a primeira mensagem desta sessão?",
            "Qual foi a minha primeira mensagem na sessão?",
            "Qual é minha primeira mensagem nesta sessão?",
            "QUAL FOI A PRIMEIRA MENSAGEM DESSA SESSÃO?!",
            "  Qual   foi a primeira mensagem dessa sessao ?  ",
            "Qual foi a primeira mensagem que eu enviei a você nesta sessão?",
            "Qual foi a primeira coisa que eu te pedi nessa sessão?",
        )
        for query in queries:
            with self.subTest(query=query):
                result = self.orch.process_command(query)
                self.assertEqual(
                    result.message, "Sua primeira mensagem nesta sessão foi:\n" + original,
                )
        self.assertEqual(self.orch.ai_core.mock_calls, [])
        self.assertEqual(self.orch.executor.mock_calls, [])

    def test_unrelated_or_combined_commands_are_not_memory_queries(self):
        for command in (
            "Qual foi a última mensagem dessa sessão?",
            "Qual foi a primeira mensagem do arquivo?",
            "Qual foi a primeira mensagem dessa sessão? Abra o Obsidian.",
            "Não diga qual foi a primeira mensagem dessa sessão",
            "Qual foi a primeira mensagem que o Therion enviou nesta sessão?",
            "Qual foi o primeiro plano desta sessão?",
        ):
            with self.subTest(command=command):
                self.assertFalse(_is_first_message_query(command))

    def test_query_as_first_message_returns_itself(self):
        query = "Qual foi minha primeira mensagem nessa sessão?"
        result = self.orch.process_command(query)
        self.assertEqual(result.message, "Sua primeira mensagem nesta sessão foi:\n" + query)

    def test_original_scope_submission_preserved(self):
        original = "raízes: :: liste meus aliases"
        self.orch.process_command(original)
        self.assertEqual(self.orch.memory.first_user_message(), original)
        self.assertEqual(self.orch.memory.turns[0].text, "liste meus aliases")

    def test_rejected_input_does_not_start_task_or_call_ai(self):
        self.orch.ai_core = MagicMock()
        result = self.orch.process_command("x" * 16_001)
        self.assertEqual(result.status, "session_limit")
        self.assertIsNone(self.orch.memory.current_task)
        self.assertEqual(len(self.orch.memory.turns), 0)
        self.assertEqual(self.orch.ai_core.mock_calls, [])

    def test_full_session_does_not_execute_or_drop_history(self):
        self.orch.memory.MAX_TURNS = 3
        self.orch.memory.add_turn("user", "primeira")
        self.orch.executor = MagicMock()
        result = self.orch.process_command("Abra o Obsidian.")
        self.assertEqual(result.status, "session_limit")
        self.assertEqual(self.orch.memory.first_user_message(), "primeira")
        self.assertEqual(self.orch.executor.mock_calls, [])

    def test_oversized_response_is_not_silently_lost(self):
        result = OrchestrationResult(status="success", message="x" * 16_001)
        self.orch._finalize_session_result(result)
        self.assertIn("não foi registrada", result.message)
        self.assertTrue(self.orch.memory.session_full)

    def test_clear_discards_tasks_plans_and_intermediate_flows(self):
        self.orch.memory.start_task("antes")
        self.orch.memory.complete_task()
        self.orch.memory.add_turn("user", "antes")
        self.orch._alias_flow_step = "awaiting_target"
        self.orch._pending_alias_keyword = "teste"
        self.orch._pending_event_draft = {"title": "teste"}
        self.orch._open_app_flow_active = True
        self.orch._pending_clarification = "pergunta"
        self.orch.clear_session()
        self.assertEqual(self.orch.memory.history, [])
        self.assertIsNone(self.orch.memory.current_task)
        self.assertIsNone(self.orch.memory.first_user_message())
        self.assertIsNone(self.orch._alias_flow_step)
        self.assertIsNone(self.orch._pending_alias_keyword)
        self.assertIsNone(self.orch._pending_event_draft)
        self.assertIsNone(self.orch._pending_clarification)
        self.assertFalse(self.orch._open_app_flow_active)

    def test_interactive_flow_has_priority_over_memory_query(self):
        self.orch._alias_flow_step = "awaiting_keyword"
        result = self.orch.process_command("Qual foi minha primeira mensagem nessa sessão?")
        self.assertNotIn("Sua primeira mensagem", result.message)

    def test_new_session_returns_new_first_message(self):
        self.orch.memory.add_turn("user", "sessão antiga")
        self.orch.clear_session()
        query = "Qual foi minha primeira mensagem nesta sessão?"
        result = self.orch.process_command(query)
        self.assertEqual(result.message, "Sua primeira mensagem nesta sessão foi:\n" + query)


class TestSessionClearInterface(unittest.TestCase):
    def test_pending_confirmation_prevents_clear_and_voice_cancel(self):
        from therion.interface.desktop import MainWindow
        window = MagicMock()
        window._processing = False
        window._pending_plan = object()
        MainWindow._clear_conversation(window)
        window._cancel_voice_if_active.assert_not_called()
        window._history.clear.assert_not_called()
        window._orchestrator.clear_session.assert_not_called()

    def test_safe_clear_cancels_voice_before_resetting_session(self):
        from therion.interface.desktop import MainWindow
        window = MagicMock()
        window._processing = False
        window._pending_plan = None
        MainWindow._clear_conversation(window)
        self.assertEqual(
            [str(call) for call in window.mock_calls],
            ["call._cancel_voice_if_active()", "call._history.clear()",
             "call._orchestrator.clear_session()"],
        )


if __name__ == "__main__":
    unittest.main()
