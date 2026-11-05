"""Reuso do preload sem transferir autorização entre sessões de voz."""
from collections import deque
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from therion.core.orchestrator import OrchestrationResult
from therion.interface.desktop import MainWindow
from therion.voice.capture import AudioCaptureService
from therion.voice.pipeline import VoicePipeline
from therion.voice.service import VoiceModelService
from tests.test_voice_capture import FakeInputStream


class Transcription(QObject):
    transcribed = Signal(int, str)
    transcription_failed = Signal(int, str)

    def transcribe_async(self, audio, generation):
        raise AssertionError('Preload não deve transcrever ou executar mensagens.')


class ControlledCore:
    def __init__(self):
        self.calls = 0
        self.finished = 0
        self.jobs = deque()
        self.events = []
        self.lock = threading.Lock()

    def enqueue(self, *, fails=False):
        event = threading.Event()
        self.events.append(event)
        self.jobs.append((event, fails))
        return event

    def warmup(self):
        with self.lock:
            self.calls += 1
            event, fails = self.jobs.popleft()
        try:
            if not event.wait(5):
                raise AssertionError('O teste não liberou o preload simulado.')
            if fails:
                raise RuntimeError('IA simulada indisponível')
        finally:
            self.finished += 1


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    assert predicate()


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    core = ControlledCore()
    orchestrator = MagicMock(ai_core=core, confirmation_id=None)
    orchestrator.memory_notifications.return_value = ''
    orchestrator.workflow_progress.return_value = None
    model = MagicMock(state=VoiceModelService.STATE_READY)
    capture = AudioCaptureService(stream_factory=FakeInputStream)
    pipeline = VoicePipeline(capture, Transcription())
    with patch('therion.interface.desktop.Orchestrator', return_value=orchestrator), \
            patch.object(MainWindow, '_setup_tray'):
        instance = MainWindow(app, voice_service=model, voice_pipeline=pipeline)
    instance._speech_output = MagicMock(is_ready=True, state='idle')
    instance._speech_output.warmup.return_value = True
    instance._start_command_worker = MagicMock()
    instance._start_confirmation_worker = MagicMock()
    now = [100.0]
    instance._ai_warm_clock = lambda: now[0]
    instance._test_now = now
    instance._test_core = core
    instance._test_cores = [core]
    yield instance
    instance._end_conversation()
    instance._closing = True
    for item in instance._test_cores:
        for event in item.events:
            event.set()
    wait_for(lambda: all(item.finished == item.calls for item in instance._test_cores))
    QTest.qWait(10)
    instance._memory_timer.stop()
    instance.deleteLater()
    app.processEvents()


def prepare_startup(window):
    event = window._test_core.enqueue()
    window._prepare_voice_background()
    wait_for(lambda: window._test_core.calls == 1)
    return event


def complete_startup(window):
    event = prepare_startup(window)
    event.set()
    wait_for(lambda: not window._ai_preparing)
    assert window._ai_resource_recent()
    assert not window._voice_pipeline._capture.is_recording


def test_click_during_startup_adopts_one_inflight_preload(window):
    event = prepare_startup(window)
    window._toggle_conversation()
    assert window._test_core.calls == 1
    assert not window._voice_pipeline._capture.is_recording
    event.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)
    assert window._test_core.calls == 1
    assert window._ai_warm_token == 1
    window._start_command_worker.assert_not_called()
    window._start_confirmation_worker.assert_not_called()


def test_completed_startup_is_ready_when_conversation_opens(window):
    complete_startup(window)
    window._toggle_conversation()
    assert window._voice_pipeline._capture.is_recording
    assert 'IA: pronta (0.0s)' in window._preparation_label.text()
    assert window._test_core.calls == 1


def test_recent_resource_can_be_reused_only_after_new_explicit_start(window):
    complete_startup(window)
    window._toggle_conversation()
    old_capture = window._voice_pipeline.generation
    window._end_conversation()
    assert not window._ai_warm_ready
    assert not window._voice_pipeline._capture.is_recording
    window._on_ai_warmed(1, True)
    assert not window._voice_pipeline._capture.is_recording
    window._orchestrator.confirmation_id = 'new-proposal'
    window._toggle_conversation()
    assert window._voice_pipeline._capture.is_recording
    assert window._voice_pipeline.generation != old_capture
    assert window._conversation_confirmation_token == 'new-proposal'
    assert window._test_core.calls == 1


def test_restart_with_fast_speech_warmup_rearms_after_echo_pause(window):
    complete_startup(window)
    window._toggle_conversation()
    assert window._voice_pipeline._capture.is_recording
    window._end_conversation()
    window._speech_output.is_ready = False
    window._toggle_conversation()
    window._on_speech_state('warming')
    window._speech_output.is_ready = True
    window._speech_output.state = 'idle'
    window._on_speech_state('idle')
    window._on_speech_warmed()
    assert not window._voice_pipeline._capture.is_recording
    wait_for(lambda: window._voice_pipeline._capture.is_recording)
    assert window._conversation_label.text() == 'Ouvindo…'
    assert window._test_core.calls == 1


def test_end_during_echo_pause_never_reopens_microphone(window):
    complete_startup(window)
    window._speech_output.is_ready = False
    window._toggle_conversation()
    window._on_speech_state('warming')
    window._speech_output.is_ready = True
    window._speech_output.state = 'idle'
    window._on_speech_state('idle')
    window._on_speech_warmed()
    window._end_conversation()
    QTest.qWait(800)
    window._poll_conversation()
    assert not window._voice_pipeline._capture.is_recording
    window._start_command_worker.assert_not_called()


def test_expired_resource_requires_a_new_preload(window):
    complete_startup(window)
    window._test_now[0] += window._AI_READY_TTL_SECONDS
    event = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 2)
    assert not window._voice_pipeline._capture.is_recording
    assert 'IA: preparando' in window._preparation_label.text()
    event.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)


@pytest.mark.parametrize('stop', ['_end_conversation', '_clear_conversation'])
def test_inflight_result_after_stop_cannot_reopen_or_be_cached(window, stop):
    event = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 1)
    getattr(window, stop)()
    event.set()
    wait_for(lambda: not window._ai_preparing)
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording
    assert not window._ai_resource_recent()
    assert window._test_core.calls == 1
    window._start_command_worker.assert_not_called()


def test_restarted_session_waits_for_fresh_probe_after_old_work_finishes(window):
    old = window._test_core.enqueue()
    fresh = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 1)
    window._end_conversation()
    window._toggle_conversation()
    assert window._test_core.calls == 1
    old.set()
    wait_for(lambda: window._test_core.calls == 2)
    assert not window._voice_pipeline._capture.is_recording
    fresh.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)


def test_clear_before_startup_finishes_invalidates_that_resource(window):
    event = prepare_startup(window)
    window._clear_conversation()
    event.set()
    wait_for(lambda: not window._ai_preparing)
    assert not window._ai_resource_recent()
    assert not window._voice_pipeline._capture.is_recording
    window._orchestrator.clear_session.assert_called_once()


def test_clear_discards_completed_resource_readiness(window):
    complete_startup(window)
    window._clear_conversation()
    assert not window._ai_resource_recent()
    event = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 2)
    assert not window._voice_pipeline._capture.is_recording
    event.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)


def test_timeout_invalidates_late_preload_and_keeps_text_available(window):
    now = [0.0]
    window._preparation.clock = lambda: now[0]
    old = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 1)
    now[0] = 91.0
    window._poll_conversation()
    assert not window._conversation_mode
    assert window._input.isEnabled()
    assert window._send_button.isEnabled()
    assert 'tempo excedido' in window._preparation_label.text()
    old.set()
    wait_for(lambda: not window._ai_preparing)
    assert not window._ai_resource_recent()
    assert not window._voice_pipeline._capture.is_recording
    retry = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 2)
    retry.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)


def test_failed_preload_can_retry_without_executing_commands(window):
    failure = window._test_core.enqueue(fails=True)
    window._toggle_conversation()
    failure.set()
    wait_for(lambda: not window._conversation_mode)
    assert not window._ai_resource_recent()
    assert 'IA: falhou' in window._preparation_label.text()
    retry = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 2)
    retry.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)
    window._start_command_worker.assert_not_called()
    window._start_confirmation_worker.assert_not_called()


@pytest.mark.parametrize('status', ['ai_unavailable', 'ai_timeout', 'ai_invalid_response'])
def test_actual_ai_failure_invalidates_recent_resource(window, status):
    complete_startup(window)
    window._toggle_conversation()
    window._apply_command_result(OrchestrationResult(status=status, message='Falha simulada'))
    assert not window._conversation_mode
    assert not window._ai_resource_recent()
    assert window._input.isEnabled()


def test_changed_core_never_reuses_old_readiness(window):
    complete_startup(window)
    replacement = ControlledCore()
    window._test_cores.append(replacement)
    event = replacement.enqueue()
    window._orchestrator.ai_core = replacement
    window._toggle_conversation()
    wait_for(lambda: replacement.calls == 1)
    assert not window._voice_pipeline._capture.is_recording
    event.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)
    assert window._ai_resource_core is replacement


def test_changed_core_does_not_adopt_an_inflight_preload(window):
    old = prepare_startup(window)
    replacement = ControlledCore()
    window._test_cores.append(replacement)
    fresh = replacement.enqueue()
    window._orchestrator.ai_core = replacement
    window._toggle_conversation()
    assert replacement.calls == 0
    old.set()
    wait_for(lambda: replacement.calls == 1)
    assert not window._voice_pipeline._capture.is_recording
    assert not window._ai_resource_recent()
    fresh.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)
    assert window._ai_resource_core is replacement
    assert window._test_core.calls == 1


def test_old_token_does_not_complete_a_new_preload(window):
    complete_startup(window)
    window._test_now[0] += window._AI_READY_TTL_SECONDS
    event = window._test_core.enqueue()
    window._toggle_conversation()
    wait_for(lambda: window._test_core.calls == 2)
    window._on_ai_warmed(1, True)
    assert window._ai_preparing
    assert not window._voice_pipeline._capture.is_recording
    event.set()
    wait_for(lambda: window._voice_pipeline._capture.is_recording)


def test_closing_window_discards_late_preload(window):
    event = prepare_startup(window)
    window._closing = True
    event.set()
    wait_for(lambda: not window._ai_preparing)
    assert window._ai_resource_ready_at is None
    assert not window._voice_pipeline._capture.is_recording
