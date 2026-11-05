"""Encerramento sob carga cooperativa; sem microfone, fala ou modelo pessoal."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import numpy as np
from PySide6.QtCore import Qt,QProcess
from PySide6.QtWidgets import QApplication
from therion.voice.service import VoiceModelService
from therion.voice.transcription import VoiceTranscriptionService


def loading_service(tmp_path):
    entered=threading.Event();release=threading.Event()
    def factory(path):entered.set();assert release.wait(3);return object()
    service=VoiceModelService(str(tmp_path),model_factory=factory)
    assert service.load() and entered.wait(1)
    return service,release


def test_loader_shutdown_waits_and_never_announces_a_late_model(tmp_path):
    service,release=loading_service(tmp_path);events=[]
    service.loaded.connect(lambda model:events.append('loaded'),Qt.DirectConnection)
    service.load_failed.connect(lambda error:events.append('failed'),Qt.DirectConnection)
    try:
        service.shutdown()
        assert not service.is_quiescent and not service.load()
    finally:release.set();service._thread.join(timeout=2)
    assert service.is_quiescent and events==[] and service.model is None


def test_transcription_shutdown_waits_and_drops_late_yes():
    entered=threading.Event();release=threading.Event();events=[]
    class Model:
        def transcribe(self,audio,**kwargs):
            entered.set();assert release.wait(3)
            return iter([SimpleNamespace(text='sim')]),{}
    service=VoiceTranscriptionService(Model(),is_current_generation=lambda generation:True)
    service.transcribed.connect(lambda *args:events.append(args),Qt.DirectConnection)
    service.transcription_failed.connect(lambda *args:events.append(args),Qt.DirectConnection)
    assert service.transcribe_async(np.zeros(16000,dtype=np.float32),1) and entered.wait(1)
    try:
        service.shutdown()
        assert not service.is_quiescent
        assert not service.transcribe_async(np.zeros(16000,dtype=np.float32),2)
    finally:release.set();service._thread.join(timeout=2)
    assert service.is_quiescent and events==[]


def test_tts_shutdown_tracks_process_until_actual_exit():
    qt=QApplication.instance() or QApplication([])
    from therion.voice.speech_output import SpeechOutput
    with patch('therion.voice.speech_output.QSoundEffect'):
        service=SpeechOutput({});process=MagicMock();process.state.return_value=QProcess.Running
        service.process=process
        service.shutdown()
        assert not service.is_quiescent
        process.kill.assert_called_once()
        process.state.return_value=QProcess.NotRunning
        assert service.is_quiescent
        service.deleteLater();qt.processEvents()


def test_desktop_defers_quit_until_loading_thread_finishes(tmp_path):
    qt=QApplication.instance() or QApplication([])
    from therion.interface.desktop import MainWindow
    from therion.context.second_brain import SecondBrainReader
    service,release=loading_service(tmp_path);app=MagicMock();window=None
    try:
        with patch.object(MainWindow,'_setup_tray'),patch.object(SecondBrainReader,'DEFAULT_VAULT_ROOT',str(tmp_path/'vault')),patch('therion.interface.desktop.QTimer.singleShot') as timer:
            window=MainWindow(app,config={},voice_service=service,config_loader=lambda:{})
            cancelled=threading.Event()
            window._processing=True;window._command_worker=SimpleNamespace(cancelled=cancelled)
            window._quit_application()
            app.quit.assert_not_called()
            assert window._quit_requested and timer.called and cancelled.is_set()
            release.set();service._thread.join(timeout=2)
            window._processing=False;window._command_worker=None
            window._quit_application()
            app.quit.assert_called_once()
    finally:
        release.set();service._thread.join(timeout=2)
        if window is not None:
            window._memory_timer.stop();window._conversation_timer.stop();window._orchestrator.close()
            window.deleteLater();qt.processEvents()
