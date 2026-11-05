from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.core.orchestrator import Orchestrator


@pytest.fixture
def orch(tmp_path):
    adapter = MagicMock()
    adapter.create_event.side_effect = lambda **kwargs: SimpleNamespace(summary=kwargs['summary'])
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=adapter)
    instance._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    return instance


@pytest.mark.parametrize('cancel', ['cancele.', 'cancelar!', 'não.', 'n?', 'CANCELA!!!'])
@pytest.mark.parametrize('command', ['marque reunião amanhã às 15h', 'crie um evento'])
def test_cancel_punctuation_at_each_collection_stage(orch, command, cancel):
    orch.process_command(command)
    result = orch.process_command(cancel)
    assert result.status == 'cancelled'
    assert orch._pending_event_draft is None
    orch.calendar_adapter.create_event.assert_not_called()


def test_correcting_current_proposal_never_writes_before_fresh_confirmation(orch):
    orch.process_command('marque reunião amanhã às 15h')
    result = orch.process_command('troque para hoje')
    assert result.status == 'awaiting_confirmation'
    assert orch._pending_event_draft['date'] == 'hoje'
    orch.calendar_adapter.create_event.assert_not_called()
    result = orch.process_command('sim.')
    assert result.status == 'success'
    assert orch.calendar_adapter.create_event.call_args.kwargs['start'].date().isoformat() == '2026-10-09'
    orch.calendar_adapter.create_event.assert_called_once()


def test_another_event_discards_every_previous_field(orch):
    orch.process_command('marque reunião amanhã às 15h')
    result = orch.process_command('Na verdade eu quero que você crie outro compromisso, não o mesmo')
    assert 'título' in result.message
    assert orch._pending_event_draft == {'duration_minutes': 60}
    orch.calendar_adapter.create_event.assert_not_called()
    orch.process_command('Dentista')
    orch.process_command('hoje')
    result = orch.process_command('11:00')
    assert result.status == 'awaiting_confirmation'
    orch.calendar_adapter.create_event.assert_not_called()
    orch.process_command('sim')
    assert orch.calendar_adapter.create_event.call_args.kwargs['summary'] == 'Dentista'
    orch.calendar_adapter.create_event.assert_called_once()


def test_reported_reminder_scenario_never_reuses_created_meeting(orch):
    orch.process_command('marque reunião amanhã às 15h')
    orch.process_command('sim')
    orch.calendar_adapter.create_event.reset_mock()
    result = orch.process_command('Adicione o lembrete no calendário.')
    assert 'novo compromisso' in result.message
    assert 'aviso' in result.message
    assert orch._pending_event_draft is None
    orch.process_command('Na verdade eu quero que você cria outro lembrete, não o mesmo')
    assert orch._pending_event_draft is None
    result = orch.process_command('um novo compromisso')
    assert 'título' in result.message
    assert orch._pending_event_draft == {'duration_minutes': 60}
    orch.calendar_adapter.create_event.assert_not_called()


@pytest.mark.parametrize('choice', ['aviso', 'adicionar um aviso a um evento existente'])
def test_existing_event_alert_is_reported_as_unimplemented(orch, choice):
    orch.process_command('crie um lembrete')
    result = orch.process_command(choice)
    assert 'não consigo configurar avisos' in result.message
    assert not orch._pending_reminder_choice
    assert orch._pending_event_draft is None
    orch.calendar_adapter.create_event.assert_not_called()


def test_clear_discards_reminder_choice_and_new_command_can_interrupt_it(orch):
    orch.process_command('crie um lembrete')
    assert orch._pending_reminder_choice
    orch.clear_session()
    assert not orch._pending_reminder_choice
    orch.process_command('crie um lembrete')
    result = orch.process_command('liste meus aliases')
    assert result.status == 'success'
    assert not orch._pending_reminder_choice
    orch.calendar_adapter.create_event.assert_not_called()
