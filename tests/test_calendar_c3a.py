"""Testes C3A — ligação entre confirmação conversacional e CalendarAdapter.create_event."""

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from therion.calendar.adapter import CalendarError
from therion.calendar.models import CalendarEvent
from therion.core.orchestrator import Orchestrator


TZ = ZoneInfo("America/Sao_Paulo")
FIXED_NOW = datetime(2026, 9, 15, 10, 0, 0, tzinfo=TZ)  # terça-feira


class FakeCalendarAdapter:
    """Adapter falso para testes — grava chamadas, retorna evento controlado."""

    def __init__(self, return_event=None, raise_error=False):
        self.calls = []
        self.return_event = return_event or CalendarEvent(
            event_id="fake_001",
            summary="",
            start=datetime(2026, 9, 15, 15, 0, tzinfo=TZ),
            end=datetime(2026, 9, 15, 16, 0, tzinfo=TZ),
            all_day=False,
        )
        self.raise_error = raise_error

    def list_events_for_day(self, day):
        return []

    def create_event(self, summary, start, end):
        self.calls.append({"summary": summary, "start": start, "end": end})
        if self.raise_error:
            raise CalendarError("Erro simulado de calendário")
        evt = CalendarEvent(
            event_id="fake_001",
            summary=summary,
            start=start,
            end=end,
            all_day=False,
        )
        self.return_event = evt
        return evt


class TestC3AConfirmationToCreateEvent(unittest.TestCase):
    """C3A: confirmação 'sim' após resumo completo chama create_event."""

    def setUp(self):
        self.adapter = FakeCalendarAdapter()
        self.orc = Orchestrator(calendar_adapter=self.adapter)
        self.orc._now_func = lambda: FIXED_NOW

    def test_1_affirmative_calls_create_event_exactly_once(self):
        """1. Confirmação afirmativa chama create_event exatamente 1 vez."""
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("sim")
        self.assertEqual(res.status, "success")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_2_summary_correct(self):
        """2. Summary passado ao create_event está correto."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        self.assertEqual(self.adapter.calls[0]["summary"], "Reunião")

    def test_3_start_correct(self):
        """3. Start é timezone-aware com hora/minuto corretos."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.hour, 15)
        self.assertEqual(start.minute, 0)
        self.assertIsNotNone(start.tzinfo)

    def test_4_end_equals_start_plus_60(self):
        """4. End = start + 60 minutos (duração padrão)."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        end = self.adapter.calls[0]["end"]
        self.assertEqual(end - start, timedelta(minutes=60))

    def test_5_timezone_is_sao_paulo(self):
        """5. Timezone dos datetimes é America/Sao_Paulo."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(str(start.tzinfo), "America/Sao_Paulo")

    def test_6_no_does_not_call_create_event(self):
        """6. Resposta 'não' não chama create_event."""
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("não")
        self.assertEqual(res.status, "cancelled")
        self.assertEqual(len(self.adapter.calls), 0)

    def test_7_ambiguous_does_not_call_create_event(self):
        """7. Resposta ambígua não chama create_event."""
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("talvez")
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertEqual(len(self.adapter.calls), 0)

    def test_8_correction_before_confirm_uses_corrected_data(self):
        """8. Correção antes do 'sim' usa dados corrigidos no create_event."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("mude para 16h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.hour, 16)
        self.assertEqual(self.adapter.calls[0]["summary"], "Reunião")

    def test_9_success_message_includes_event_details(self):
        """9. Mensagem de sucesso confirma criação com detalhes do evento."""
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("sim")
        self.assertEqual(res.status, "success")
        self.assertIn("Evento criado", res.message)
        self.assertIn("Reunião", res.message)

    def test_10_calendar_error_returns_controlled_message(self):
        """10. CalendarError do adapter gera mensagem controlada."""
        error_adapter = FakeCalendarAdapter(raise_error=True)
        self.orc.calendar_adapter = error_adapter
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("sim")
        self.assertEqual(res.status, "execution_failed")
        self.assertIn("Erro ao criar evento", res.message)

    def test_11_state_cleaned_after_success(self):
        """11. Estado temporário é limpo após sucesso."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        self.assertIsNone(self.orc._pending_event_draft)

    def test_12_no_real_google_access(self):
        """12. Nenhum Google real é acessado — adapter falso usado."""
        self.orc.process_command("marque reunião amanhã às 15h")
        self.orc.process_command("sim")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertIsInstance(self.adapter, FakeCalendarAdapter)


class TestC3ACalendarAdapterNone(unittest.TestCase):
    """C3A: adapter None gera erro controlado."""

    def setUp(self):
        self.orc = Orchestrator()  # calendar_adapter=None

    def test_none_adapter_returns_execution_failed(self):
        self.orc.process_command("marque reunião amanhã às 15h")
        res = self.orc.process_command("sim")
        self.assertEqual(res.status, "execution_failed")
        self.assertIn("Calendário não disponível", res.message)
        self.assertIsNone(self.orc._pending_event_draft)


class TestC3ADateParsing(unittest.TestCase):
    """C3A: parsing de datas variadas."""

    def setUp(self):
        self.adapter = FakeCalendarAdapter()
        self.orc = Orchestrator(calendar_adapter=self.adapter)
        self.orc._now_func = lambda: FIXED_NOW

    def test_today(self):
        self.orc.process_command("marque teste hoje às 14h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.date(), date(2026, 9, 15))

    def test_tomorrow(self):
        self.orc.process_command("marque teste amanhã às 14h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.date(), date(2026, 9, 16))

    def test_explicit_date(self):
        self.orc.process_command("marque teste 20/12 às 10h")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.date(), date(2026, 12, 20))

    def test_time_with_minutes(self):
        self.orc.process_command("marque teste amanhã às 14:30")
        self.orc.process_command("sim")
        start = self.adapter.calls[0]["start"]
        self.assertEqual(start.hour, 14)
        self.assertEqual(start.minute, 30)


if __name__ == "__main__":
    unittest.main()
