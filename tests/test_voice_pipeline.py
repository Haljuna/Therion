"""Testes unitários para VoicePipeline — coordenação sem UI."""

import numpy as np
import pytest
from PySide6.QtCore import QObject, Qt, Signal

from therion.voice.pipeline import VoicePipeline


class FakeCapture:
    def __init__(self, audio_to_return=None) -> None:
        self.audio_to_return = audio_to_return
        self.started = False
        self.stopped = False
        self.canceled = False
        self.fail_on_start = False

    def start(self) -> bool:
        if self.fail_on_start:
            return False
        self.started = True
        return True

    def stop(self):
        self.stopped = True
        self.started = False
        return self.audio_to_return

    def cancel(self) -> None:
        self.canceled = True
        self.started = False


class FakeTranscription(QObject):
    transcribed = Signal(int, str)
    transcription_failed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = []
        self._is_current_generation = None
        self.is_busy = False
        self.fail_dispatch = False

    def transcribe_async(self, audio, generation) -> bool:
        if self.fail_dispatch:
            return False
        self.calls.append((audio, generation))
        self.is_busy = True
        return True

    def finish(self, generation: int, text: str) -> None:
        self.is_busy = False
        self.transcribed.emit(generation, text)

    def fail(self, generation: int, error: str) -> None:
        self.is_busy = False
        self.transcription_failed.emit(generation, error)


def test_start_stop_transcribe_fluxo_completo():
    sample_audio = np.full(8000, 0.5, dtype=np.float32)
    capture = FakeCapture(audio_to_return=sample_audio)
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    assert pipeline.state == VoicePipeline.STATE_IDLE
    states = []
    pipeline.state_changed.connect(
        lambda s: states.append(s), Qt.ConnectionType.DirectConnection
    )

    results = []
    pipeline.transcribed.connect(
        lambda gen, text: results.append((gen, text)),
        Qt.ConnectionType.DirectConnection,
    )

    assert pipeline.start() is True
    assert pipeline.state == VoicePipeline.STATE_RECORDING
    assert capture.started is True
    gen_1 = pipeline.generation
    assert gen_1 > 0

    assert pipeline.stop() is True
    assert pipeline.state == VoicePipeline.STATE_TRANSCRIBING
    assert capture.stopped is True
    assert len(transcription.calls) == 1
    call_audio, call_gen = transcription.calls[0]
    assert np.array_equal(call_audio, sample_audio)
    assert call_gen == gen_1

    transcription.finish(gen_1, "texto transcrito com sucesso")
    assert pipeline.state == VoicePipeline.STATE_IDLE
    assert results == [(gen_1, "texto transcrito com sucesso")]
    assert states == ["recording", "transcribing", "idle"]


def test_audio_vazio_ou_curto_nao_transcreve():
    capture = FakeCapture(audio_to_return=None)
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    assert pipeline.start() is True
    assert pipeline.state == VoicePipeline.STATE_RECORDING

    assert pipeline.stop() is False
    assert pipeline.state == VoicePipeline.STATE_IDLE
    assert len(transcription.calls) == 0


def test_cancel_descarta_invalida_resultado_tardio():
    sample_audio = np.full(4000, 0.1, dtype=np.float32)
    capture = FakeCapture(audio_to_return=sample_audio)
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    results = []
    failures = []
    pipeline.transcribed.connect(
        lambda gen, text: results.append((gen, text)),
        Qt.ConnectionType.DirectConnection,
    )
    pipeline.transcription_failed.connect(
        lambda gen, err: failures.append((gen, err)),
        Qt.ConnectionType.DirectConnection,
    )

    pipeline.start()
    gen = pipeline.generation
    pipeline.stop()
    assert pipeline.state == VoicePipeline.STATE_TRANSCRIBING

    # Usuário cancela durante a transcrição
    pipeline.cancel()
    assert pipeline.state == VoicePipeline.STATE_IDLE
    assert pipeline.generation > gen

    # Transcrição tardia conclui para a geração antiga
    transcription.finish(gen, "resultado que chegou tarde")
    assert results == []

    # Mesma coisa com erro tardio
    transcription.fail(gen, "erro que chegou tarde")
    assert failures == []


def test_novo_ciclo_usa_nova_generation():
    capture = FakeCapture(audio_to_return=np.zeros(1600, dtype=np.float32))
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    pipeline.start()
    gen_1 = pipeline.generation
    pipeline.stop()
    transcription.finish(gen_1, "primeiro")

    pipeline.start()
    gen_2 = pipeline.generation
    pipeline.stop()
    transcription.finish(gen_2, "segundo")

    assert gen_2 > gen_1
    assert [call[1] for call in transcription.calls] == [gen_1, gen_2]


def test_single_flight_e_chamadas_invalidas():
    sample_audio = np.ones(3200, dtype=np.float32)
    capture = FakeCapture(audio_to_return=sample_audio)
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    # Stop em IDLE
    assert pipeline.stop() is False

    # Start normal
    assert pipeline.start() is True
    # Start concorrente durante gravação
    assert pipeline.start() is False

    # Stop passa para transcrevendo
    assert pipeline.stop() is True
    # Start ou stop enquanto transcrevendo
    assert pipeline.start() is False
    assert pipeline.stop() is False

    # Finaliza
    transcription.finish(pipeline.generation, "ok")
    assert pipeline.state == VoicePipeline.STATE_IDLE


def test_falha_ao_iniciar_captura():
    capture = FakeCapture()
    capture.fail_on_start = True
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    assert pipeline.start() is False
    assert pipeline.state == VoicePipeline.STATE_IDLE


def test_falha_na_transcricao_emite_erro():
    sample_audio = np.ones(3200, dtype=np.float32)
    capture = FakeCapture(audio_to_return=sample_audio)
    transcription = FakeTranscription()
    pipeline = VoicePipeline(capture, transcription)

    failures = []
    pipeline.transcription_failed.connect(
        lambda gen, msg: failures.append((gen, msg)),
        Qt.ConnectionType.DirectConnection,
    )

    pipeline.start()
    gen = pipeline.generation
    pipeline.stop()

    transcription.fail(gen, "erro simulado de transcrição")
    assert pipeline.state == VoicePipeline.STATE_IDLE
    assert failures == [(gen, "erro simulado de transcrição")]
