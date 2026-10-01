"""Testes unitários para VoiceTranscriptionService — sem modelo real."""

import threading
from dataclasses import dataclass
import numpy as np
import pytest
from PySide6.QtCore import Qt

from therion.voice.transcription import VoiceTranscriptionService

_TIMEOUT = 5.0


@dataclass
class FakeSegment:
    text: str


class FakeWhisperModel:
    def __init__(self, segments=None, info=None, exception=None, gate=None) -> None:
        self.segments = segments if segments is not None else []
        self.info = info or {}
        self.exception = exception
        self.gate = gate
        self.calls = []
        self.thread_ids = []

    def transcribe(self, audio, **kwargs):
        self.thread_ids.append(threading.get_ident())
        self.calls.append({"audio": audio, "kwargs": kwargs})
        if self.gate is not None:
            self.gate.wait(_TIMEOUT)
        if self.exception is not None:
            raise self.exception
        return self.segments, self.info


def _wait(event: threading.Event, label: str) -> None:
    assert event.wait(_TIMEOUT), f"Timeout aguardando {label}"


def test_sucesso_texto_montado():
    fake_segments = [
        FakeSegment("  Olá mundo  "),
        FakeSegment("segundo segmento\n"),
        FakeSegment(" final "),
    ]
    model = FakeWhisperModel(segments=fake_segments)
    service = VoiceTranscriptionService(model)

    done = threading.Event()
    results = []

    service.transcribed.connect(
        lambda gen, text: (results.append((gen, text)), done.set()),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.zeros(16000, dtype=np.float32)
    assert service.transcribe_async(audio, generation=42) is True
    _wait(done, "transcribed")

    assert results == [(42, "Olá mundo segundo segmento final")]
    assert not service.is_busy


def test_argumentos_exatos_transcribe():
    model = FakeWhisperModel(segments=[FakeSegment("teste")])
    service = VoiceTranscriptionService(model)

    done = threading.Event()
    service.transcribed.connect(
        lambda gen, text: done.set(),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.ones(3200, dtype=np.float32)
    assert service.transcribe_async(audio, generation=1) is True
    _wait(done, "transcribed")

    assert len(model.calls) == 1
    call = model.calls[0]
    assert np.array_equal(call["audio"], audio)

    expected_hotwords = (
        "Obsidian, aliases, Segundo Cérebro, álgebra linear, "
        "circuitos lógicos, matrizes, determinantes, cancele"
    )
    assert call["kwargs"] == {
        "language": "pt",
        "beam_size": 5,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "hotwords": expected_hotwords,
    }


def test_execucao_fora_da_thread_chamadora():
    model = FakeWhisperModel(segments=[FakeSegment("ok")])
    service = VoiceTranscriptionService(model)

    done = threading.Event()
    service.transcribed.connect(
        lambda gen, text: done.set(),
        Qt.ConnectionType.DirectConnection,
    )

    caller_tid = threading.get_ident()
    audio = np.zeros(1600, dtype=np.float32)
    service.transcribe_async(audio, generation=10)
    _wait(done, "transcribed")

    assert len(model.thread_ids) == 1
    assert model.thread_ids[0] != caller_tid


def test_single_flight():
    gate = threading.Event()
    model = FakeWhisperModel(segments=[FakeSegment("ok")], gate=gate)
    service = VoiceTranscriptionService(model)

    audio = np.zeros(1600, dtype=np.float32)
    assert service.transcribe_async(audio, generation=1) is True
    assert service.is_busy is True

    # Chamada concorrente deve ser rejeitada imediatamente
    assert service.transcribe_async(audio, generation=2) is False
    assert service.transcribe_async(audio, generation=3) is False

    # Libera a execução
    gate.set()

    # Aguarda a finalização
    for _ in range(50):
        if not service.is_busy:
            break
        threading.Event().wait(0.05)

    assert service.is_busy is False
    assert len(model.calls) == 1

    # Nova chamada deve ser aceita agora
    assert service.transcribe_async(audio, generation=4) is True


def test_excecao_vira_erro():
    model = FakeWhisperModel(exception=RuntimeError("falha interna no motor"))
    service = VoiceTranscriptionService(model)

    done = threading.Event()
    failures = []

    service.transcription_failed.connect(
        lambda gen, msg: (failures.append((gen, msg)), done.set()),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.zeros(1600, dtype=np.float32)
    assert service.transcribe_async(audio, generation=99) is True
    _wait(done, "transcription_failed")

    assert len(failures) == 1
    gen, msg = failures[0]
    assert gen == 99
    assert "falha interna no motor" in msg
    assert not service.is_busy


def test_texto_vazio():
    model = FakeWhisperModel(segments=[FakeSegment("   "), FakeSegment("")])
    service = VoiceTranscriptionService(model)

    done = threading.Event()
    results = []

    service.transcribed.connect(
        lambda gen, text: (results.append((gen, text)), done.set()),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.zeros(1600, dtype=np.float32)
    assert service.transcribe_async(audio, generation=7) is True
    _wait(done, "transcribed")

    assert results == [(7, "")]


def test_generation_obsoleta_descarta_sucesso():
    gate = threading.Event()
    model = FakeWhisperModel(segments=[FakeSegment("tarde demais")], gate=gate)

    current_gen = 1
    service = VoiceTranscriptionService(
        model,
        is_current_generation=lambda gen: gen == current_gen,
    )

    results = []
    service.transcribed.connect(
        lambda gen, text: results.append((gen, text)),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.zeros(1600, dtype=np.float32)
    service.transcribe_async(audio, generation=1)

    # Invalida a geração enquanto a transcrição ainda está rodando
    current_gen = 2
    gate.set()

    # Aguarda término do worker
    for _ in range(50):
        if not service.is_busy:
            break
        threading.Event().wait(0.05)

    assert not service.is_busy
    assert results == []  # Resultado descartado


def test_generation_obsoleta_descarta_erro():
    gate = threading.Event()
    model = FakeWhisperModel(exception=RuntimeError("erro tardio"), gate=gate)

    current_gen = 1
    service = VoiceTranscriptionService(
        model,
        is_current_generation=lambda gen: gen == current_gen,
    )

    failures = []
    service.transcription_failed.connect(
        lambda gen, msg: failures.append((gen, msg)),
        Qt.ConnectionType.DirectConnection,
    )

    audio = np.zeros(1600, dtype=np.float32)
    service.transcribe_async(audio, generation=1)

    # Invalida a geração
    current_gen = 2
    gate.set()

    # Aguarda término do worker
    for _ in range(50):
        if not service.is_busy:
            break
        threading.Event().wait(0.05)

    assert not service.is_busy
    assert failures == []  # Erro descartado
