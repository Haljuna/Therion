"""Testes de integração Orchestrator ↔ calendário (Bloco A mockado)."""

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.models import CalendarEvent
from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator


class MockCalendarAdapter(CalendarAdapter):
    """Adapter mockado configurável para testes."""

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events = events or []
        self._raise_error = False

    def list_events_for_day(self, day: date) -> list[CalendarEvent]:
        if self._raise_error:
            raise CalendarError("Erro simulado")
        return self._events

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> CalendarEvent:
        if self._raise_error:
            raise CalendarError("Erro simulado")
        return CalendarEvent(
            event_id="new_event",
            summary=summary,
            start=start,
            end=end,
            all_day=False,
        )


class TestIntentRecognizerCalendar(unittest.TestCase):
    """Valida reconhecimento de intenções de calendário."""

    def setUp(self) -> None:
        self.recognizer = IntentRecognizer()

    def test_intent_calendar_today_basic(self) -> None:
        """1. IntentRecognizer reconhece 'Therion, o que tenho hoje?'."""
        intent = self.recognizer.parse("Therion, o que tenho hoje?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "calendário hoje")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_intent_calendar_today_variations(self) -> None:
        """2. Variações de comandos de calendário são reconhecidas."""
        variations = [
            "o que tenho hoje?",
            "o que ha hoje",
            "o que está hoje",
            "minha agenda",
            "minha agenda de hoje",
            "agenda de hoje",
            "compromissos de hoje",
            "compromisso de hoje",
            "eventos de hoje",
            "evento de hoje",
            "Therion, o que tenho hoje?",
            "therion, minha agenda",
        ]
        for cmd in variations:
            with self.subTest(cmd=cmd):
                intent = self.recognizer.parse(cmd)
                self.assertIsNotNone(intent, f"Comando não reconhecido: {cmd}")
                self.assertEqual(intent.action, "calendário hoje")

    def test_intent_calendar_not_calendar_commands(self) -> None:
        """3. Comandos que não são de calendário não retornam intent de calendário."""
        non_calendar = [
            "o que tenho amanhã",
            "abra o Obsidian",
            "liste meus aliases",
            "procure no Segundo Cérebro teste",
        ]
        for cmd in non_calendar:
            with self.subTest(cmd=cmd):
                intent = self.recognizer.parse(cmd)
                if intent:
                    self.assertNotEqual(intent.action, "calendário hoje")


class TestOrchestratorCalendar(unittest.TestCase):
    """Valida integração do Orchestrator com calendário."""

    def test_orchestrator_without_adapter(self) -> None:
        """4. Orchestrator sem adapter retorna 'Calendário não disponível'."""
        orch = Orchestrator(simulate=True)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Calendário não disponível.")

    def test_orchestrator_with_empty_calendar(self) -> None:
        """5. Orchestrator com adapter vazio retorna 'Nenhum evento para hoje'."""
        adapter = MockCalendarAdapter(events=[])
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "success")
        self.assertIn("Nenhum compromisso para hoje", result.message)

    def test_orchestrator_with_adapter_error(self) -> None:
        """6. Orchestrator com adapter que retorna erro controlado."""
        adapter = MockCalendarAdapter()
        adapter._raise_error = True
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "execution_failed")
        self.assertIn("Erro ao acessar calendário", result.message)

    def test_orchestrator_with_timed_event(self) -> None:
        """7. Orchestrator formata evento com horário corretamente."""
        event = CalendarEvent(
            "ev1",
            "Reunião de equipe",
            datetime(2026, 9, 15, 14, 0),
            datetime(2026, 9, 15, 15, 0),
            all_day=False,
        )
        adapter = MockCalendarAdapter(events=[event])
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "success")
        self.assertIn("Reunião de equipe", result.message)
        self.assertIn("14:00", result.message)

    def test_orchestrator_with_all_day_event(self) -> None:
        """8. Orchestrator formata evento de dia inteiro corretamente."""
        event = CalendarEvent(
            "ev2",
            "Feriado nacional",
            date(2026, 9, 15),
            date(2026, 9, 16),
            all_day=True,
        )
        adapter = MockCalendarAdapter(events=[event])
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "success")
        self.assertIn("Feriado nacional", result.message)
        self.assertIn("Dia inteiro", result.message)

    def test_orchestrator_multiple_events_sorted(self) -> None:
        """9. Orchestrator ordena eventos cronologicamente."""
        events = [
            CalendarEvent("ev2", "Tarde", datetime(2026, 9, 15, 14, 0), datetime(2026, 9, 15, 15, 0), False),
            CalendarEvent("ev1", "Manhã", datetime(2026, 9, 15, 9, 0), datetime(2026, 9, 15, 10, 0), False),
            CalendarEvent("ev3", "Feriado", date(2026, 9, 15), date(2026, 9, 16), True),
        ]
        adapter = MockCalendarAdapter(events=events)
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        result = orch.process_command("Therion, o que tenho hoje?")
        self.assertEqual(result.status, "success")
        msg = result.message
        idx_feriado = msg.index("Feriado")
        idx_manha = msg.index("Manhã")
        idx_tarde = msg.index("Tarde")
        self.assertLess(idx_feriado, idx_manha)
        self.assertLess(idx_manha, idx_tarde)

    def test_orchestrator_calendar_registers_in_memory(self) -> None:
        """10. Consulta de calendário registra turno na memória de sessão."""
        adapter = MockCalendarAdapter(events=[])
        orch = Orchestrator(simulate=True, calendar_adapter=adapter)
        orch.process_command("Therion, o que tenho hoje?")
        user_turns = [t for t in orch.memory.turns if t.role == "user"]
        therion_turns = [t for t in orch.memory.turns if t.role == "therion"]
        self.assertEqual(len(user_turns), 1)
        self.assertEqual(len(therion_turns), 1)


if __name__ == "__main__":
    unittest.main()
