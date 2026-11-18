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


# --- perguntas e ofertas valem só para a próxima frase, mesmo que outra rota responda ----------------------
from therion.core import focus, pc_cleanup  # noqa: E402
from therion.core.orchestrator import OrchestrationResult  # noqa: E402


def _three(orch):
    for hour, text in ((15, 'ligar'), (16, 'regar as plantas'), (17, 'tirar a roupa da máquina')):
        orch.store.add(text, datetime(2026, 10, 9, hour), None, datetime(2026, 10, 9, 10))


def _other_route(orch, monkeypatch, taken, on_turn=None):
    """O agente responde as frases de `taken` antes da rota local (como memória, agenda, conversa)."""
    real = orch._dispatch_agent

    def dispatch(command, cancelled=None):
        if command in taken:
            if on_turn:
                on_turn()
            return OrchestrationResult(status='success', message='respondido por outra rota')
        return real(command, cancelled) if cancelled is not None else real(command)
    monkeypatch.setattr(orch, '_dispatch_agent', dispatch)


def test_cleanup_offer_takes_the_yes_from_a_pending_cancel_all(orch, monkeypatch):
    _three(orch)
    assert orch.process_command('cancela todos os lembretes').message == 'Cancelo os 3 lembretes?'
    monkeypatch.setattr('therion.core.pc_cleanup.run', lambda: 'limpou')
    pc_cleanup.offer(orch)   # o vigia do PC fala "quer que eu limpe?" entre as frases
    assert orch.process_command('sim').message == 'limpou'
    assert len(orch.store.items()) == 3


def test_cancel_all_question_dies_when_another_route_answers_the_next_phrase(orch, monkeypatch):
    _three(orch)
    _other_route(orch, monkeypatch, {'anota que o carro é prata'})
    assert orch.process_command('cancela todos os lembretes').message == 'Cancelo os 3 lembretes?'
    assert orch.process_command('anota que o carro é prata').message == 'respondido por outra rota'
    assert orch._reminder_pending is None
    orch.process_command('sim')
    assert len(orch.store.items()) == 3


def test_what_question_dies_when_another_route_answers_the_next_phrase(orch, monkeypatch):
    _other_route(orch, monkeypatch, {'anota que o carro é prata'})
    assert orch.process_command('me lembra em 10 minutos').message == 'Te lembro do quê?'
    orch.process_command('anota que o carro é prata')
    assert orch._reminder_pending is None
    assert voice_reminders.answer('qual a capital da França?', orch) is None
    assert orch.store.items() == []


def test_session_entry_also_spends_the_pending(orch, monkeypatch):
    _three(orch)
    _other_route(orch, monkeypatch, {'anota que o carro é prata'})
    assert orch.process_command('cancela todos os lembretes').message == 'Cancelo os 3 lembretes?'
    orch.process_session_command('anota que o carro é prata', orch._session_id, orch._confirmation_id)
    assert orch._reminder_pending is None


def test_offer_armed_between_turns_lives_until_the_next_phrase_only(orch, monkeypatch):
    _other_route(orch, monkeypatch, {'anota que o carro é prata'})
    focus.offer(orch, 'pause')   # a janela arma a oferta depois de falar o resumo do foco
    voice_reminders.snooze_window(orch, 'ligar')   # e abre o "adia" quando um lembrete toca
    orch.process_command('anota que o carro é prata')
    assert orch._focus_offer is None and orch._reminder_snooze is None


def test_cleanup_offer_armed_between_turns_is_spent_by_the_next_phrase(orch, monkeypatch):
    _other_route(orch, monkeypatch, {'anota que o carro é prata'})
    pc_cleanup.offer(orch)
    orch.process_command('anota que o carro é prata')
    assert orch._pc_cleanup_offer is None


def test_offer_armed_while_a_turn_runs_survives_that_turn(orch, monkeypatch):
    _other_route(orch, monkeypatch, {'anota que o carro é prata'}, on_turn=lambda: focus.offer(orch, 'pause'))
    focus.offer(orch, 'again')
    orch.process_command('anota que o carro é prata')
    assert orch._focus_offer is not None and orch._focus_offer[1] == 'pause'


def test_memory_command_spends_a_pending_cancel_all(agent_orch, tmp_path, monkeypatch):
    shared = ReminderStore(tmp_path / 'lembretes.json')
    monkeypatch.setattr(voice_reminders, 'store', lambda: shared)
    agent_orch.desktop_timers = True
    for hour, text in ((15, 'ligar'), (16, 'regar as plantas')):
        shared.add(text, datetime(2030, 10, 9, hour), None, datetime(2030, 10, 9, 10))
    assert agent_orch.process_command('cancela todos os lembretes').message == 'Cancelo os 2 lembretes?'
    agent_orch.process_command('guarde que prefiro estudar cerâmica nas manhãs')
    assert agent_orch._reminder_pending is None
    agent_orch.process_command('sim')
    assert len(shared.items()) == 2
