"""Ligação dos lembretes por voz no orchestrator e no host do agente."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.core import voice_reminders
from therion.core.orchestrator import Orchestrator
from therion.core.voice_reminders import ReminderStore


@pytest.fixture
def orch(tmp_path, monkeypatch):
    shared = ReminderStore(tmp_path / 'lembretes.json')
    monkeypatch.setattr(voice_reminders, 'store', lambda: shared)
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=MagicMock())
    instance._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    instance.desktop_timers = True
    instance.store = shared
    return instance


def test_create_returns_reminders_ui_action(orch):
    result = orch.process_command('me lembra às 18h de ligar')
    assert result.status == 'success' and result.message.startswith('Combinado: ')
    assert result.ui_action == 'reminders'
    assert not hasattr(orch, '_reminders_changed')
    assert [r.text for r in orch.store.items()] == ['ligar']


def test_question_and_list_do_not_ask_the_window_to_reload(orch):
    assert orch.process_command('me lembra de pagar o boleto').ui_action is None
    assert orch.process_command('meus lembretes').ui_action is None


def test_terminal_answers_without_saving(orch):
    orch.desktop_timers = False
    result = orch.process_command('me lembra às 18h de ligar')
    assert result.message == 'Lembretes e foco funcionam com a janela do Therion aberta.'
    assert result.ui_action is None and orch.store.items() == []


def test_reminder_runs_before_pc_cleanup_and_spends_its_offer(orch, monkeypatch):
    ran = []
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: ran.append(1) or 'limpou')
    from therion.core import pc_cleanup
    pc_cleanup.offer(orch)
    assert orch.process_command('me lembra às 18h de ligar').ui_action == 'reminders'
    result = orch.process_command('sim')
    assert ran == [] and result.message != 'limpou'


def test_cleanup_offer_still_works_when_no_reminder_phrase(orch, monkeypatch):
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: 'limpou')
    from therion.core import pc_cleanup
    pc_cleanup.offer(orch)
    assert orch.process_command('sim').message == 'limpou'


@pytest.fixture
def agent_orch(tmp_path):
    instance = Orchestrator(simulate=True, vault_root=str(tmp_path), log_dir=str(tmp_path / 'logs'),
                            agent_config={'enabled': True, 'context_tokens': 5120, 'output_tokens': 4352},
                            agent_state_root=tmp_path / 'agent')
    yield instance
    instance.close()


@pytest.mark.parametrize('phrase', ['me lembra às 18h de ligar', 'meus lembretes', 'cancela todos os lembretes'])
def test_agent_host_leaves_reminder_phrases_to_the_local_route(agent_orch, phrase):
    assert agent_orch._dispatch_agent(phrase) is None


def test_agent_host_would_take_the_phrase_without_the_reminder_check(agent_orch, monkeypatch):
    monkeypatch.setattr(voice_reminders, 'reminder_request', lambda *args, **kwargs: False)
    assert agent_orch._dispatch_agent('me lembra às 18h de ligar') is not None
