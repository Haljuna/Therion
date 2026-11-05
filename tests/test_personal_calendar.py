"""Agenda pessoal com relógio e adapter controlados; sem Google."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.calendar.adapter import CalendarError
from therion.calendar.dialogue import parse_day, parse_time, partition_events
from therion.calendar.models import CalendarEvent
from therion.core.orchestrator import Orchestrator

TZ = ZoneInfo('America/Sao_Paulo')
NOW = datetime(2026, 10, 9, 10, tzinfo=TZ)


@pytest.fixture
def orch(tmp_path):
    adapter = MagicMock()
    adapter.list_events_for_day.return_value = []
    adapter.create_event.side_effect = lambda **kw: CalendarEvent('fake', kw['summary'], kw['start'], kw['end'], False)
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=adapter)
    instance._now_func = lambda: NOW
    return instance


@pytest.mark.parametrize('raw,expected', [
    ('hoje', date(2026, 10, 9)), ('amanha', date(2026, 10, 10)),
    ('sexta', date(2026, 10, 9)), ('próxima sexta-feira', date(2026, 10, 16)),
    ('quinta', date(2026, 10, 15)), ('10/10', date(2026, 10, 10)),
    ('20/12/2027', date(2027, 12, 20)), ('dia 12', date(2026, 10, 12)),
])
def test_dates_are_resolved_without_silent_rollover(raw, expected):
    assert parse_day(raw, NOW) == expected


@pytest.mark.parametrize('raw', ['31/02', '32/10', '29/02/2025', 'algum dia'])
def test_invalid_dates_are_controlled(raw):
    with pytest.raises(CalendarError):
        parse_day(raw, NOW)


@pytest.mark.parametrize('raw,expected', [('15h30', (15,30)), ('15:30', (15,30)), ('15h', (15,0)), ('00:00', (0,0))])
def test_exact_time_parsing(raw, expected):
    assert parse_time(raw) == expected


@pytest.mark.parametrize('raw', ['24h', '15h99', '15:30 lixo', '15:300'])
def test_invalid_times_are_not_partially_accepted(raw):
    with pytest.raises(CalendarError):
        parse_time(raw)


@pytest.mark.parametrize('phrase,start,end,minutes', [
    ('às 15h30 por 30 minutos', '15:30', '16:00', 30),
    ('das 15h às 16h30', '15:00', '16:30', 90),
    ('às 15:10 por uma hora', '15:10', '16:10', 60),
    ('às 15h por meia hora', '15:00', '15:30', 30),
    ('às 15h por 1 hora e 30 minutos', '15:00', '16:30', 90),
    ('às 15h', '15:00', '16:00', 60),
])
def test_display_and_write_use_identical_times(orch, phrase, start, end, minutes):
    result = orch.process_command('marque reunião amanhã ' + phrase)
    assert result.status == 'awaiting_confirmation'
    assert f'{start}–{end}' in result.message
    assert f'Duração: {minutes} minutos' in result.message
    orch.calendar_adapter.create_event.assert_not_called()
    assert orch.process_command('sim').status == 'success'
    args = orch.calendar_adapter.create_event.call_args.kwargs
    assert args['start'].strftime('%H:%M') == start
    assert args['end'].strftime('%H:%M') == end
    assert args['end'] - args['start'] == timedelta(minutes=minutes)
    assert args['summary'] == 'Reunião'


@pytest.mark.parametrize('command', [
    'marque reunião 31/02 às 15h', 'marque reunião amanhã às 25h',
    'marque reunião amanhã às 15h99', 'marque reunião hoje às 9h',
    'marque reunião amanhã das 16h às 15h', 'marque reunião amanhã às 15h por 0 minutos',
    'marque reunião amanhã das 15h às 16h por 30 minutos',
    'marque reunião hoje amanhã às 15h',
])
def test_invalid_or_conflicting_proposal_never_writes(orch, command):
    result = orch.process_command(command)
    assert 'Vou criar:' not in result.message
    orch.process_command('sim')
    orch.calendar_adapter.create_event.assert_not_called()


def test_unrelated_correction_does_not_clear_date_conflict(orch):
    orch.process_command('marque reunião hoje amanhã às 15h')
    orch.process_command('mude para 16h')
    orch.process_command('sim')
    orch.calendar_adapter.create_event.assert_not_called()
    assert 'Vou criar:' in orch.process_command('troque para amanhã').message
    assert orch.process_command('sim').status == 'success'


def test_corrections_require_current_proposal_confirmation(orch):
    first = orch.process_command('marque reunião amanhã às 15h30 por 30 minutos')
    session, token = orch.session_id, first.confirmation_id
    revised = orch.process_command('mude a duração para 90 minutos')
    assert '15:30–17:00' in revised.message
    assert orch.process_session_command('sim', session, token).status == 'cancelled'
    orch.process_command('o nome é Consulta')
    revised = orch.process_command('troque para 20/12')
    assert '15:30–17:00' in revised.message
    orch.calendar_adapter.create_event.assert_not_called()
    assert orch.process_command('sim').status == 'success'
    args = orch.calendar_adapter.create_event.call_args.kwargs
    assert args['summary'] == 'Consulta'
    assert args['start'].date() == date(2026, 12, 20)


def test_explicit_duration_can_replace_conflicting_interval(orch):
    orch.process_command('marque reunião amanhã das 15h às 16h por 30 minutos')
    assert '15:00–15:30' in orch.process_command('mude a duração para 30 minutos').message
    assert orch.process_command('sim').status == 'success'


def test_duration_crossing_midnight_shows_actual_end_date(orch):
    result = orch.process_command('marque reunião amanhã às 23h por 2 horas')
    assert '23:00–01:00' in result.message
    assert 'término em 11/10/2026' in result.message
    orch.process_command('sim')
    assert orch.calendar_adapter.create_event.call_args.kwargs['end'].date() == date(2026, 10, 11)


@pytest.mark.parametrize('command,day', [
    ('agenda de amanhã', date(2026,10,10)), ('o que tenho quinta-feira?', date(2026,10,15)),
    ('minha agenda de próxima sexta', date(2026,10,16)), ('eventos de 12/10', date(2026,10,12)),
])
def test_queries_use_configured_date_and_never_write(orch, command, day):
    assert orch.process_command(command).status == 'success'
    orch.calendar_adapter.list_events_for_day.assert_called_once_with(day)
    orch.calendar_adapter.create_event.assert_not_called()


def test_seven_day_query_reports_partial_failures_without_claiming_free_days(orch):
    def listing(day):
        if day == NOW.date() + timedelta(days=1):
            raise CalendarError('simulado')
        return []
    orch.calendar_adapter.list_events_for_day.side_effect = listing
    result = orch.process_command('agenda dos próximos sete dias')
    assert result.status == 'success'
    assert 'Consulta parcial' in result.message
    assert '2026-10-10' in result.message
    assert len(orch.calendar_adapter.list_events_for_day.call_args_list) == 7
    assert orch._last_tool_evidence['partial'] is True


def events():
    return [CalendarEvent(str(hour), title, NOW.replace(hour=hour), NOW.replace(hour=hour+1), False)
            for hour, title in [(8,'Encerrado'), (9,'Terminou agora'), (10,'Em andamento'), (11,'Próximo'), (12,'Depois')]] + [
            CalendarEvent('all', 'Dia inteiro', NOW.date(), NOW.date()+timedelta(days=1), True)]


def test_next_event_and_plan_day_distinguish_event_states(orch):
    available = events()
    orch.calendar_adapter.list_events_for_day.side_effect = lambda day: available if day == NOW.date() else []
    result = orch.process_command('qual é meu próximo compromisso?')
    assert 'Em andamento: Em andamento' in result.message
    assert 'Próximo compromisso: Próximo' in result.message
    assert 'Próximo compromisso: Encerrado' not in result.message
    assert 'Dia inteiro:' in result.message
    assert orch.calendar_adapter.list_events_for_day.call_count == 7
    result = orch.process_command('planeje meu dia')
    assert 'Em andamento: Em andamento' in result.message
    assert 'Próximo compromisso: Próximo' in result.message
    orch.calendar_adapter.create_event.assert_not_called()


def test_partition_boundary_and_deduplication(orch):
    parts = partition_events(events(), NOW)
    assert len(parts['past']) == 2
    assert len(parts['ongoing']) == 1
    assert len(parts['future']) == 2
    assert len(parts['all_day']) == 1
    orch.calendar_adapter.list_events_for_day.return_value = [events()[3]]
    result = orch.process_command('agenda próximos 7 dias')
    assert '1 compromisso para' in result.message
