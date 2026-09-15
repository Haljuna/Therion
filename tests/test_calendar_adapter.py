"""Testes unitários do CalendarAdapter (Bloco A mockado)."""

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.models import CalendarEvent


class DummyCalendarAdapter(CalendarAdapter):
    """Adapter mockado para testes."""

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self._events = events or []
        self._raise_error = False

    def list_events_for_day(self, day: date) -> list[CalendarEvent]:
        if self._raise_error:
            raise CalendarError("Erro simulado de calendário")
        return self._events


class TestCalendarEventModel(unittest.TestCase):
    """Valida o modelo CalendarEvent."""

    def test_timed_event(self) -> None:
        """1. CalendarEvent com horário: all_day=False, start/end como datetime."""
        start = datetime(2026, 9, 15, 14, 0)
        end = datetime(2026, 9, 15, 15, 0)
        event = CalendarEvent(
            event_id="ev1",
            summary="Reunião",
            start=start,
            end=end,
            all_day=False,
        )
        self.assertEqual(event.event_id, "ev1")
        self.assertEqual(event.summary, "Reunião")
        self.assertEqual(event.start, start)
        self.assertEqual(event.end, end)
        self.assertFalse(event.all_day)
        self.assertIsNone(event.description)

    def test_all_day_event(self) -> None:
        """2. CalendarEvent de dia inteiro: all_day=True, start/end como date."""
        start = date(2026, 9, 15)
        end = date(2026, 9, 16)
        event = CalendarEvent(
            event_id="ev2",
            summary="Feriado",
            start=start,
            end=end,
            all_day=True,
            description="Dia nacional",
        )
        self.assertTrue(event.all_day)
        self.assertEqual(event.description, "Dia nacional")
        self.assertIsInstance(event.start, date)
        self.assertNotIsInstance(event.start, datetime)

    def test_description_is_optional(self) -> None:
        """3. description é opcional (None por padrão)."""
        event = CalendarEvent(
            event_id="ev3",
            summary="Sem descrição",
            start=datetime(2026, 9, 15, 10, 0),
            end=datetime(2026, 9, 15, 11, 0),
            all_day=False,
        )
        self.assertIsNone(event.description)


class TestCalendarAdapter(unittest.TestCase):
    """Valida o comportamento do CalendarAdapter."""

    def test_returns_timed_events(self) -> None:
        """4. Adapter retorna eventos com horário corretamente."""
        start = datetime(2026, 9, 15, 14, 0)
        end = datetime(2026, 9, 15, 15, 0)
        event = CalendarEvent("ev1", "Reunião", start, end, all_day=False)
        adapter = DummyCalendarAdapter(events=[event])
        result = adapter.list_events_for_day(date(2026, 9, 15))
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].all_day)

    def test_returns_all_day_events(self) -> None:
        """5. Adapter retorna eventos de dia inteiro corretamente."""
        event = CalendarEvent(
            "ev2", "Feriado", date(2026, 9, 15), date(2026, 9, 16), all_day=True
        )
        adapter = DummyCalendarAdapter(events=[event])
        result = adapter.list_events_for_day(date(2026, 9, 15))
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].all_day)

    def test_empty_calendar(self) -> None:
        """6. Adapter com agenda vazia retorna lista vazia sem erro."""
        adapter = DummyCalendarAdapter(events=[])
        result = adapter.list_events_for_day(date(2026, 9, 15))
        self.assertEqual(result, [])

    def test_api_error_raises_calendar_error(self) -> None:
        """7. Erro do provider levanta CalendarError controlada."""
        adapter = DummyCalendarAdapter()
        adapter._raise_error = True
        with self.assertRaises(CalendarError):
            adapter.list_events_for_day(date(2026, 9, 15))

    def test_multiple_events(self) -> None:
        """8. Adapter retorna múltiplos eventos."""
        events = [
            CalendarEvent("ev1", "Manhã", datetime(2026, 9, 15, 9, 0), datetime(2026, 9, 15, 10, 0), False),
            CalendarEvent("ev2", "Tarde", datetime(2026, 9, 15, 14, 0), datetime(2026, 9, 15, 15, 0), False),
            CalendarEvent("ev3", "Feriado", date(2026, 9, 15), date(2026, 9, 16), True),
        ]
        adapter = DummyCalendarAdapter(events=events)
        result = adapter.list_events_for_day(date(2026, 9, 15))
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main()
