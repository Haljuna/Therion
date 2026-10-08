"""Falha recuperável de STT atravessando serviço, pipeline e interface Qt."""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from PySide6.QtWidgets import QApplication

from therion.interface.desktop import MainWindow
from therion.voice.pipeline import VoicePipeline
from therion.voice.service import VoiceModelService
from therion.voice.transcription import VoiceTranscriptionService


def test_transcription_failure_then_success_in_same_window():
    qapp = QApplication.instance() or QApplication([])
    model = MagicMock()
    model.transcribe.side_effect = [
        RuntimeError("falha controlada de STT"),
        ([SimpleNamespace(text="Teste de recuperação.")], {}),
    ]
    service = VoiceModelService("modelo-de-teste")
    service._state = VoiceModelService.STATE_READY
    capture = MagicMock()
    capture.start.return_value = True
    capture.stop.return_value = np.ones(16000, dtype=np.float32)
    transcription = VoiceTranscriptionService(model)
    pipeline = VoicePipeline(capture, transcription)
    app = MagicMock()
    with patch.object(MainWindow, "_setup_tray"):
        window = MainWindow(app, voice_service=service)
    window._voice_pipeline = pipeline
    pipeline.transcribed.connect(window._on_voice_transcribed)
    pipeline.transcription_failed.connect(window._on_voice_transcription_failed)
    pipeline.state_changed.connect(window._on_voice_pipeline_state_changed)
    window._input.setPlainText("Rascunho:")

    def wait_idle():
        deadline = time.monotonic() + 5
        while pipeline.state != VoicePipeline.STATE_IDLE and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        qapp.processEvents()
        assert pipeline.state == VoicePipeline.STATE_IDLE
        assert not transcription.is_busy

    try:
        with patch.object(window, "_append", wraps=window._append) as append:
            window._on_voice_pressed()
            window._on_voice_released()
            wait_idle()
            append.assert_called_once_with("Therion", "Transcrição de voz falhou: falha controlada de STT")
        assert window._input.toPlainText() == "Rascunho:"
        assert window._voice_button.text() == "Segure para falar"
        assert window._voice_button.isEnabled()

        window._on_voice_pressed()
        window._on_voice_released()
        wait_idle()
        assert window._input.toPlainText() == "Rascunho: Teste de recuperação."
        assert window._voice_pipeline is pipeline
        assert pipeline._transcription is transcription
        assert model.transcribe.call_count == 2
        assert app.mock_calls == []  # erro e sucesso não enviam comandos
    finally:
        pipeline.cancel()
        window.deleteLater()
        qapp.processEvents()
