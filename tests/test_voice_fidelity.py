"""Fala incerta não vira mensagem, execução ou confirmação."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import Qt

from therion.voice.transcription import VoiceTranscriptionService, UNCLEAR_AUDIO
from tests.test_voice_transcription import FakeWhisperModel
from tests.test_voice_conversation import window, activate
from tests import test_autonomy_v4 as autonomy_fixtures
from therion.core.orchestrator import Orchestrator


def segment(text, **metrics):
    return SimpleNamespace(text=text, avg_logprob=metrics.get('avg_logprob', -.25),
        no_speech_prob=metrics.get('no_speech_prob', .01),
        compression_ratio=metrics.get('compression_ratio', 1.1))


def transcribe(segments, **kwargs):
    model = FakeWhisperModel(segments=segments)
    service = VoiceTranscriptionService(model, **kwargs)
    service.fast_mode = True  # Não pode diminuir precisão por configuração antiga.
    done = threading.Event()
    texts, errors = [], []
    service.transcribed.connect(lambda gen, text: (texts.append(text), done.set()), Qt.DirectConnection)
    service.transcription_failed.connect(lambda gen, error: (errors.append(error), done.set()), Qt.DirectConnection)
    assert service.transcribe_async(np.zeros(16000, np.float32), 1)
    assert done.wait(5)
    assert not service.is_busy
    return model, texts, errors


@pytest.mark.parametrize('metrics', [
    {'avg_logprob': -1.1}, {'no_speech_prob': .7},
    {'compression_ratio': 2.5}, {'avg_logprob': float('nan')},
])
def test_low_confidence_discards_whole_capture_including_clear_suffix(metrics):
    _, texts, errors = transcribe([segment('Não', **metrics), segment('abre o Chrome')])
    assert texts == []
    assert errors == [UNCLEAR_AUDIO]


def test_clear_command_keeps_original_words_and_full_decoder():
    model, texts, errors = transcribe([segment('Abre o Google Chrome.')])
    assert texts == ['Abre o Google Chrome.'] and errors == []
    assert model.calls[0]['kwargs']['beam_size'] == 5
    assert model.calls[0]['kwargs']['temperature'] == 0.0


def test_unknown_words_are_never_rewritten_into_registered_apps():
    _, texts, errors = transcribe([segment('pretas.')], vocabulary_provider=lambda: ['Google Chrome'])
    assert texts == ['pretas.'] and not errors


def test_vocabulary_uses_current_catalog_without_full_paths_or_duplicate_prompts():
    model, _, _ = transcribe([segment('Chrome')],
        vocabulary_provider=lambda: ['Google Chrome', 'chrome', 'Chrome', 'Notas\nPessoais'])
    words = model.calls[0]['kwargs']['hotwords']
    assert 'Google Chrome' in words and words.count('chrome') == 1
    assert '\n' not in words
    model, _, _ = transcribe([segment('teste')], vocabulary_provider=lambda: ['nome longo ' * 20] * 100)
    assert len(model.calls[0]['kwargs']['hotwords']) <= 512


@pytest.mark.parametrize('pending', [False, True])
def test_unclear_voice_does_not_send_to_ai_or_confirm_plan(window, pending):
    activate(window)
    pipeline = window._voice_pipeline
    plan = object() if pending else None
    window._pending_plan = plan
    window._handle_confirmation = MagicMock()
    pipeline._capture._audio_callback(np.full((8000, 1), .03, np.float32), 8000, None, None)
    assert pipeline.stop()
    pipeline._transcription.transcription_failed.emit(pipeline.generation, UNCLEAR_AUDIO)
    assert window._conversation_mode and pipeline.state == 'recording'
    assert window._pending_plan is plan
    assert 'Repita a frase' in window._history.toPlainText()
    window._start_command_worker.assert_not_called()
    window._handle_confirmation.assert_not_called()


def test_vocabulary_refreshes_after_alias_change(window):
    app = SimpleNamespace(name='Google Chrome', aliases=['chrome'])
    catalog = MagicMock()
    window._orchestrator.application_catalog = catalog
    catalog.entries.return_value = [app]
    assert window._voice_vocabulary() == ['Google Chrome', 'chrome']
    app.aliases = ['navegador']
    assert window._voice_vocabulary() == ['Google Chrome', 'navegador']


class TestApplicationVoiceRouting:
    """Executável fictício, somente confirmação/simulação; sem abertura real."""

    def test_google_chrome_with_voice_punctuation_bypasses_ai(self):
        fixture = autonomy_fixtures.AutonomyTests()
        fixture.setUp()
        from therion.autonomy.apps import ApplicationCatalog
        path = fixture.root / 'chrome.exe'
        path.write_bytes(b'fixture - never execute')
        app = ApplicationCatalog(fixture.runtime).register('Google Chrome', str(path), ('chrome',))
        ai = MagicMock()
        orch = Orchestrator(simulate=True, log_dir=str(fixture.root/'logs'),
            autonomy_runtime=fixture.runtime, ai_core=ai)
        try:
            for command in ('Abre o Google Chrome.', 'Abra o Chrome!', 'Therion, abre o Google Chrome.'):
                result = orch.process_command(command)
                assert result.status == 'awaiting_confirmation', result.message
                assert result.intent.target == app.id
                orch.confirm_and_execute(result.plan, False)
            ai.classify_detailed.assert_not_called()
        finally:
            orch.close()
            fixture.tearDown()
