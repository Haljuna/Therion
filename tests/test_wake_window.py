"""Janela principal acordando pelo nome: escuta, continuação de 8 s, volta a dormir e "para de me ouvir"."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from therion.config.local import _validate_config
from therion.core.orchestrator import OrchestrationResult


class FakeListener:
    def __init__(self, model_path, on_wake, **kwargs):
        self.model_path, self.on_wake, self.kwargs = model_path, on_wake, kwargs
        self.gate = SimpleNamespace(muted=False)
        self.calls = []
        FakeListener.last = self

    def start(self):
        self.calls.append('start')
        return True

    def stop(self):
        self.calls.append('stop')

    def pause(self):
        self.calls.append('pause')

    def resume(self):
        self.calls.append('resume')


class FakePipeline:
    STATE_IDLE = 'idle'

    def __init__(self):
        self.state, self.generation, self.starts, self.cancels = 'idle', 0, [], 0
        self.cycle = None
        self.ready_to_capture = True
        self.utterance_complete, self.endpoint_reason, self.has_speech = False, None, False
        self.input_stalled, self.last_confidence = False, None

    def start(self, **kwargs):
        self.starts.append(kwargs)
        self.generation += 1
        self.state = 'recording'
        return True

    def cancel(self):
        self.cancels += 1
        self.state = 'idle'

    def stop(self):
        self.state = 'transcribing'
        return True

    def set_fast_mode(self, enabled):
        pass

    def is_current_generation(self, generation):
        return generation == self.generation


def make_window(tmp_path, monkeypatch, *, wake=True, model=True, extra=None):
    from therion.interface import desktop
    FakeListener.last = None
    monkeypatch.setattr(desktop, 'WakeListener', FakeListener)
    for variable in ('APPDATA', 'LOCALAPPDATA'):
        folder = tmp_path / variable
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    if model:
        path = tmp_path / 'LOCALAPPDATA' / 'Therion' / 'wake' / 'therion.onnx'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'modelo falso')
    config = {'ai': {'enabled': False}, 'tts': {'enabled': False},
              'ui': {'wake_word': wake, 'mini_orb': False, 'pc_watch': False, 'conversation_log': True}}
    config.update(extra or {})
    service = MagicMock()
    service.state = desktop.VoiceModelService.STATE_READY
    pipeline = FakePipeline()
    with patch.object(desktop.MainWindow, '_setup_tray'):
        window = desktop.MainWindow(MagicMock(), config=config, voice_service=service, voice_pipeline=pipeline,
                                    config_writer=MagicMock(), log_dir=tmp_path / 'logs')
    window._speech_output = MagicMock()
    window._speech_output.state = 'idle'
    window._speech_output.is_ready = True
    window._speech_output.warmup.return_value = True
    window._orchestrator.ai_core = MagicMock()
    window._start_command_worker = MagicMock()
    window._play_wake_sound = MagicMock()
    return window, pipeline


def close(app, window):
    window._closing = True
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def log_text(tmp_path):
    notes = list((tmp_path / 'LOCALAPPDATA' / 'Therion' / 'conversas').glob('*.md'))
    return ''.join(note.read_text(encoding='utf-8') for note in notes)


def test_waking_in_idle_listens_with_the_audio_after_the_name(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    assert listener.calls == ['start'] and listener.model_path.endswith('therion.onnx')
    listener.on_wake(np.ones(800, np.float32), .83)   # da thread do detector chega pelo sinal Qt
    assert window._conversation_mode
    start = pipeline.starts[-1]
    assert start['automatic'] is True and len(start['preroll']) == 800 and start['no_speech_seconds'] == 5.0
    assert window._orbe_state == 'listening'
    window._play_wake_sound.assert_called_once()
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_called_once_with('Abre o Discord.')
    assert 'acordou pelo nome · pontuação 0.83 · virou pedido' in log_text(tmp_path)
    close(app, window)


def test_the_name_is_ignored_while_a_request_is_running(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._processing = True
    window._on_wake(np.ones(800, np.float32), .7)
    assert pipeline.starts == [] and not window._conversation_mode
    assert 'pontuação 0.70 · ignorado: pedido em andamento' in log_text(tmp_path)
    window._processing = False
    close(app, window)


def test_the_name_stops_the_speech_unless_the_speech_says_therion(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    speech = window._speech_output
    speech.state = 'speaking'
    window._speech_text = 'Eu sou o Therion, seu assistente.'
    window._on_wake(np.ones(800, np.float32), .9)
    speech.stop.assert_not_called()
    assert pipeline.starts == [] and not window._conversation_mode
    assert 'ignorado: a fala tem o nome' in log_text(tmp_path)
    window._speech_text = 'Abrindo o Discord.'
    speech.stop.side_effect = lambda: setattr(speech, 'state', 'idle')   # como a SpeechOutput real
    window._on_wake(np.ones(800, np.float32), .9)
    speech.stop.assert_called()
    assert pipeline.starts and pipeline.starts[-1]['no_speech_seconds'] == 5.0
    close(app, window)


def test_a_second_name_inside_an_open_turn_does_not_open_another(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_wake(np.ones(400, np.float32), .8)
    assert len(pipeline.starts) == 1
    assert 'ignorado: turno de voz aberto' in log_text(tmp_path)
    close(app, window)


def test_silence_after_the_name_goes_back_to_sleep(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    pipeline.utterance_complete, pipeline.endpoint_reason = True, 'no_speech'
    window._poll_conversation()
    assert not window._conversation_mode and pipeline.state == 'idle'
    assert window._orbe_state == 'idle'
    assert 'pontuação 0.80 · sem fala' in log_text(tmp_path)
    close(app, window)


def test_follow_up_listening_waits_eight_seconds(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_voice_transcribed(pipeline.generation, 'Que horas são?')
    window._set_processing(False)            # resposta pronta e falada; a captura seguinte é a continuação
    pipeline.state = 'idle'
    window._on_ai_warmed(window._ai_warm_token, True)
    window._try_conversation_listen()
    assert pipeline.starts[-1] == {'automatic': True, 'no_speech_seconds': 8.0}
    pipeline.utterance_complete, pipeline.endpoint_reason = True, 'no_speech'
    window._poll_conversation()
    assert not window._conversation_mode
    close(app, window)


def test_the_button_conversation_keeps_listening_without_a_deadline(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._toggle_conversation()
    window._on_ai_warmed(window._ai_warm_token, True)
    window._try_conversation_listen()
    assert pipeline.starts == [{'automatic': True}]
    close(app, window)


def test_stop_listening_answer_mutes_the_wake_word(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._apply_command_result(OrchestrationResult(
        status='success', message='Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.', ui_action='wake_off'))
    assert FakeListener.last.gate.muted is True
    close(app, window)


def test_recording_pauses_the_listener(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_voice_pipeline_state_changed('recording')
    window._on_voice_pipeline_state_changed('idle')
    assert FakeListener.last.calls[-2:] == ['pause', 'resume']
    close(app, window)


def test_a_microphone_problem_is_written_once_on_the_window(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    FakeListener.last.kwargs['on_problem']('microfone')
    assert 'Não consegui abrir o microfone para ouvir meu nome; tento de novo sozinho.' in window._history.toPlainText()
    close(app, window)


def test_wake_word_is_on_by_default_and_off_means_no_microphone(app, tmp_path, monkeypatch):
    assert _validate_config({})['ui']['wake_word'] is True
    assert _validate_config({'ui': {'wake_word': 'sim'}})['ui']['wake_word'] is True
    assert _validate_config({'wake': {'threshold': 0.7}})['wake']['threshold'] == 0.7
    for wrong in (2, 0.01, 'alto', True):
        assert _validate_config({'wake': {'threshold': wrong}})['wake']['threshold'] == 0.5
    window, pipeline = make_window(tmp_path, monkeypatch, wake=False)
    assert window._wake is None and FakeListener.last is None
    close(app, window)
    window, pipeline = make_window(tmp_path / 'sem-modelo', monkeypatch, model=False)
    assert window._wake is None
    close(app, window)
    window, pipeline = make_window(tmp_path / 'limiar', monkeypatch, extra={'wake': {'threshold': 0.7}})
    assert FakeListener.last.kwargs['threshold'] == 0.7
    close(app, window)


def test_quitting_stops_the_listener_first(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    order = []
    listener.stop = lambda: order.append('stop')
    window._app.quit.side_effect = lambda: order.append('quit')
    window._quit_application()
    assert order[0] == 'stop' and 'quit' in order
    close(app, window)


def test_closing_the_window_stops_the_listener(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path / 'fechar', monkeypatch)
    close(app, window)
    assert 'stop' in FakeListener.last.calls


def test_the_capture_starts_before_the_voice_warmup_can_block_it(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    order = []
    real_start = pipeline.start
    pipeline.start = lambda **kwargs: order.append('start') or real_start(**kwargs)
    window._speech_output.warmup.side_effect = lambda: order.append('warmup') or True
    window._on_wake(np.ones(800, np.float32), .8)
    assert order[:2] == ['start', 'warmup'] and window._conversation_mode
    assert window._conversation_capture_generation == pipeline.generation
    close(app, window)


def test_a_voice_that_cannot_warm_up_logs_the_name_as_ignored(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._speech_output.warmup.return_value = False
    window._on_wake(np.ones(800, np.float32), .8)
    assert not window._conversation_mode and pipeline.state == 'idle'
    assert 'ignorado: conversa por voz indisponível' in log_text(tmp_path)
    close(app, window)
