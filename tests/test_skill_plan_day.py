"""Testes unitários da SKILL-002 — Planejar meu dia."""

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.models import CalendarEvent
from therion.context.second_brain import SecondBrainReader, SearchResult
from therion.skills.plan_day import PlanDaySkill, SkillResult, _READ_ONLY_WARNING
from therion.skills.registry import get_skill, list_skills


DAY = date(2026, 9, 17)


def _timed(summary: str, hour: int, minute: int = 0) -> CalendarEvent:
    s = datetime(2026, 9, 17, hour, minute)
    e = datetime(2026, 9, 17, hour + 1, minute)
    return CalendarEvent(event_id=f"ev_{hour}", summary=summary, start=s, end=e, all_day=False)


def _allday(summary: str) -> CalendarEvent:
    return CalendarEvent(
        event_id=f"ev_{summary}", summary=summary,
        start=date(2026, 9, 17), end=date(2026, 9, 18), all_day=True,
    )


class FakeCalendar:
    def __init__(self, events=None, raise_error=False):
        self._events = events or []
        self._raise = raise_error

    def list_events_for_day(self, day):
        if self._raise:
            raise CalendarError("falha simulada")
        return self._events


class FakeSB:
    def __init__(self, results=None, raise_error=False):
        self._results = results or {}
        self._raise = raise_error
        self.calls = []

    def search_notes(self, term, max_results=5):
        self.calls.append(term)
        if self._raise:
            raise RuntimeError("falha simulada")
        return list(self._results.get(term, []))[:max_results]


# ---- Registry ----

class TestRegistry(unittest.TestCase):
    def test_get_returns_class(self):
        self.assertIs(get_skill("SKILL-002"), PlanDaySkill)

    def test_list_contains(self):
        self.assertIn("SKILL-002", list_skills())

    def test_unknown_raises_key_error(self):
        with self.assertRaises(KeyError) as ctx:
            get_skill("SKILL-999")
        self.assertIn("SKILL-999", str(ctx.exception))


# ---- Ordenação ----

class TestOrdering(unittest.TestCase):
    def test_sorted_by_start(self):
        cal = FakeCalendar([_timed("Tarde", 14), _timed("Manha", 9), _timed("Meio", 12)])
        skill = PlanDaySkill(cal, FakeSB())
        r = skill.execute(today=DAY)
        self.assertIn("1. Manha — 09:00", r.message)
        self.assertIn("2. Meio — 12:00", r.message)
        self.assertIn("3. Tarde — 14:00", r.message)


# ---- Dia inteiro ----

class TestAllDay(unittest.TestCase):
    def test_allday_after_timed(self):
        cal = FakeCalendar([_timed("Reuniao", 10), _allday("Feriado")])
        skill = PlanDaySkill(cal, FakeSB())
        r = skill.execute(today=DAY)
        i_comp = r.message.index("Compromissos:")
        i_dia = r.message.index("Dia inteiro:")
        self.assertLess(i_comp, i_dia)
        self.assertIn("1. Feriado — Dia inteiro", r.message)


# ---- Buscas literais ----

class TestSearches(unittest.TestCase):
    def test_only_literal_terms(self):
        sb = FakeSB()
        PlanDaySkill(FakeCalendar(), sb).execute(today=DAY)
        self.assertEqual(sb.calls, ["prioridades", "tarefas"])

    def test_max_three_results(self):
        many = [SearchResult(path=f"n{i}.md", snippet=f"s{i}") for i in range(10)]
        sb = FakeSB({"prioridades": many, "tarefas": []})
        r = PlanDaySkill(FakeCalendar(), sb).execute(today=DAY)
        self.assertIn("s0", r.message)
        self.assertIn("s1", r.message)
        self.assertIn("s2", r.message)
        self.assertNotIn("s3", r.message)


# ---- Calendário indisponível ----

class TestCalendarDown(unittest.TestCase):
    def test_none_calendar_partial(self):
        sb = FakeSB({"prioridades": [SearchResult("p.md", "pri A")], "tarefas": []})
        r = PlanDaySkill(None, sb).execute(today=DAY)
        self.assertEqual(r.status, "partial")
        self.assertIn("pri A", r.message)

    def test_calendar_error_partial(self):
        sb = FakeSB({"prioridades": [], "tarefas": []})
        r = PlanDaySkill(FakeCalendar(raise_error=True), sb).execute(today=DAY)
        self.assertEqual(r.status, "partial")


# ---- Segundo Cérebro vazio ----

class TestSBEmpty(unittest.TestCase):
    def test_empty_sb_keeps_calendar(self):
        cal = FakeCalendar([_timed("Reuniao", 10)])
        r = PlanDaySkill(cal, FakeSB()).execute(today=DAY)
        self.assertEqual(r.status, "success")
        self.assertIn("Reuniao", r.message)


# ---- SB falhou ----

class TestSBDown(unittest.TestCase):
    def test_sb_error_partial_with_calendar(self):
        cal = FakeCalendar([_timed("Reuniao", 10)])
        r = PlanDaySkill(cal, FakeSB(raise_error=True)).execute(today=DAY)
        self.assertEqual(r.status, "partial")
        self.assertIn("Reuniao", r.message)


# ---- Ambas indisponíveis ----

class TestBothDown(unittest.TestCase):
    def test_unavailable(self):
        r = PlanDaySkill(None, FakeSB(raise_error=True)).execute(today=DAY)
        self.assertEqual(r.status, "unavailable")
        self.assertIn("indisponíveis", r.message)


# ---- Sem escrita ----

class TestNoWrites(unittest.TestCase):
    def test_no_create_event(self):
        cal = MagicMock(spec=CalendarAdapter)
        cal.list_events_for_day.return_value = []
        PlanDaySkill(cal, FakeSB()).execute(today=DAY)
        cal.list_events_for_day.assert_called_once()
        self.assertFalse(cal.create_event.called)


# ---- Read-only warning ----

class TestReadOnly(unittest.TestCase):
    def test_success_ends_with_warning(self):
        r = PlanDaySkill(FakeCalendar(), FakeSB()).execute(today=DAY)
        self.assertTrue(r.message.endswith(_READ_ONLY_WARNING))

    def test_partial_ends_with_warning(self):
        r = PlanDaySkill(None, FakeSB()).execute(today=DAY)
        self.assertTrue(r.message.endswith(_READ_ONLY_WARNING))

    def test_unavailable_ends_with_warning(self):
        r = PlanDaySkill(None, FakeSB(raise_error=True)).execute(today=DAY)
        self.assertTrue(r.message.endswith(_READ_ONLY_WARNING))


if __name__ == "__main__":
    unittest.main()
