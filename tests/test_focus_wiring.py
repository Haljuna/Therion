"""Ligação do modo foco no orchestrator e no host do agente."""
import time
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.core import focus, voice_reminders
from therion.core.focus import FocusStore
from therion.core.orchestrator import Orchestrator
from therion.core.voice_reminders import ReminderStore


@pytest.fixture
def orch(tmp_path, monkeypatch):
    shared = FocusStore(tmp_path / 'foco.json')
    monkeypatch.setattr(focus, 'store', lambda: shared)
    monkeypatch.setattr(focus, '_config_minutes', lambda key, default, low, high: default)
    reminders = ReminderStore(tmp_path / 'lembretes.json')
    monkeypatch.setattr(voice_reminders, 'store', lambda: reminders)
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=MagicMock())
    instance._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    instance.desktop_timers = True
    instance.focus_store = shared
    return instance


def test_start_returns_focus_ui_action_with_payload(orch):
    result = orch.process_command('foco 30 minutos')
    assert result.status == 'success' and result.message.startswith('Foco de 30 minutos, até as ')
    assert result.ui_action == 'focus'
    assert result.ui_payload['phase'] == 'focus' and result.ui_payload['minutes'] == 30 and result.ui_payload['ended'] is False
    assert orch.focus_store.state().phase == 'focus'


def test_answers_without_change_do_not_ask_the_window_to_move(orch):
    orch.process_command('foco')
    result = orch.process_command('quanto falta do foco?')
    assert result.message.startswith('Faltam ') and result.ui_action is None and result.ui_payload is None


def test_terminal_answers_without_saving(orch):
    orch.desktop_timers = False
    result = orch.process_command('foco')
    assert result.message == 'Lembretes e foco funcionam com a janela do Therion aberta.'
    assert result.ui_action is None and orch.focus_store.state().phase == 'off'


def test_stop_goes_through_with_ended_payload(orch):
    orch.process_command('foco')
    result = orch.process_command('sai do foco')
    assert result.ui_action == 'focus' and result.ui_payload['phase'] == 'off' and result.ui_payload['ended'] is True


def test_focus_runs_before_pc_cleanup_and_spends_its_offer(orch, monkeypatch):
    ran = []
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: ran.append(1) or 'limpou')
    from therion.core import pc_cleanup
    pc_cleanup.offer(orch)
    assert orch.process_command('foco').ui_action == 'focus'
    assert orch.process_command('sim').message != 'limpou' and ran == []


def test_focus_offer_owns_yes_and_cleanup_offer_does_not_fire(orch, monkeypatch):
    ran = []
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: ran.append(1) or 'limpou')
    from therion.core import pc_cleanup
    pc_cleanup.offer(orch)
    focus.offer(orch, 'pause')
    result = orch.process_command('sim')
    assert result.ui_action == 'focus' and result.ui_payload['phase'] == 'pause' and ran == []


def test_focus_answer_clears_a_pending_reminder_question(orch):
    assert orch.process_command('me lembra de pagar o boleto').message == 'Quando eu te lembro?'
    assert orch._reminder_pending is not None
    orch.process_command('foco')
    assert orch._reminder_pending is None


def test_other_phrases_drop_the_focus_offer_and_reminders_still_work(orch):
    focus.offer(orch, 'pause')
    assert orch.process_command('me lembra às 18h de ligar').ui_action == 'reminders'
    assert orch._focus_offer is None
    assert orch.process_command('sim').ui_action is None


def test_cleanup_offer_still_works_when_no_focus_phrase(orch, monkeypatch):
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: 'limpou')
    from therion.core import pc_cleanup
    pc_cleanup.offer(orch)
    assert orch.process_command('sim').message == 'limpou'


@pytest.fixture
def agent_orch(tmp_path, monkeypatch):
    shared = FocusStore(tmp_path / 'foco.json')
    monkeypatch.setattr(focus, 'store', lambda: shared)
    instance = Orchestrator(simulate=True, vault_root=str(tmp_path), log_dir=str(tmp_path / 'logs'),
                            agent_config={'enabled': True, 'context_tokens': 5120, 'output_tokens': 4352},
                            agent_state_root=tmp_path / 'agent')
    yield instance
    instance.close()


@pytest.mark.parametrize('phrase', ['foco', 'vou focar 30 minutos', 'sai do foco'])
def test_agent_host_leaves_focus_phrases_to_the_local_route(agent_orch, phrase):
    assert agent_orch._dispatch_agent(phrase) is None


def test_agent_host_leaves_the_offer_answer_to_the_local_route(agent_orch):
    focus.offer(agent_orch, 'pause')
    assert agent_orch._dispatch_agent('sim') is None


def test_agent_host_would_take_the_phrase_without_the_focus_check(agent_orch, monkeypatch):
    monkeypatch.setattr(focus, 'wanted', lambda *args, **kwargs: False)
    assert agent_orch._dispatch_agent('vou focar 30 minutos') is not None
