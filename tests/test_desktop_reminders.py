"""A janela toca os lembretes na hora e nunca corta a fala (porta única _speak_when_free)."""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from therion.core import voice_reminders
from therion.core.orchestrator import OrchestrationResult
from therion.core.voice_reminders import ReminderStore
from therion.interface import reminders
from tests.test_reminders import close, make_window

SIX_PM = datetime(2026, 11, 18, 18, 0)


@pytest.fixture
def shared(tmp_path, monkeypatch):
    store = ReminderStore(tmp_path / 'lembretes.json')
    monkeypatch.setattr(voice_reminders, 'store', lambda: store)
    return store


@pytest.fixture
def window(app, tmp_path, monkeypatch, shared):
    win = make_window(app, tmp_path, monkeypatch, True)
    win._speech_output = MagicMock()
    said = []
    monkeypatch.setattr(win, '_append', lambda sender, text: said.append(text))
    win.said = said
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    yield win
    win._speech_output = None
    win._processing = False
    win._game_forced = False
    close(app, win)


def spoken(win):
    return [call.args[0] for call in win._speech_output.speak.call_args_list]


def test_reminder_waits_for_speech_then_speaks(window, shared):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    window._speech_output.state = 'playing'          # outra fala tocando
    window._fire_reminders(SIX_PM)
    assert window.said == ['Lembrete: tirar a roupa da máquina.'] and spoken(window) == []
    window._speech_output.state = 'idle'
    window._drain_speech()
    assert spoken(window) == ['Lembrete: tirar a roupa da máquina.']
    window._drain_speech()
    assert len(spoken(window)) == 1                  # a fila esvaziou


def test_reminder_waits_for_listening_and_for_a_pending_request(window, shared):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    window._orbe_state = 'listening'
    window._fire_reminders(SIX_PM)
    assert spoken(window) == []
    window._orbe_state = 'idle'
    window._processing = True
    window._drain_speech()
    assert spoken(window) == []
    window._processing = False
    window._drain_speech()
    assert spoken(window) == ['Lembrete: tirar a roupa da máquina.']


def test_reminder_speaks_in_full_screen_and_game_mode(window, shared, monkeypatch):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: True)
    window._game_forced = True
    window._fire_reminders(SIX_PM)
    assert spoken(window) == ['Lembrete: tirar a roupa da máquina.']


def test_two_due_together_one_sentence(window, shared):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    shared.add('ligar para o Fulano', SIX_PM, None, SIX_PM - timedelta(hours=1))
    window._fire_reminders(SIX_PM + timedelta(seconds=30))
    assert spoken(window) == ['Dois lembretes: tirar a roupa da máquina; ligar para o Fulano.']
    assert shared.items() == []


def test_late_on_open(app, tmp_path, monkeypatch, shared):
    due = datetime.now().replace(second=0, microsecond=0) - timedelta(days=1)
    shared.add('tirar a roupa da máquina', due, None, due - timedelta(hours=1))
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    win = make_window(app, tmp_path, monkeypatch, False)
    try:
        said = []
        monkeypatch.setattr(win, '_append', lambda sender, text: said.append(text))
        win._speech_output = MagicMock()
        app.processEvents()                          # o singleShot(0) do __init__
        expected = f'Enquanto eu estava fechado, passou da hora de: tirar a roupa da máquina ({due:%H:%M}).'
        assert said[:1] == [expected] and spoken(win)[:1] == [expected]
    finally:
        win._speech_output = None
        close(app, win)


def test_shot_timer_armed_to_next_due(window, shared):
    assert not window._reminder_shot.isActive()
    shared.add('tirar a roupa da máquina', datetime.now() + timedelta(minutes=10), None, datetime.now())
    window._apply_command_result(OrchestrationResult(status='success', message='Combinado.', ui_action='reminders'))
    assert window._reminder_shot.isActive() and window._reminder_shot.isSingleShot()
    assert abs(window._reminder_shot.remainingTime() - 600000) < 3000


def test_timer_runs_without_any_ui_setting(app, tmp_path, monkeypatch, shared):
    win = make_window(app, tmp_path, monkeypatch, False)
    try:
        assert win._reminder_timer.isActive() and win._orchestrator.desktop_timers is True
    finally:
        close(app, win)


def test_tick_rereads_file_when_mtime_changes(window, shared, tmp_path):
    other = ReminderStore(tmp_path / 'lembretes.json')    # outro processo grava no mesmo arquivo
    other.add('tirar a roupa da máquina', datetime.now() + timedelta(hours=1), None, datetime.now())
    os.utime(tmp_path / 'lembretes.json', (1, 1))
    assert shared.items() == []
    window._poll_reminders()
    assert [item.text for item in shared.items()] == ['tirar a roupa da máquina']
    assert window._reminder_shot.isActive()


def test_broken_file_notice_said_once(app, tmp_path, monkeypatch):
    path = tmp_path / 'lembretes.json'
    path.write_text('{quebrado', encoding='utf-8')
    store = ReminderStore(path)
    monkeypatch.setattr(voice_reminders, 'store', lambda: store)
    win = make_window(app, tmp_path, monkeypatch, False)
    try:
        said = []
        monkeypatch.setattr(win, '_append', lambda sender, text: said.append(text))
        app.processEvents()
        win._fire_reminders()
        notices = [text for text in said if text.startswith('Não consegui ler seus lembretes antigos')]
        assert len(notices) == 1 and 'lembretes.json.bad-' in notices[0]
    finally:
        close(app, win)


def test_fire_opens_snooze_window(window, shared):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    window._fire_reminders(SIX_PM)
    snooze = window._orchestrator._reminder_snooze
    assert snooze[1] == 'tirar a roupa da máquina'


def test_event_warning_no_longer_cuts_speech(window):
    window._reminders = MagicMock()
    window._reminders.due.return_value = ['Em 15 minutos: Dentista, às 14:00.']
    window._speech_output.state = 'synthesizing'
    window._poll_reminders()
    assert window.said == ['Em 15 minutos: Dentista, às 14:00.'] and spoken(window) == []
    window._reminders.due.return_value = []
    window._speech_output.state = 'idle'
    window._poll_reminders()                          # o tique de 30 s solta a fila
    assert spoken(window) == ['Em 15 minutos: Dentista, às 14:00.']


def test_speech_turning_idle_drains_the_queue(window, shared):
    shared.add('tirar a roupa da máquina', SIX_PM, None, SIX_PM - timedelta(hours=1))
    window._speech_output.state = 'playing'
    window._fire_reminders(SIX_PM)
    window._speech_output.state = 'idle'
    window._on_speech_state('idle')
    assert spoken(window) == []                       # nunca dentro do próprio stop() de outra fala
    QApplication.processEvents()
    assert spoken(window) == ['Lembrete: tirar a roupa da máquina.']
