"""A voz precisa dizer os compromissos, não só que eles existem."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.calendar.models import CalendarEvent
from therion.calendar.spoken import spoken_day, spoken_time, plural_compromissos
from therion.core.orchestrator import Orchestrator

TZ = ZoneInfo('America/Sao_Paulo')
NOW = datetime(2026, 11, 3, 20, 45, tzinfo=TZ)
TOMORROW = NOW.date() + timedelta(days=1)


@pytest.fixture
def orch(tmp_path):
    adapter = MagicMock()
    adapter.list_events_for_day.return_value = []
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=adapter)
    instance._now_func = lambda: NOW
    return instance


def tomorrow_events():
    start = datetime.combine(TOMORROW, datetime.min.time(), TZ)
    return [CalendarEvent('a', 'Aniversário Guilherme', TOMORROW, TOMORROW + timedelta(days=1), True),
            CalendarEvent('b', 'Reunião de negócios', start.replace(hour=15), start.replace(hour=16), False)]


@pytest.mark.parametrize('hour,minute,expected', [
    (15, 0, 'às 15 horas'), (15, 30, 'às 15 e 30'), (9, 5, 'às 9 e 5'),
    (1, 0, 'à 1 hora'), (12, 0, 'ao meio-dia'), (0, 0, 'à meia-noite'),
])
def test_spoken_time(hour, minute, expected):
    assert spoken_time(hour, minute) == expected


def test_spoken_day():
    assert spoken_day(NOW.date(), NOW.date()) == 'hoje'
    assert spoken_day(TOMORROW, NOW.date()) == 'amanhã'
    assert spoken_day(date(2026, 11, 20), NOW.date()) == 'em 20 de novembro'


def test_plural():
    assert plural_compromissos(1) == '1 compromisso'
    assert plural_compromissos(2) == '2 compromissos'


def test_voice_reads_each_event_of_tomorrow(orch):
    orch.calendar_adapter.list_events_for_day.side_effect = lambda day: tomorrow_events() if day == TOMORROW else []
    result = orch.process_command('eu tenho algum compromisso amanhã?')
    speech = result.speech_message
    assert 'Aniversário Guilherme' in speech
    assert 'Reunião de negócios' in speech
    assert 'às 15 horas' in speech
    assert speech.startswith('Amanhã você tem 2 compromissos')
    assert '(s)' not in speech and '/' not in speech


def test_followup_qual_e_o_compromisso_also_reads_events(orch):
    orch.calendar_adapter.list_events_for_day.side_effect = lambda day: tomorrow_events() if day == TOMORROW else []
    orch.process_command('eu tenho algum compromisso amanhã?')
    result = orch.process_command('Qual é o compromisso?')
    assert 'Reunião de negócios' in (result.speech_message or '')


def test_empty_day_is_not_repeated_on_screen(orch):
    result = orch.process_command('O que eu tenho hoje?')
    assert result.message.count('Nenhum') <= 1
    assert 'nos dias consultados' not in result.message
    assert 'hoje' in result.speech_message


def test_display_uses_correct_plural(orch):
    orch.calendar_adapter.list_events_for_day.side_effect = lambda day: tomorrow_events() if day == TOMORROW else []
    result = orch.process_command('eu tenho algum compromisso amanhã?')
    assert '2 compromissos' in result.message
    assert '(s)' not in result.message


def test_this_week_queries_from_today_until_sunday(orch):
    # 04/11: "o que eu tenho na agenda para esta semana" dava "Não reconheci a data".
    result = orch.process_command('O que eu tenho na agenda para esta semana?')
    assert result.status == 'success', result.message
    days = [call.args[0] for call in orch.calendar_adapter.list_events_for_day.call_args_list]
    assert days[0] == NOW.date() and days[-1] == date(2026, 11, 8)  # terça a domingo
    assert 'entre 3 de novembro e 8 de novembro' in result.speech_message


def test_long_lists_are_summarized_in_speech(orch):
    start = datetime.combine(TOMORROW, datetime.min.time(), TZ)
    many = [CalendarEvent(str(h), f'Evento {h}', start.replace(hour=h), start.replace(hour=h, minute=30), False)
            for h in range(8, 18)]
    orch.calendar_adapter.list_events_for_day.side_effect = lambda day: many if day == TOMORROW else []
    speech = orch.process_command('agenda de amanhã').speech_message
    assert 'Evento 8' in speech
    assert 'Evento 17' not in speech
    assert 'mais' in speech and 'painel' in speech
