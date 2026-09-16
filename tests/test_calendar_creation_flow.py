"""Testes para o fluxo conversacional de criação de evento no calendário (C1)."""

import unittest
from unittest.mock import MagicMock
from therion.core.orchestrator import Orchestrator

class TestCalendarCreationFlow(unittest.TestCase):
    def setUp(self):
        self.orc = Orchestrator()
        self.mock_adapter = MagicMock()
        self.orc.calendar_adapter = self.mock_adapter

    def test_intent_parsing_full(self):
        res = self.orc.process_command("marque reunião amanhã às 15h")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("Vou criar", res.message)
        self.assertIn("Título: Reunião", res.message)
        self.assertIn("Data: amanhã", res.message)
        self.assertIn("15:00", res.message)

    def test_missing_title(self):
        res = self.orc.process_command("marque amanhã às 15h")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("título", res.message.lower())

    def test_missing_date(self):
        res = self.orc.process_command("marque reunião às 15h")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("data", res.message.lower())

    def test_missing_time(self):
        res = self.orc.process_command("marque reunião amanhã")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("horas", res.message.lower())

    def test_default_duration_and_summary(self):
        res = self.orc.process_command("marque reunião amanhã às 15h")
        self.assertEqual(self.orc._pending_event_draft["duration_minutes"], 60)
        self.assertIn("15:00–16:00", res.message)

    def test_cancel_clears_state(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        self.assertIsNotNone(self.orc._pending_event_draft)
        res = self.orc.process_command("não")
        self.assertEqual(res.status, "cancelled")
        self.assertIsNone(self.orc._pending_event_draft)

    def test_ambiguity_keeps_state(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("talvez")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertTrue("ambígua" in res.message.lower() or "não reconhecida" in res.message.lower())
        self.assertIsNotNone(self.orc._pending_event_draft)

    def test_correction_time_re_presents_summary(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("mude para 16h")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("16:00–17:00", res.message)

    def test_correction_date_re_presents_summary(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("troque para hoje")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("Data: hoje", res.message)

    def test_correction_title_re_presents_summary(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("o nome é Reunião CAELE")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertIn("Título: Reunião caele", res.message)

    def test_confirm_only_after_summary_and_no_external_call(self):
        self.orc.process_command("marque reunião")
        res = self.orc.process_command("sim") 
        self.assertIn("horas", res.message.lower())
        
        self.orc._reset_calendar_create_flow()
        
        # Com MagicMock adapter, confirmação completa chama create_event
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("sim")
        self.assertEqual(res.status, "success")
        self.assertIsNone(self.orc._pending_event_draft)
        self.mock_adapter.create_event.assert_called_once()

    def test_existing_flows_continue_working(self):
        res = self.orc.process_command("liste meus aliases")
        self.assertEqual(res.status, "success")
        res = self.orc.process_command("agenda de hoje")
        self.assertEqual(res.status, "success")

if __name__ == "__main__":
    unittest.main()
