"""Pedidos compostos na UI real, sem calendário, áudio ou rede reais."""
import time
from datetime import datetime
from threading import Event
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from therion.calendar.models import CalendarEvent
from therion.core.orchestrator import Orchestrator
from therion.interface.desktop import MainWindow
from therion.voice.service import VoiceModelService


def wait_until(predicate, timeout=3):
    """Processa sinais Qt enquanto aguarda uma condição, sem bloquear a UI."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert predicate(), 'A condição esperada da UI não ocorreu.'


@pytest.fixture
def window(tmp_path):
    qt_app = QApplication.instance() or QApplication([])
    app = MagicMock()
    voice = MagicMock()
    voice.state = VoiceModelService.STATE_READY
    with patch.object(MainWindow, '_setup_tray'):
        instance = MainWindow(app, config={}, voice_service=voice)
    instance._orchestrator.close()
    vault = tmp_path / 'vault'
    root = vault / '10 - Projetos' / 'Therion'
    root.mkdir(parents=True)
    (root / 'Circuitos.md').write_text('# Circuitos\nNota fictícia para referência.', encoding='utf-8')
    calendar = MagicMock()
    calendar.list_events_for_day.return_value = []
    instance._orchestrator = Orchestrator(vault_root=str(vault), log_dir=str(tmp_path / 'logs'),
                                        calendar_adapter=calendar)
    instance._orchestrator._now_func = lambda: datetime(2026, 10, 9, 10,
                                                        tzinfo=ZoneInfo('America/Sao_Paulo'))
    instance._speech_output = MagicMock()
    instance._speech_output.is_ready = True
    instance._speech_output.state = 'idle'
    releases = []
    yield instance, calendar, voice, releases
    for release in releases:
        release.set()
    if instance._command_worker is not None:
        wait_until(lambda: instance._command_worker is None)
    instance._memory_timer.stop()
    instance._conversation_timer.stop()
    instance._orchestrator.close()
    instance.deleteLater()
    qt_app.processEvents()


def start_blocked(window):
    instance, calendar, _, releases = window
    entered, release = Event(), Event()
    releases.append(release)

    def query(_day):
        entered.set()
        assert release.wait(5), 'O teste não liberou a consulta fictícia.'
        tz = ZoneInfo('America/Sao_Paulo')
        return [CalendarEvent('fake', 'Consulta de resultado antigo',
                              datetime(2026, 10, 10, 9, tzinfo=tz),
                              datetime(2026, 10, 10, 10, tzinfo=tz), False)]

    calendar.list_events_for_day.side_effect = query
    instance._input.setPlainText('Veja minha agenda amanhã e adicione uma tarefa: organizar arquivos.')
    instance._send_command()
    wait_until(entered.is_set)
    assert instance._processing
    assert instance._command_worker.isRunning()
    return release


def test_progress_remains_on_ui_thread_without_automatic_speech(window, monkeypatch):
    instance, calendar, voice, _ = window
    release = start_blocked(window)
    widget_threads, applied_threads = [], []
    original_text = instance._workflow_label.setText
    original_apply = instance._apply_command_result

    def set_text(text):
        widget_threads.append(QThread.currentThread())
        original_text(text)

    def apply_result(result):
        applied_threads.append(QThread.currentThread())
        original_apply(result)

    monkeypatch.setattr(instance._workflow_label, 'setText', set_text)
    monkeypatch.setattr(instance, '_apply_command_result', apply_result)
    ui_ticks = []
    QTimer.singleShot(0, lambda: ui_ticks.append(QThread.currentThread()))
    instance._poll_memory_previews()
    wait_until(lambda: bool(ui_ticks))
    assert instance._workflow_label.text() == 'Etapa 1/2'
    assert not instance._workflow_cancel_button.isHidden()
    assert instance._workflow_cancel_button.isEnabled()
    assert instance._clear_button.isEnabled()
    assert not instance._send_button.isEnabled()
    assert instance._input.isEnabled()
    assert instance._command_worker.isRunning()
    instance._speech_output.speak.assert_not_called()
    release.set()
    wait_until(lambda: instance._command_worker is None)
    instance._poll_workflow_progress()
    main_thread = QApplication.instance().thread()
    assert widget_threads and all(thread == main_thread for thread in widget_threads)
    assert applied_threads == [main_thread]
    assert ui_ticks == [main_thread]
    assert instance._workflow_cancel_button.isHidden()
    assert [task.description for task in instance._orchestrator._session_tasks.list()] == ['organizar arquivos']
    assert 'Consulta de resultado antigo' in instance._history.toPlainText()
    instance._speech_output.speak.assert_not_called()
    voice.load.assert_not_called()
    calendar.create_event.assert_not_called()


def test_cancel_button_does_not_wait_for_current_step_or_execute_next_write(window):
    instance, calendar, _, _ = window
    release = start_blocked(window)
    instance._poll_workflow_progress()
    instance._workflow_cancel_button.click()
    assert instance._command_worker.isRunning()
    assert not release.is_set()
    assert instance._workflow_label.text() == 'Cancelando etapas restantes…'
    assert not instance._workflow_cancel_button.isEnabled()
    assert not instance._orchestrator._session_tasks.list()
    release.set()
    wait_until(lambda: instance._command_worker is None)
    assert instance._orchestrator.workflow_progress().state == 'cancelled'
    assert not instance._orchestrator._session_tasks.list()
    assert 'Cancelei as etapas restantes' in instance._history.toPlainText()
    calendar.create_event.assert_not_called()
    instance._speech_output.speak.assert_not_called()


def test_clear_during_step_discards_old_display_and_all_session_references(window):
    instance, calendar, _, _ = window
    orch = instance._orchestrator
    orch.process_command('Adicione uma tarefa: tarefa antiga.')
    orch.process_command('Lembre que prefiro respostas curtas.')
    orch.process_command('Busque no segundo cérebro Circuitos')
    assert orch._note_results is not None
    assert orch.knowledge.snapshot() and orch._session_tasks.list()
    old_session = orch.session_id
    release = start_blocked(window)
    instance._poll_workflow_progress()
    instance._clear_button.click()
    assert instance._workflow_clear_pending
    assert instance._processing and instance._command_worker.isRunning()
    assert instance._history.toPlainText() == ''
    assert not instance._clear_button.isEnabled()
    release.set()
    wait_until(lambda: instance._command_worker is None)
    assert not instance._workflow_clear_pending and not instance._processing
    assert orch.session_id != old_session
    assert orch.workflow_progress() is None
    assert not orch._session_tasks.list() and not orch.knowledge.snapshot()
    assert not orch.memory.turns
    assert orch._note_results is None and orch._last_tool_evidence is None
    assert orch.confirmation_id is None and instance._pending_plan is None
    assert instance._history.toPlainText() == ''
    assert instance._speech_text == ''
    instance._poll_memory_previews()
    assert instance._history.toPlainText() == ''
    instance._speech_output.speak.assert_not_called()
    calendar.create_event.assert_not_called()


def test_quit_cancels_remaining_steps_and_waits_for_worker_before_app_quit(window):
    instance, calendar, _, _ = window
    release = start_blocked(window)
    instance._quit_application()
    assert instance._quit_requested and not instance._closing
    assert instance._command_worker.isRunning()
    instance._app.quit.assert_not_called()
    assert not release.is_set()
    release.set()
    wait_until(lambda: instance._command_worker is None)
    assert instance._closing and not instance._processing
    instance._app.quit.assert_called_once_with()
    assert not instance._orchestrator._session_tasks.list()
    assert instance._orchestrator.workflow_progress() is None
    assert 'Consulta de resultado antigo' not in instance._history.toPlainText()
    instance._speech_output.speak.assert_not_called()
    calendar.create_event.assert_not_called()
