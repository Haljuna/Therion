"""Cenários completos do assistente pessoal; somente arquivos e serviços fictícios."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.calendar.adapter import CalendarError
from therion.calendar.models import CalendarEvent
from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse, ProviderTimeoutError
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def system(tmp_path):
    root = tmp_path / 'vault' / '10 - Projetos' / 'Therion'
    root.mkdir(parents=True)
    (root / 'A.md').write_text('# Rotina\nPrimeira nota fictícia.', encoding='utf-8')
    (root / 'B.md').write_text('# Rotina\nSegunda nota fictícia.', encoding='utf-8')
    provider = MagicMock()
    provider.generate.return_value = AIResponse(type='chat', message='Podemos escolher uma prioridade.')
    provider.describe_result.return_value = None
    adapter = MagicMock()
    adapter.list_events_for_day.return_value = []
    adapter.create_event.side_effect = lambda **kw: CalendarEvent('fake', kw['summary'], kw['start'], kw['end'], False)
    orch = Orchestrator(vault_root=str(tmp_path / 'vault'), log_dir=str(tmp_path / 'logs'),
        calendar_adapter=adapter, ai_core=AICore(provider, []))
    orch._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    return orch, provider, adapter


def send(orch, command):
    return orch.process_session_command(command, orch.session_id, orch.confirmation_id)


def test_full_conversation_notes_tasks_corrected_event_and_session_clear(system):
    orch, provider, calendar = system
    assert send(orch, 'Estou cansado e preciso priorizar').status == 'success'
    assert send(orch, 'busque no segundo cérebro Rotina').status == 'success'
    assert 'Segunda nota fictícia' in send(orch, 'leia a segunda nota').message
    assert send(orch, 'resuma a primeira').status == 'success'
    send(orch, 'adicione tarefas: revisar, com calma; organizar arquivos')
    send(orch, 'conclua a tarefa 1')
    assert '2. [pendente]' in send(orch, 'liste tarefas pendentes').message
    send(orch, 'reabra a tarefa 1')
    first = send(orch, 'marque revisão amanhã às 15h30 por uma hora e meia')
    assert '15:30–17:00' in first.message
    old_token = first.confirmation_id
    revised = send(orch, 'mude a duração para 30 minutos')
    assert '15:30–16:00' in revised.message
    assert orch.process_session_command('sim', orch.session_id, old_token).status == 'cancelled'
    assert send(orch, 'sim').status == 'success'
    assert send(orch, 'sim').status == 'cancelled'
    calendar.create_event.assert_called_once()
    send(orch, 'marque reunião amanhã às 18h')
    assert send(orch, 'cancele!').status == 'cancelled'
    previous_session = orch.session_id
    orch.clear_session()
    assert not orch._session_tasks.list() and orch._note_results is None
    assert orch._last_tool_evidence is None and orch._pending_event_draft is None
    assert orch.process_session_command('adicione uma tarefa: atrasada', previous_session, None).status == 'cancelled'
    assert 'Faça uma busca' in send(orch, 'leia a segunda nota').message
    calendar.create_event.assert_called_once()


def test_provider_failure_does_not_disable_deterministic_utilities(system):
    orch, provider, calendar = system
    provider.generate.side_effect = ProviderTimeoutError('simulado')
    provider.describe_result.side_effect = ProviderTimeoutError('simulado')
    assert send(orch, 'me ajude a decidir').status == 'ai_timeout'
    assert send(orch, 'busque no segundo cérebro Rotina').status == 'success'
    assert 'Primeira nota fictícia' in send(orch, 'leia a primeira nota').message
    assert send(orch, 'adicione uma tarefa: estudar').status == 'success'
    assert send(orch, 'agenda de amanhã').status == 'success'
    send(orch, 'marque revisão amanhã às 15h30')
    assert send(orch, 'sim').status == 'success'
    calendar.create_event.assert_called_once()


def test_concurrent_confirmations_are_consumed_once_and_new_request_is_allowed(system):
    orch, _, calendar = system
    first = send(orch, 'marque revisão amanhã às 15h30')
    token, session = first.confirmation_id, orch.session_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: orch.process_session_command('sim', session, token), range(4)))
    assert sum(result.status == 'success' for result in results) == 1
    calendar.create_event.assert_called_once()
    send(orch, 'marque outra reunião amanhã às 17h')
    assert send(orch, 'sim').status == 'success'
    assert calendar.create_event.call_count == 2


def test_partial_calendar_does_not_change_note_selection_and_tasks_remain_readonly(system):
    orch, _, calendar = system
    send(orch, 'busque no segundo cérebro Rotina')
    today = orch._calendar_now().date()
    calendar.list_events_for_day.side_effect = lambda day: (_ for _ in ()).throw(CalendarError('simulado')) if day == today + timedelta(days=2) else []
    result = send(orch, 'agenda dos próximos sete dias')
    assert 'Consulta parcial' in result.message and calendar.list_events_for_day.call_count == 7
    assert send(orch, 'resuma a primeira').status == 'clarification'
    assert 'Primeira nota fictícia' in send(orch, '1').message
    assert not orch._session_tasks.list()
    calendar.create_event.assert_not_called()


def test_generic_result_after_calendar_requires_note_selection(system):
    orch, _, _ = system
    send(orch, 'busque no segundo cérebro Rotina')
    send(orch, 'agenda de amanhã')
    result = send(orch, 'abra esse resultado')
    assert result.status == 'clarification' and 'Você se refere a uma nota' in result.message
    assert 'Segunda nota fictícia' in send(orch, '2').message


@pytest.mark.parametrize('duration', ['-5 minutos', '30 segundos', 'duas horas', '0,5 minutos'])
def test_invalid_explicit_duration_is_never_silently_replaced_by_default(system, duration):
    orch, _, calendar = system
    result = send(orch, 'marque revisão amanhã às 15h por ' + duration)
    assert 'Vou criar:' not in result.message
    send(orch, 'sim')
    calendar.create_event.assert_not_called()
    assert '15:00–15:30' in send(orch, 'mude a duração para 30 minutos').message
    assert send(orch, 'sim').status == 'success'
    assert calendar.create_event.call_args.kwargs['summary'] == 'Revisão'


@pytest.mark.parametrize('extra', ['às -5h', '31/02/20266'])
def test_invalid_additional_field_does_not_allow_confirming_the_valid_part(system, extra):
    orch, _, calendar = system
    result = send(orch, 'marque revisão amanhã às 15h ' + extra)
    assert 'Vou criar:' not in result.message
    send(orch, 'sim')
    calendar.create_event.assert_not_called()


def test_configured_timezone_is_used_in_display_and_write(system):
    orch, _, calendar = system
    orch._calendar_tz = ZoneInfo('UTC')
    assert orch._calendar_now().hour == 13
    result = send(orch, 'marque revisão hoje às 14h30 por 45 minutos')
    assert '14:30–15:15' in result.message
    send(orch, 'sim')
    args = calendar.create_event.call_args.kwargs
    assert str(args['start'].tzinfo) == 'UTC' and args['start'].hour == 14


def test_midnight_does_not_move_a_reviewed_relative_date_automatically(system):
    orch, _, calendar = system
    first = send(orch, 'marque revisão hoje às 15h30')
    assert first.status == 'awaiting_confirmation'
    now = orch._calendar_now()
    orch._now_func = lambda: now + timedelta(days=1)
    result = send(orch, 'sim')
    assert result.status == 'awaiting_confirmation' and 'passou' in result.message
    calendar.create_event.assert_not_called()
    send(orch, 'mude o início para 16h30')
    send(orch, 'sim')
    calendar.create_event.assert_not_called()
    revised = send(orch, 'troque para hoje')
    assert '16:30–17:30' in revised.message
    assert send(orch, 'sim').status == 'success'
    assert calendar.create_event.call_args.kwargs['start'].date() == (now + timedelta(days=1)).date()


def test_start_and_title_corrections_refresh_confirmation(system):
    orch, _, calendar = system
    first = send(orch, 'marque revisão amanhã às 15h30 por 30 minutos')
    second = send(orch, 'mude o início para 16h15')
    third = send(orch, 'troque o título para Consulta')
    assert len({first.confirmation_id, second.confirmation_id, third.confirmation_id}) == 3
    assert '16:15–16:45' in third.message and 'Título: Consulta' in third.message
    calendar.create_event.assert_not_called()
    send(orch, 'sim')
    assert calendar.create_event.call_args.kwargs['summary'] == 'Consulta'


def test_read_calendar_converts_returned_event_time_to_configured_timezone(system):
    orch, _, calendar = system
    utc_start = datetime(2026, 10, 9, 14, 30, tzinfo=ZoneInfo('UTC'))
    calendar.list_events_for_day.return_value = [CalendarEvent('utc', 'Evento UTC', utc_start, utc_start + timedelta(hours=1), False)]
    result = send(orch, 'agenda de hoje')
    assert 'Evento UTC — 11:30' in result.message
    result = send(orch, 'planeje meu dia')
    assert 'Próximo compromisso: Evento UTC — 11:30' in result.message


def test_desktop_passes_timezone_from_existing_calendar_configuration(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from therion.interface.desktop import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, '_setup_tray', lambda self: None)
    monkeypatch.setattr(MainWindow, '_build_calendar_adapter', lambda self: MagicMock())
    monkeypatch.setattr(MainWindow, '_build_ai_core', lambda self: None)
    window = MainWindow(app, config={'calendar': {'time_zone': 'UTC'}})
    try:
        assert str(window._orchestrator._calendar_tz) == 'UTC'
    finally:
        window._closing = True
        window.close()


def test_invalid_configured_timezone_never_falls_back_to_wrong_calendar_time(tmp_path):
    calendar = MagicMock()
    orch = Orchestrator(log_dir=str(tmp_path), calendar_adapter=calendar, calendar_time_zone='Fuso/Invalido')
    result = send(orch, 'agenda de amanhã')
    assert result.status == 'execution_failed' and 'Fuso horário' in result.message
    result = send(orch, 'marque revisão amanhã às 15h')
    assert 'Vou criar:' not in result.message
    send(orch, 'sim')
    calendar.list_events_for_day.assert_not_called()
    calendar.create_event.assert_not_called()


def test_concurrent_task_batches_preserve_limits_and_atomicity(system):
    orch, _, _ = system
    session = orch.session_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: orch.process_session_command(
            'adicione tarefas: ' + ';'.join(f'lote {n} item {i}' for i in range(8)), session, None), range(4)))
    assert sum(result.status == 'success' for result in results) == 3
    assert len(orch._session_tasks.list()) == 24
    assert [item.id for item in orch._session_tasks.list()] == list(range(1, 25))
