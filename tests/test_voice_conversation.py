from unittest.mock import MagicMock, patch
import time
import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal, Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from therion.interface.desktop import MainWindow, _CommandWorker, _ConfirmationWorker
from therion.voice.capture import AudioCaptureService
from therion.voice.pipeline import VoicePipeline
from therion.voice.service import VoiceModelService
from therion.core.orchestrator import OrchestrationResult
from tests.test_voice_capture import FakeInputStream


class Transcription(QObject):
    transcribed = Signal(int, str)
    transcription_failed = Signal(int, str)
    def transcribe_async(self, audio, generation):
        self.audio, self.generation = audio, generation
        return True


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    # Este teste cobre o fluxo Qt, não a classificação acústica. Seus blocos DC
    # são marcadores sintéticos; o VAD real é validado separadamente com áudio.
    capture = AudioCaptureService(stream_factory=FakeInputStream,
        activity_factory=lambda: lambda samples: bool(np.max(np.abs(samples)) > .004))
    transcription = Transcription()
    pipeline = VoicePipeline(capture, transcription)
    model = MagicMock()
    model.state = VoiceModelService.STATE_READY
    with patch.object(MainWindow, '_setup_tray'):
        instance = MainWindow(MagicMock(), voice_service=model, voice_pipeline=pipeline)
    pipeline.transcribed.connect(instance._on_voice_transcribed)
    pipeline.transcription_failed.connect(instance._on_voice_transcription_failed)
    instance._orchestrator.ai_core = MagicMock()
    instance._speech_output = MagicMock()
    instance._speech_output.is_ready = True
    instance._speech_output.state = 'idle'
    instance._speech_output.warmup.return_value = True
    instance._start_command_worker = MagicMock()
    yield instance
    instance._end_conversation()
    instance.deleteLater()
    app.processEvents()


def activate(window):
    window._toggle_conversation()
    window._on_ai_warmed(window._conversation_generation, True)


def test_internal_windows_preserve_active_voice_conversation_and_typed_draft(window):
    activate(window)
    generation=window._conversation_generation
    window._input.setPlainText('Rascunho durante a conversa.')
    window._select_interface('constellation',persist=False)
    dashboard=window._dashboard
    dashboard.navigate(2); dashboard.navigate(3)
    dashboard.workspace.panels['tasks'].dismiss(); dashboard.navigate(0)
    deadline=time.monotonic()+3
    while dashboard.workers and time.monotonic()<deadline: QTest.qWait(10)
    assert not dashboard.workers
    assert window._conversation_mode and window._conversation_generation==generation
    assert window._orchestrator.voice_conversation
    assert window._input.toPlainText()=='Rascunho durante a conversa.'
    dashboard.cancel()


def test_task_stop_ends_voice_and_ignores_late_reply(window):
    activate(window)
    worker=_CommandWorker(window._orchestrator,'Converse sobre uma cidade fictícia.')
    worker.conversation_generation=window._conversation_generation
    worker.result=OrchestrationResult(status='success',message='Resposta tardia que não deve ser falada.')
    window._command_worker=worker
    window._set_processing(True)
    window._workflow_cancel_button.setEnabled(True)
    window._workflow_cancel_button.click()
    assert worker.cancelled.is_set() and not window._conversation_mode
    assert window._workflow_label.text()=='Cancelando etapas restantes…'
    window._finish_command(worker)
    QTest.qWait(250)
    window._speech_output.speak.assert_not_called()
    assert window._voice_pipeline.state==VoicePipeline.STATE_IDLE
    assert not window._conversation_mode and not window._processing


@pytest.mark.parametrize('worker_type', [_CommandWorker, _ConfirmationWorker])
def test_ending_voice_cancels_queued_worker_and_discards_its_result(window, worker_type):
    activate(window)
    if worker_type is _CommandWorker:
        worker = worker_type(window._orchestrator, 'olá')
        window._command_worker = worker
        finish = window._finish_command
    else:
        plan = window._orchestrator.process_command('abra o Obsidian').plan
        worker = worker_type(window._orchestrator, plan, True)
        window._confirmation_worker = worker
        finish = window._finish_confirmation
    worker.conversation_generation = window._conversation_generation
    window._end_conversation()
    assert worker.cancelled.is_set()
    worker.run()
    assert worker.result.status == 'cancelled'
    finish(worker)
    assert 'Nenhuma nova ação' not in window._history.toPlainText()
    window._speech_output.speak.assert_not_called()


@pytest.mark.parametrize('worker_type', [_CommandWorker, _ConfirmationWorker])
@pytest.mark.parametrize('pending', [False, True])
def test_discarded_voice_result_clears_thinking_only_after_worker_finishes(window, worker_type, pending):
    activate(window)
    plan = MagicMock()
    if worker_type is _CommandWorker:
        worker = worker_type(window._orchestrator, 'consulta fictícia')
        window._command_worker = worker
        finish = window._finish_command
    else:
        worker = worker_type(window._orchestrator, plan, True)
        window._confirmation_worker = worker
        finish = window._finish_confirmation
    worker.conversation_generation = window._conversation_generation
    window._pending_plan = plan if pending else None
    window._set_processing(True)
    window._update_orbe('thinking')
    previous_history = window._history.toPlainText()
    window._end_conversation()
    assert window._processing and not window._send_button.isEnabled()
    assert window._orbe_label.text() == 'Pensando...'
    worker.run()
    finish(worker)
    assert not window._processing and window._send_button.isEnabled()
    assert window._orbe_label.text() == ('Aguardando confirmação' if pending else 'Pronto')
    expected_plan = plan if pending else None
    assert window._pending_plan is expected_plan
    assert window._history.toPlainText() == previous_history
    window._speech_output.speak.assert_not_called()


def test_old_finished_callback_does_not_consume_new_worker(window):
    old = _CommandWorker(window._orchestrator, 'olá')
    new = _CommandWorker(window._orchestrator, 'liste meus aliases')
    window._command_worker = new
    window._set_processing(True)
    window._finish_command(old)
    assert window._command_worker is new
    assert window._processing


def test_real_worker_completion_applies_result_on_ui_thread(window):
    applied_threads = []
    window._apply_command_result = lambda result: applied_threads.append(QThread.currentThread())
    window._set_processing(True)
    MainWindow._start_command_worker(window, 'liste meus aliases')
    deadline = time.monotonic() + 5
    while window._command_worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert window._command_worker is None
    assert applied_threads == [QApplication.instance().thread()]


def test_cleared_session_worker_result_is_not_displayed(window):
    worker = _CommandWorker(window._orchestrator, 'olá')
    worker.result = OrchestrationResult(status='success', message='Resultado de sessão antiga')
    window._command_worker = worker
    window._orchestrator.clear_session()
    window._finish_command(worker)
    assert 'Resultado de sessão antiga' not in window._history.toPlainText()
    assert window._command_worker is None


def test_clear_discards_pending_plan_panel_and_duplicate_confirm_click(window):
    pending = window._orchestrator.process_command('abra o Obsidian')
    window._apply_command_result(pending)
    assert window._pending_plan is pending.plan
    assert window._clear_button.isEnabled()
    window._clear_conversation()
    assert window._pending_plan is None
    assert window._orchestrator.confirmation_id is None
    assert window._speech_text == ''
    assert not window._confirm_panel.isVisible()
    window._start_confirmation_worker = MagicMock()
    window._on_confirm()
    window._start_confirmation_worker.assert_not_called()


def test_transcription_captured_for_old_calendar_proposal_is_ignored(window):
    window._orchestrator.calendar_adapter = MagicMock()
    window._orchestrator.process_command('marque reunião amanhã às 15h')
    activate(window)
    pipeline = window._voice_pipeline
    pipeline._capture._audio_callback(np.full((8000, 1), 0.03, dtype=np.float32), 8000, None, None)
    pipeline.stop()
    window._orchestrator.process_command('troque para hoje')
    pipeline._transcription.transcribed.emit(pipeline.generation, 'sim')
    window._start_command_worker.assert_not_called()
    window._orchestrator.calendar_adapter.create_event.assert_not_called()
    assert pipeline._capture.is_recording


def test_preparation_shows_components_and_waits_for_all_of_them(window):
    window._speech_output.is_ready = False
    window._speech_output.state = 'warming'
    window._toggle_conversation()
    window._on_ai_warmed(window._ai_warm_token, True)
    assert not window._voice_pipeline._capture.is_recording
    assert 'IA: pronta' in window._preparation_label.text()
    assert 'Transcrição: pronta' in window._preparation_label.text()
    assert 'Voz: preparando' in window._preparation_label.text()
    window._speech_output.is_ready = True
    window._speech_output.state = 'idle'
    window._on_speech_warmed()
    assert window._voice_pipeline._capture.is_recording


def test_preparation_deadline_keeps_text_available_and_ignores_late_ready(window):
    now = [0.0]
    window._preparation.clock = lambda: now[0]
    window._speech_output.is_ready = False
    window._toggle_conversation()
    token = window._ai_warm_token
    now[0] = 121.0
    window._poll_conversation()
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording
    assert window._input.isEnabled()
    assert window._send_button.isEnabled()
    assert 'tempo excedido' in window._preparation_label.text()
    window._on_ai_warmed(token, True)
    window._on_speech_warmed()
    assert not window._voice_pipeline._capture.is_recording


def test_failed_ai_can_be_retried_without_executing_any_command(window):
    window._prepare_ai_background = MagicMock()
    window._toggle_conversation()
    window._ai_warm_generation = window._conversation_generation
    window._on_ai_warmed(window._ai_warm_token, False)
    assert not window._conversation_mode
    assert 'IA: falhou' in window._preparation_label.text()
    window._toggle_conversation()
    window._ai_warm_generation = window._conversation_generation
    window._on_ai_warmed(window._ai_warm_token, True)
    assert window._voice_pipeline._capture.is_recording
    window._start_command_worker.assert_not_called()


def test_missing_ai_ends_preparation_and_keeps_typing_available(window):
    window._orchestrator.ai_core = None
    window._toggle_conversation()
    deadline = time.monotonic() + 3
    while window._conversation_mode and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording
    assert window._send_button.isEnabled()
    assert 'IA: falhou' in window._preparation_label.text()


def test_old_warmup_requires_a_new_probe_after_restart(window):
    window._prepare_ai_background = MagicMock()
    window._toggle_conversation()
    previous = window._conversation_generation
    window._end_conversation()
    window._toggle_conversation()
    window._ai_warm_generation = previous
    window._on_ai_warmed(window._ai_warm_token, True)
    assert not window._voice_pipeline._capture.is_recording
    assert window._prepare_ai_background.call_count == 3


def test_one_click_phrase_response_and_listen_again(window):
    activate(window)
    pipeline = window._voice_pipeline
    assert pipeline.state == 'recording'
    assert pipeline._transcription.fast_mode is False
    capture = pipeline._capture
    capture._audio_callback(np.full((8000,1),0.03,dtype=np.float32),8000,None,None)
    capture._audio_callback(np.zeros((12800,1),dtype=np.float32),12800,None,None)
    window._poll_conversation()
    assert pipeline.state == 'transcribing'
    assert not capture.is_recording
    pipeline._transcription.transcribed.emit(pipeline.generation, 'Olá, tudo bem?')
    window._start_command_worker.assert_called_once_with('Olá, tudo bem?')
    assert window._input.toPlainText() == ''
    assert window._processing
    window._command_worker = MagicMock(failed=False, result=OrchestrationResult(status='success',message='Olá! Como posso ajudar?'))
    window._finish_command()
    window._speech_output.speak.assert_called_once_with('Olá! Como posso ajudar?')
    assert not capture.is_recording
    window._conversation_playback_finished()
    QTest.qWait(250)
    assert not capture.is_recording
    QTest.qWait(400)
    assert capture.is_recording


def test_tool_reply_speaks_interpretation_instead_of_source_listing(window):
    activate(window)
    window._voice_pipeline.cancel()
    window._apply_command_result(OrchestrationResult(status='success',
        message='Encontrei sua atividade.\n\nFontes: Faculdade/Circuitos/Atividade 3.md',
        speech_message='Encontrei sua atividade. Quer um resumo?'))
    window._conversation_reply()
    window._speech_output.speak.assert_called_once_with('Encontrei sua atividade. Quer um resumo?')


def test_confirmed_action_speaks_reply_without_reading_technical_details(window):
    activate(window)
    window._voice_pipeline.cancel()
    window._apply_confirmation_result(OrchestrationResult(
        status='executed_simulated',
        message='Simulei esta ação.\nExecutor: simulação\nVerificação: simulação',
        speech_message='Simulei a abertura do Obsidian. Não abri o aplicativo de verdade.',
    ))
    window._conversation_reply()
    window._speech_output.speak.assert_called_once_with(
        'Simulei a abertura do Obsidian. Não abri o aplicativo de verdade.'
    )
    assert 'Executor: simulação' in window._history.toPlainText()


def test_end_discards_late_transcript_and_ai_audio(window):
    activate(window)
    pipeline = window._voice_pipeline
    generation = pipeline.generation
    window._end_conversation()
    window._on_voice_transcribed(generation, 'fala antiga')
    assert window._input.toPlainText() == ''
    window._command_worker = MagicMock(failed=False,result=OrchestrationResult(status='success',message='Resposta antiga'))
    window._finish_command()
    window._speech_output.speak.assert_not_called()
    assert not pipeline._capture.is_recording


def test_pending_confirmation_keeps_mode_and_discards_pre_question_audio(window):
    activate(window)
    pipeline = window._voice_pipeline
    generation = pipeline.generation
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=MagicMock()))
    assert window._conversation_mode
    assert window._pending_plan is not None
    window._on_voice_transcribed(generation, 'sim')
    window._start_command_worker.assert_not_called()
    assert not window._processing
    assert not pipeline._capture.is_recording


@pytest.mark.parametrize('answer,confirmed', [('sim.', True), ('não.', False)])
def test_voice_confirmation_routes_to_current_plan_and_resumes_after_result(window, answer, confirmed):
    activate(window)
    plan = MagicMock()
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=plan))
    window._conversation_reply()
    window._speech_output.speak.assert_called_with('Confirma?')
    window._conversation_playback_finished()
    QTest.qWait(650)
    pipeline = window._voice_pipeline
    assert pipeline._capture.is_recording
    assert window._conversation_confirmation_plan is plan
    window._start_confirmation_worker = MagicMock()
    window._on_voice_transcribed(pipeline.generation, answer)
    window._start_confirmation_worker.assert_called_once_with(plan, confirmed)
    assert not pipeline._capture.is_recording
    assert window._processing
    window._confirmation_worker = MagicMock(failed=False,result=OrchestrationResult(status='success' if confirmed else 'cancelled',message='Resultado'))
    window._finish_confirmation()
    window._speech_output.speak.assert_called_with('Resultado')
    window._conversation_playback_finished()
    QTest.qWait(650)
    assert pipeline._capture.is_recording
    assert window._pending_plan is None


def test_ambiguous_voice_confirmation_reprompts_without_executing(window):
    activate(window)
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=MagicMock()))
    window._try_conversation_listen()
    window._start_confirmation_worker = MagicMock()
    window._on_voice_transcribed(window._voice_pipeline.generation, 'talvez')
    window._start_confirmation_worker.assert_not_called()
    window._speech_output.speak.assert_called_with("Resposta não reconhecida. Responda 'sim' ou 'não'.")
    window._conversation_playback_finished()
    QTest.qWait(650)
    assert window._voice_pipeline._capture.is_recording
    assert window._pending_plan is not None


def test_old_confirmation_cannot_approve_replaced_plan(window):
    activate(window)
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=MagicMock()))
    window._try_conversation_listen()
    window._pending_plan = MagicMock()
    window._start_confirmation_worker = MagicMock()
    window._on_voice_transcribed(window._voice_pipeline.generation, 'sim')
    window._start_confirmation_worker.assert_not_called()


def test_confirmation_transcript_after_end_does_not_execute(window):
    activate(window)
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=MagicMock()))
    window._try_conversation_listen()
    generation = window._voice_pipeline.generation
    window._start_confirmation_worker = MagicMock()
    window._end_conversation()
    window._on_voice_transcribed(generation, 'sim')
    window._start_confirmation_worker.assert_not_called()


@pytest.mark.parametrize('answer', ['sim.', 'não.'])
def test_calendar_confirmation_without_ui_plan_remains_spoken(window, answer):
    activate(window)
    window._voice_pipeline.cancel()
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Vou criar o evento. Confirma?'))
    window._conversation_reply()
    assert window._conversation_mode
    window._conversation_playback_finished()
    QTest.qWait(650)
    generation = window._voice_pipeline.generation
    window._on_voice_transcribed(generation, answer)
    window._start_command_worker.assert_called_once_with(answer.rstrip('.'))


@pytest.mark.parametrize('answer,creates_event', [('sim.', True), ('não.', False), ('talvez', False)])
def test_calendar_voice_cycle_uses_real_orchestrator_with_fake_calendar(window, answer, creates_event):
    adapter = MagicMock()
    adapter.create_event.return_value.summary = 'Reunião'
    window._orchestrator.calendar_adapter = adapter
    window._start_command_worker = MainWindow._start_command_worker.__get__(window)
    activate(window)

    def say(text):
        pipeline = window._voice_pipeline
        assert pipeline._capture.is_recording
        pipeline._capture._audio_callback(np.full((8000,1),0.03,dtype=np.float32),8000,None,None)
        pipeline.stop()
        pipeline._transcription.transcribed.emit(pipeline.generation, text)
        deadline = time.monotonic() + 3
        while window._processing and time.monotonic() < deadline:
            QTest.qWait(10)
        assert not window._processing
        assert window._conversation_mode
        assert not pipeline._capture.is_recording
        window._conversation_playback_finished()
        QTest.qWait(650)
        assert pipeline._capture.is_recording

    say('marque reunião amanhã às 15h')
    adapter.create_event.assert_not_called()
    assert window._orchestrator._pending_event_draft is not None
    say(answer)
    if creates_event:
        adapter.create_event.assert_called_once()
    else:
        adapter.create_event.assert_not_called()
    assert (window._orchestrator._pending_event_draft is not None) == (answer == 'talvez')


def test_existing_draft_is_preserved(window):
    window._input.setPlainText('rascunho')
    window._toggle_conversation()
    assert window._conversation_mode
    assert window._input.toPlainText() == 'rascunho'
    window._start_command_worker.assert_not_called()


@pytest.mark.parametrize('submission', ['button','enter'])
def test_typed_request_in_voice_mode_automatically_speaks_reply(window, submission):
    activate(window)
    generation=window._conversation_generation
    capture_generation=window._voice_pipeline.generation
    window._start_command_worker=MainWindow._start_command_worker.__get__(window,MainWindow)
    response=OrchestrationResult(status='success',message='Resposta visual com fontes.',
                                 speech_message='Esta é a resposta falada.')
    with patch.object(window._orchestrator,'process_session_command',return_value=response) as process:
        window._input.setPlainText('Explique este assunto fictício.')
        if submission=='button':
            window._send_button.click()
        else:
            QTest.keyClick(window._input,Qt.Key_Return)
        deadline=time.monotonic()+3
        while window._command_worker is not None and time.monotonic()<deadline:
            QTest.qWait(10)
        assert window._command_worker is None
        assert process.call_count==1
        assert process.call_args.args[0]=='Explique este assunto fictício.'
    assert window._conversation_mode and window._conversation_generation==generation
    assert window._orchestrator.voice_conversation
    assert not window._voice_pipeline._capture.is_recording
    window._speech_output.speak.assert_called_once_with('Esta é a resposta falada.')
    assert 'Resposta visual com fontes.' in window._history.toPlainText()
    # Uma transcrição capturada antes do envio digitado não vira outro pedido.
    window._on_voice_transcribed(capture_generation,'áudio anterior')
    assert not window._processing


def test_typed_request_after_ending_voice_mode_does_not_speak_automatically(window):
    activate(window)
    window._end_conversation()
    window._start_command_worker=MainWindow._start_command_worker.__get__(window,MainWindow)
    response=OrchestrationResult(status='success',message='Resposta apenas na conversa.')
    with patch.object(window._orchestrator,'process_session_command',return_value=response):
        window._input.setPlainText('Pedido fora do modo de voz.')
        window._send_button.click()
        deadline=time.monotonic()+3
        while window._command_worker is not None and time.monotonic()<deadline:
            QTest.qWait(10)
    assert window._command_worker is None and not window._conversation_mode
    window._speech_output.speak.assert_not_called()


@pytest.mark.parametrize('failure_stage',['start','process'])
def test_typed_request_failure_speaks_error_instead_of_previous_reply(window,failure_stage):
    activate(window)
    window._speech_text='Resposta anterior que não deve ser repetida.'
    window._input.setPlainText('Novo pedido digitado.')
    if failure_stage=='start':
        window._start_command_worker=MagicMock(side_effect=RuntimeError('fixture'))
        window._send_button.click()
    else:
        window._start_command_worker=MainWindow._start_command_worker.__get__(window,MainWindow)
        with patch.object(window._orchestrator,'process_session_command',side_effect=RuntimeError('fixture')):
            window._send_button.click()
            deadline=time.monotonic()+3
            while window._command_worker is not None and time.monotonic()<deadline:
                QTest.qWait(10)
    assert window._command_worker is None and not window._processing
    assert window._conversation_mode
    window._speech_output.speak.assert_called_once_with('Ocorreu um erro inesperado ao processar o comando.')


@pytest.mark.parametrize('answer,confirmed',[('sim',True),('não',False)])
def test_typed_confirmation_in_voice_mode_keeps_spoken_reply(window,answer,confirmed):
    activate(window)
    generation=window._conversation_generation
    plan=MagicMock()
    window._pending_plan=plan
    window._start_confirmation_worker=MainWindow._start_confirmation_worker.__get__(window,MainWindow)
    response=OrchestrationResult(status='success' if confirmed else 'cancelled',
                                 message='Operação confirmada.' if confirmed else 'Operação cancelada.')
    with patch.object(window._orchestrator,'confirm_session_proposal',return_value=response) as process:
        window._input.setPlainText(answer)
        window._send_button.click()
        deadline=time.monotonic()+3
        while window._confirmation_worker is not None and time.monotonic()<deadline:
            QTest.qWait(10)
        assert process.call_count==1 and process.call_args.args[1] is confirmed
    assert window._confirmation_worker is None
    assert window._conversation_mode and window._conversation_generation==generation
    window._speech_output.speak.assert_called_once_with(response.message)


def test_failed_warmup_never_opens_microphone(window):
    window._toggle_conversation()
    window._on_ai_warmed(window._conversation_generation, False)
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording


def test_stop_generation_resumes_listening_while_voice_rewarms(window):
    activate(window)
    window._voice_pipeline.cancel()
    window._speech_output.is_ready=False
    window._speech_output.state='warming'
    window._stop_speech()
    QTest.qWait(250)
    assert window._voice_pipeline._capture.is_recording


def test_disconnected_microphone_ends_mode(window):
    activate(window)
    window._voice_pipeline._capture._last_frame_at=0
    window._poll_conversation()
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording


def test_memory_failure_ends_capture_preserves_confirmation_and_never_executes(window):
    activate(window)
    plan = MagicMock()
    window._apply_command_result(OrchestrationResult(status='awaiting_confirmation',message='Confirma?',plan=plan))
    window._try_conversation_listen()
    window._start_confirmation_worker = MagicMock()
    window._on_voice_transcription_failed(window._voice_pipeline.generation, 'voice_memory_exhausted')
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording
    assert window._pending_plan is plan
    window._start_confirmation_worker.assert_not_called()
    assert 'A transcrição falhou ao alocar memória.' in window._history.toPlainText()


def test_silence_rotates_buffer_without_sending_to_ai(window):
    activate(window)
    capture=window._voice_pipeline._capture
    capture._audio_callback(np.zeros((336000,1),dtype=np.float32),336000,None,None)
    window._poll_conversation()
    assert window._voice_pipeline._capture.is_recording
    window._start_command_worker.assert_not_called()
    assert not hasattr(window._voice_pipeline._transcription,'audio')


def test_background_preparation_does_not_open_microphone(window):
    window._prepare_voice_background()
    window._on_ai_warmed(window._ai_warm_token,True)
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording


@pytest.mark.parametrize('minimize', ['native', 'button'])
def test_minimize_keeps_conversation_and_microphone_active(window, minimize):
    window.setAttribute(Qt.WA_DontShowOnScreen,True)
    window.show()
    activate(window)
    generation = window._conversation_generation
    window._speech_output.stop.reset_mock()
    if minimize == 'native':
        window.showMinimized()
    else:
        window._minimize_window()
    QApplication.processEvents()
    assert window.isMinimized()
    assert window._conversation_mode
    assert window._conversation_generation == generation
    assert window._voice_pipeline._capture.is_recording
    window._speech_output.stop.assert_not_called()
    window.showNormal()
    QApplication.processEvents()
    assert window._conversation_mode
    assert window._voice_pipeline._capture.is_recording


def test_hide_closes_microphone_and_ends_mode(window):
    window.setAttribute(Qt.WA_DontShowOnScreen,True)
    window.show()
    activate(window)
    window.hide()
    assert not window._conversation_mode
    assert not window._voice_pipeline._capture.is_recording


def test_early_rearm_timer_schedules_retry_after_primed_turn(window):
    activate(window)
    window._voice_pipeline.cancel()
    window._conversation_primed=True
    window._conversation_listen_after=time.monotonic()+.12
    window._voice_pipeline.cycle.rearm_after=time.monotonic()+.12
    with patch('therion.interface.desktop.QTimer.singleShot') as timer:
        window._try_conversation_listen()
        timer.assert_called_once()
    assert not window._voice_pipeline._capture.is_recording
    QTest.qWait(160)
    window._try_conversation_listen()
    assert window._voice_pipeline._capture.is_recording


def test_cycle_rearm_retries_without_broad_idle_poll(window):
    activate(window)
    window._voice_pipeline.cancel()
    window._conversation_primed=True
    window._conversation_listen_after=0
    window._voice_pipeline.cycle.rearm_after=time.monotonic()+.12
    with patch('therion.interface.desktop.QTimer.singleShot') as timer:
        window._try_conversation_listen()
        assert timer.call_args.args[0]==50
    window._end_conversation()
    with patch('therion.interface.desktop.QTimer.singleShot') as timer:
        window._try_conversation_listen()
        timer.assert_not_called()


def test_idle_clears_stale_speaking_label_in_conversation(window):
    activate(window)
    window._conversation_label.setText('Falando…')
    window._on_speech_state('idle')
    assert window._conversation_label.text()=='Preparando escuta…'
