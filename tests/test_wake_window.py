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
        if callable(kwargs.get('preroll')):   # a captura real lê o áudio inicial depois de abrir o microfone
            kwargs['preroll'] = kwargs['preroll']()
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


def test_stop_listening_answer_closes_the_microphone_of_the_wake_word(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._apply_command_result(OrchestrationResult(
        status='success', message='Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.', ui_action='wake_off'))
    assert 'stop' in FakeListener.last.calls and window._wake is None   # nada de microfone aberto até reiniciar
    assert window._speech_text == 'Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.'
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
    assert _validate_config({})['wake']['threshold'] == 0.7
    assert _validate_config({'wake': {'threshold': 0.6}})['wake']['threshold'] == 0.6
    for wrong in (2, 0.01, 'alto', True):
        assert _validate_config({'wake': {'threshold': wrong}})['wake']['threshold'] == 0.7
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


class CyclePipeline(FakePipeline):
    """Pipeline falso com o VoiceCycle de verdade: recusa gravar durante a fala, o aquecimento e o antieco."""

    def __init__(self):
        super().__init__()
        from therion.voice.cycle import VoiceCycle
        self.cycle = VoiceCycle()

    @property
    def ready_to_capture(self):
        return self.state == 'idle' and self.cycle.can_capture

    @ready_to_capture.setter
    def ready_to_capture(self, value):
        pass

    def start(self, **kwargs):
        if not self.ready_to_capture:
            return False
        return super().start(**kwargs)


def speaking_window(tmp_path, monkeypatch):
    """Resposta longa sendo falada; parar mata o processo de voz e reaquecer volta a 'warming', como a SpeechOutput real."""
    from therion.interface import desktop
    window, _ = make_window(tmp_path, monkeypatch)
    pipeline = CyclePipeline()
    window._voice_pipeline = pipeline
    speech = window._speech_output

    def set_state(state):
        speech.state = state
        window._on_speech_state(state)

    def stop():
        speech.is_ready = False
        set_state('idle')

    def warmup():
        set_state('warming')
        return True
    speech.stop.side_effect = stop
    speech.warmup.side_effect = warmup
    speech.spoken_text = 'Primeira parte da resposta. Segunda parte.'
    window._speech_text = 'Primeira parte da resposta. Segunda parte.'
    return window, pipeline, set_state


def test_the_name_during_a_long_answer_records_at_once(app, tmp_path, monkeypatch):
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    set_state('playing')
    window._on_wake(np.ones(800, np.float32), .8)
    assert window._conversation_mode
    assert pipeline.starts and len(pipeline.starts[-1]['preroll']) == 800
    close(app, window)


def test_the_name_during_a_spoken_reply_in_an_open_conversation_records_at_once(app, tmp_path, monkeypatch):
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)   # abre a conversa
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    set_state('playing')                            # a resposta longa começa a sair
    before = len(pipeline.starts)
    window._on_wake(np.ones(600, np.float32), .8)
    assert len(pipeline.starts) == before + 1 and len(pipeline.starts[-1]['preroll']) == 600
    close(app, window)


def test_the_text_actually_spoken_decides_if_the_name_is_an_echo(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._speech_output.state = 'playing'
    window._speech_output.spoken_text = 'Bom dia, aqui é o Therion com o panorama.'
    window._speech_text = 'Resposta anterior.'
    window._on_wake(np.ones(800, np.float32), .8)
    assert pipeline.starts == [] and 'ignorado: a fala tem o nome' in log_text(tmp_path)
    close(app, window)


def test_stop_listening_without_the_listener_says_it_is_not_on(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch, wake=False)
    window._apply_command_result(OrchestrationResult(
        status='success', message='Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.', ui_action='wake_off'))
    assert window._speech_text == 'A escuta pelo nome não está ligada agora.'
    close(app, window)


def test_stop_listening_ends_the_conversation_after_the_answer(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_voice_transcribed(pipeline.generation, 'Para de me ouvir.')
    window._apply_command_result(OrchestrationResult(
        status='success', message='Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.', ui_action='wake_off'))
    window._set_processing(False)
    assert window._conversation_mode   # a resposta ainda vai ser falada
    window._conversation_playback_finished()
    assert not window._conversation_mode
    close(app, window)


def test_the_listener_stops_on_about_to_quit_and_on_a_plain_close(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._app.aboutToQuit.connect.assert_any_call(window._stop_wake)
    window.close()                      # sem bandeja: fecha de verdade
    assert window._closing and 'stop' in FakeListener.last.calls
    close(app, window)


def test_an_out_of_range_threshold_is_reported_once(capsys, monkeypatch):
    from therion.config import local
    monkeypatch.setattr(local, '_wake_threshold_noticed', False, raising=False)
    local._validate_config({'wake': {'threshold': 2}})
    local._validate_config({'wake': {'threshold': 2}})
    out = capsys.readouterr().out
    assert out.count('wake.threshold') == 1
    local._validate_config({})
    assert 'wake.threshold' not in capsys.readouterr().out


def test_the_name_while_the_voice_rewarms_after_a_stop_records_at_once(app, tmp_path, monkeypatch):
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)   # abre a conversa
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    set_state('playing')
    window._stop_speech()        # botão parar: mata o processo e reaquece, sem nome pendente
    assert window._speech_output.state == 'warming'
    before = len(pipeline.starts)
    window._on_wake(np.ones(600, np.float32), .8)
    assert len(pipeline.starts) == before + 1 and len(pipeline.starts[-1]['preroll']) == 600
    close(app, window)


def test_a_request_after_the_name_is_never_taken_for_background_talk(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    pipeline.last_confidence = -0.7      # pouca confiança, sem o nome (o áudio inicial corta o nome)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma piada.')
    window._start_command_worker.assert_called_once_with('Conta uma piada.')
    close(app, window)


def test_an_answer_to_a_live_offer_is_never_taken_for_background_talk(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._orchestrator._focus_offer = (10 ** 9, 'pausa')
    pipeline.last_confidence = -0.7
    window._toggle_conversation()
    window._on_ai_warmed(window._ai_warm_token, True)
    window._try_conversation_listen()
    window._on_voice_transcribed(pipeline.generation, 'Pode.')
    window._start_command_worker.assert_called_once_with('Pode.')
    close(app, window)


def test_the_capture_reads_the_audio_after_the_name_once_the_microphone_is_open(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    listener.wake_mark = 42
    listener.since = lambda mark: np.full(2400, .1, np.float32) if mark == 42 else np.zeros(0, np.float32)
    listener.on_wake(np.ones(800, np.float32), .8)   # a marca vem junto com o disparo
    preroll = pipeline.starts[-1]['preroll']
    assert len(preroll) == 2400   # o que o detector ouviu até a captura abrir, não só a foto do disparo
    close(app, window)


def test_a_name_inside_an_open_conversation_also_reads_the_audio_once_the_microphone_opens(app, tmp_path, monkeypatch):
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    window._on_wake(np.ones(800, np.float32), .8)   # abre a conversa
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    set_state('playing')
    listener.wake_mark = 7                          # o detector marca o disparo e segue enchendo o buffer
    listener.since = lambda mark: np.full(2400, .1, np.float32) if mark == 7 else np.zeros(0, np.float32)
    listener.on_wake(np.ones(600, np.float32), .8)  # nome no meio da resposta, pela thread do detector
    listener.wake_mark = 99                         # um disparo seguinte não pode trocar a marca deste
    assert len(pipeline.starts[-1]['preroll']) == 2400
    close(app, window)


def test_a_discarded_name_turn_does_not_exempt_the_next_turn_from_the_background_filter(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_ai_warmed(window._ai_warm_token, True)
    token = ['outra']
    monkeypatch.setattr(type(window._orchestrator), 'confirmation_id', property(lambda self: token[0]))
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')   # descartado: a confirmação mudou
    token[0] = None
    pipeline.state = 'idle'
    window._try_conversation_listen()                                       # continuação, sem o nome
    pipeline.last_confidence = -0.7
    window._on_voice_transcribed(pipeline.generation, 'Conversa de fundo qualquer.')
    window._start_command_worker.assert_not_called()
    close(app, window)
