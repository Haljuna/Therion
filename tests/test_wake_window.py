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
    assert pipeline.starts and len(pipeline.starts[-1]['preroll']) == 0   # 23/11: nada da voz do Therion antes da parada
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
    assert len(pipeline.starts) == before + 1 and len(pipeline.starts[-1]['preroll']) == 0   # 23/11: começa na parada
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
    listener.mark = lambda: 7                       # 23/11: no barge-in a marca é a da parada da fala
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


def barge_in_window(tmp_path, monkeypatch):
    """Conversa aberta pelo nome, primeira resposta já dada e a segunda tocando; o detector marca até onde ouviu."""
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    window._on_wake(np.ones(800, np.float32), .8)   # abre a conversa
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    set_state('playing')
    listener.wake_mark = 7                          # fim do nome
    listener.mark = lambda: 50                      # onde o buffer estava quando a fala parou
    listener.since = lambda mark: (np.full(4000, .1, np.float32) if mark == 7
                                   else np.full(1600, .2, np.float32) if mark == 50 else np.zeros(0, np.float32))
    return window, pipeline, listener


def test_a_barge_in_takes_the_audio_from_when_the_speech_stopped(app, tmp_path, monkeypatch):
    # 23/11 ao vivo: a cauda da voz do Therion entrava no turno e a pausa depois do nome fechava a captura.
    window, pipeline, listener = barge_in_window(tmp_path, monkeypatch)
    listener.on_wake(np.ones(600, np.float32), .8)
    start = pipeline.starts[-1]
    assert len(start['preroll']) == 1600 and start['no_speech_seconds'] == 5.0
    close(app, window)


def test_a_barge_in_outside_the_conversation_also_starts_where_the_speech_stopped(app, tmp_path, monkeypatch):
    window, pipeline, set_state = speaking_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    set_state('playing')
    listener.wake_mark = 7
    listener.mark = lambda: 50
    listener.since = lambda mark: (np.full(4000, .1, np.float32) if mark == 7
                                   else np.full(1600, .2, np.float32) if mark == 50 else np.zeros(0, np.float32))
    listener.on_wake(np.ones(800, np.float32), .8)
    assert window._conversation_mode
    assert len(pipeline.starts[-1]['preroll']) == 1600 and pipeline.starts[-1]['no_speech_seconds'] == 5.0
    close(app, window)


def test_unclear_audio_after_the_name_is_logged_once_and_keeps_the_window_open(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .91)
    window._on_ai_warmed(window._ai_warm_token, True)
    window._conversation_heard_at = time.monotonic() - 30   # a conversa abriu há tempo
    before = len(pipeline.starts)
    pipeline.state = 'transcribing'
    window._on_voice_transcription_failed(pipeline.generation, 'voice_unclear_audio')
    assert len(pipeline.starts) == before   # a transcrição ainda não liberou o microfone
    pipeline.state = 'idle'
    window._try_conversation_listen()
    assert len(pipeline.starts) == before + 1
    text = log_text(tmp_path)
    assert '0.91 · áudio confuso' in text and 'turno descartado' not in text
    pipeline.speech_started_after, pipeline.last_confidence = 1.0, -0.2   # repete logo depois do "Não entendi"
    window._on_voice_transcribed(pipeline.generation, 'Que horas são?')
    window._start_command_worker.assert_called_once_with('Que horas são?')
    close(app, window)


def test_a_barge_in_counts_as_talking_to_him_for_the_eight_second_window(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    speech = window._speech_output
    window._on_wake(np.ones(800, np.float32), .8)   # abre a conversa
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    speech.state, speech.spoken_text = 'playing', 'Era uma vez.'
    speech.stop.side_effect = lambda: setattr(speech, 'state', 'idle')   # parar não emite "completed"
    window._conversation_heard_at = time.monotonic() - 30
    window._start_command_worker.reset_mock()
    window._on_wake(np.ones(600, np.float32), .8)   # nome no meio da resposta longa
    pipeline.utterance_complete, pipeline.endpoint_reason, pipeline.has_speech = True, 'silence', False
    window._poll_conversation()                     # o turno do nome não teve fala: abre a continuação
    pipeline.utterance_complete = False
    pipeline.speech_started_after, pipeline.last_confidence = 1.0, -0.2
    window._on_voice_transcribed(pipeline.generation, 'Que horas são?')
    window._start_command_worker.assert_called_once_with('Que horas são?')
    close(app, window)


def test_ending_the_conversation_logs_why(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .94)
    window._end_conversation('janela escondida')
    assert '0.94 · ignorado: conversa encerrada (janela escondida)' in log_text(tmp_path)
    window._on_wake(np.ones(800, np.float32), .62)
    window._toggle_conversation()                   # botão Encerrar
    assert '0.62 · ignorado: conversa encerrada (botão)' in log_text(tmp_path)
    window._on_wake(np.ones(800, np.float32), .85)
    window.show()
    window.hide()
    assert '0.85 · ignorado: conversa encerrada (janela escondida)' in log_text(tmp_path)
    close(app, window)


def test_stop_listening_ends_the_conversation_even_when_the_answer_is_cut(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_ai_warmed(window._ai_warm_token, True)
    window._on_voice_transcribed(pipeline.generation, 'Para de me ouvir.')
    window._apply_command_result(OrchestrationResult(
        status='success', message='Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.', ui_action='wake_off'))
    window._set_processing(False)
    pipeline.state = 'idle'
    before = len(pipeline.starts)
    window._try_conversation_listen()   # a fala parou sem "completed" (botão parar): não abre outra escuta
    assert not window._conversation_mode and len(pipeline.starts) == before
    assert window._speech_text == 'Tudo bem, parei de ouvir pelo nome até o senhor me abrir de novo.'
    close(app, window)


def test_clicking_the_name_control_turns_listening_off_and_on_without_doubling_triggers(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    assert window._wake_state() == 'on'
    window._toggle_wake()
    assert window._wake is None and window._wake_state() == 'off'
    window._toggle_wake()
    assert window._wake_state() == 'on' and FakeListener.last.calls == ['start']   # ouvinte novo
    close(app, window)


def test_re_enabling_connects_the_signals_and_the_sound_only_once(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    sound = window._wake_sound
    window._toggle_wake()
    window._toggle_wake()
    assert window._wake_sound is sound
    calls = []
    monkeypatch.setattr(type(window), '_wake_ignored', lambda self: calls.append(1) or 'teste')
    FakeListener.last.on_wake(np.ones(800, np.float32), .9)
    assert calls == [1]   # o _on_wake real foi ligado uma vez só
    close(app, window)


def test_stop_listening_by_voice_turns_the_control_off_and_the_click_brings_it_back(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._apply_command_result(OrchestrationResult(status='success', message='Tudo bem.', ui_action='wake_off'))
    assert window._wake_state() == 'off'
    window._toggle_wake()
    assert window._wake_state() == 'on'
    window._apply_command_result(OrchestrationResult(status='success', message='Tudo bem.', ui_action='wake_off'))
    assert window._wake_state() == 'off'   # o comando de voz continua valendo depois de religar
    close(app, window)


def test_a_microphone_problem_turns_the_control_amber_and_a_click_retries(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    first = FakeListener.last
    first.kwargs['on_problem']('microfone')
    assert window._wake_state() == 'problem'
    window._toggle_wake()
    assert window._wake_state() == 'on' and FakeListener.last is not first and 'stop' in first.calls
    first_again = FakeListener.last
    first_again.kwargs['on_problem']('microfone')
    assert window._wake_state() == 'problem'
    window._on_wake(np.ones(800, np.float32), .9)   # um disparo real prova que o microfone voltou
    assert window._wake_state() == 'on'
    close(app, window)


def test_the_name_control_is_hidden_without_the_model_or_with_wake_word_off(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch, wake=False)
    assert window._wake_state() is None
    close(app, window)
    window, pipeline = make_window(tmp_path / 'sem-modelo', monkeypatch, model=False)
    assert window._wake_state() is None
    close(app, window)


def test_the_name_control_is_never_written_to_the_config(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._toggle_wake()
    window._toggle_wake()
    assert window._config['ui']['wake_word'] is True
    close(app, window)


def test_a_failed_re_enable_says_so_and_stays_off(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._toggle_wake()
    monkeypatch.setattr(FakeListener, 'start', lambda self: False)
    window._toggle_wake()
    assert window._wake_state() == 'off'
    assert 'Não consegui religar a escuta pelo nome.' in window._history.toPlainText()
    close(app, window)


def test_the_tray_action_follows_the_state(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QAction
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._wake_action = QAction('Ouvir meu nome', window)
    window._wake_action.setCheckable(True)
    window._wake_action.triggered.connect(window._on_wake_menu)   # como em _setup_tray
    window._wake_state_changed()
    assert window._wake_action.isChecked()
    window._wake_action.trigger()   # desmarcar desliga
    assert window._wake_state() == 'off' and not window._wake_action.isChecked()
    window._wake_action.trigger()
    assert window._wake_state() == 'on' and window._wake_action.isChecked()
    close(app, window)


def open_by_button(window, pipeline):
    window._toggle_conversation()
    window._on_ai_warmed(window._ai_warm_token, True)
    window._try_conversation_listen()


def test_unclear_background_audio_late_in_the_conversation_stays_silent(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    open_by_button(window, pipeline)
    window._conversation_heard_at = time.monotonic() - 30   # vídeo em inglês ao fundo, bem depois da resposta
    pipeline.speech_started_after, pipeline.state = 1.0, 'idle'
    before = len(pipeline.starts)
    window._on_voice_transcription_failed(pipeline.generation, 'voice_unclear_audio')
    assert 'Não entendi o áudio' not in window._history.toPlainText()
    assert len(pipeline.starts) == before + 1   # volta a ouvir em silêncio
    pipeline.last_confidence = -0.2
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_not_called()   # a janela não reabriu
    close(app, window)


def test_unclear_audio_inside_the_window_still_asks_to_repeat(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    open_by_button(window, pipeline)
    pipeline.speech_started_after = 1.0
    window._on_voice_transcription_failed(pipeline.generation, 'voice_unclear_audio')
    assert 'Não entendi o áudio' in window._history.toPlainText()
    close(app, window)


def test_a_slow_preparation_does_not_drop_the_first_request(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._toggle_conversation()
    window._conversation_heard_at = time.monotonic() - 12   # IA fria: 12 s até "Ouvindo…"
    window._on_ai_warmed(window._ai_warm_token, True)
    window._try_conversation_listen()
    pipeline.speech_started_after, pipeline.last_confidence = 1.0, -0.2
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_called_once_with('Abre o Discord.')
    close(app, window)


def test_the_stop_button_counts_as_talking_to_him_for_the_window(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    open_by_button(window, pipeline)
    window._on_voice_transcribed(pipeline.generation, 'Conta uma história.')
    window._set_processing(False)
    pipeline.state = 'idle'
    window._conversation_heard_at = time.monotonic() - 30
    window._start_command_worker.reset_mock()
    window._stop_speech()   # botão Parar no meio da resposta
    window._try_conversation_listen()
    pipeline.speech_started_after, pipeline.last_confidence = 1.0, -0.2
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_called_once_with('Abre o Discord.')
    close(app, window)


def test_a_question_in_the_reply_exempts_only_for_thirty_seconds(app, tmp_path, monkeypatch):
    import time
    window, pipeline = make_window(tmp_path, monkeypatch)
    open_by_button(window, pipeline)
    window._last_conversation_spoken = 'Não entendi bem. Pode repetir?'
    window._conversation_heard_at = window._last_conversation_spoken_at = time.monotonic() - 40
    pipeline.state = 'idle'
    pipeline.speech_started_after, pipeline.last_confidence = 1.0, -0.2
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_not_called()
    pipeline.state = 'idle'
    window._try_conversation_listen()
    window._conversation_heard_at, window._last_conversation_spoken_at = time.monotonic() - 30, time.monotonic() - 10
    window._on_voice_transcribed(pipeline.generation, 'Abre o Discord.')
    window._start_command_worker.assert_called_once_with('Abre o Discord.')
    close(app, window)


def test_a_microphone_problem_after_turning_listening_off_is_not_shown(app, tmp_path, monkeypatch):
    window, pipeline = make_window(tmp_path, monkeypatch)
    listener = FakeListener.last
    window._toggle_wake()
    listener.kwargs['on_problem']('microfone')   # já estava na fila
    assert 'tento de novo sozinho' not in window._history.toPlainText() and window._wake_state() == 'off'
    close(app, window)


def test_game_mode_ends_the_conversation_after_the_answer_but_keeps_the_name(app, tmp_path, monkeypatch):
    # 24/11: ao entrar no modo jogo o microfone da conversa fecha; o nome e o clique continuam chamando.
    window, pipeline = make_window(tmp_path, monkeypatch)
    window._on_wake(np.ones(800, np.float32), .8)
    window._on_voice_transcribed(pipeline.generation, 'Abre o modo de jogo.')
    window._apply_command_result(OrchestrationResult(status='success', message='Modo jogo ligado.', ui_action='game_mode', ui_payload={'on': True}))
    window._set_processing(False)
    assert window._conversation_mode   # a resposta ainda vai ser falada
    window._conversation_playback_finished()
    assert not window._conversation_mode and window._wake_state() == 'on'
    close(app, window)
