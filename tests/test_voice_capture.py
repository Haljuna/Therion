"""Testes unitários para AudioCaptureService — sem hardware de áudio."""

import threading
import time
import numpy as np
import pytest

from therion.voice.capture import AudioCaptureService


class FakeInputStream:
    """Mock de sounddevice.InputStream para testes isolados."""

    def __init__(
        self,
        *,
        samplerate: int = 16_000,
        channels: int = 1,
        dtype: str = "float32",
        callback=None,
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def feed(self, frames: int, value: float = 0.5) -> None:
        """Simula entrega de áudio via callback."""
        if self.callback is not None:
            data = np.full((frames, self.channels), value, dtype=np.float32)
            self.callback(data, frames, None, None)


def test_start_stop_fluxo_basico():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    assert not service.is_recording

    assert service.start() is True
    assert service.is_recording
    assert len(streams) == 1
    stream = streams[0]
    assert stream.started
    assert not stream.stopped
    assert not stream.closed

    # Alimenta 0.5s de áudio (8000 frames a 16kHz)
    stream.feed(8000, value=0.25)

    audio = service.stop()
    assert audio is not None
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 8000
    assert np.allclose(audio, 0.25)
    assert not service.is_recording
    assert stream.stopped
    assert stream.closed


def test_single_flight():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    assert service.start() is True
    assert service.start() is False
    assert service.start() is False
    assert len(streams) == 1

    # Após parar, deve permitir novo start
    service.stop()
    assert not service.is_recording
    assert service.start() is True
    assert len(streams) == 2
    service.stop()


def test_chunks_concatenacao_ordenada():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    service.start()
    stream = streams[0]

    # Simula 3 blocos de 2000 frames com valores distintos
    stream.feed(2000, value=0.1)
    stream.feed(2000, value=0.2)
    stream.feed(2000, value=0.3)

    audio = service.stop()
    assert audio is not None
    assert len(audio) == 6000
    assert np.allclose(audio[:2000], 0.1)
    assert np.allclose(audio[2000:4000], 0.2)
    assert np.allclose(audio[4000:], 0.3)


def test_audio_curto_retorna_none():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)

    # Caso 1: menos de 0.2s (3200 frames a 16kHz) -> 1000 frames
    service.start()
    streams[0].feed(1000)
    audio = service.stop()
    assert audio is None

    # Caso 2: nenhum áudio alimentado
    service.start()
    audio = service.stop()
    assert audio is None

    # Caso 3: stop sem start
    assert service.stop() is None


def test_cancelamento_descarta_chunks():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    service.start()
    stream = streams[0]
    stream.feed(5000, value=0.8)

    service.cancel()
    assert not service.is_recording
    assert stream.stopped
    assert stream.closed

    # Stop subsequente deve ser None
    assert service.stop() is None

    # Nova gravação não deve herdar chunks antigos
    service.start()
    stream2 = streams[1]
    stream2.feed(4000, value=0.3)
    audio = service.stop()
    assert audio is not None
    assert len(audio) == 4000
    assert np.allclose(audio, 0.3)


def test_cleanup_repetido_idempotente():
    streams = []

    def factory(**kwargs):
        stream = FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    service.start()

    # Múltiplos cancels e stops não devem levantar exceção
    service.cancel()
    service.cancel()
    assert service.stop() is None
    assert service.stop() is None


def test_erro_ao_abrir_stream_sem_crash():
    def failing_factory(**kwargs):
        raise RuntimeError("dispositivo de áudio ocupado ou indisponível")

    service = AudioCaptureService(stream_factory=failing_factory)
    assert service.start() is False
    assert not service.is_recording
    assert service.stop() is None

    # Recuperação: se o erro cessar, volta a funcionar
    service._stream_factory = lambda **kwargs: FakeInputStream(**kwargs)
    assert service.start() is True
    assert service.is_recording
    service.stop()


def test_seguranca_do_buffer_corrida_callback_stop():
    stream = None

    def factory(**kwargs):
        nonlocal stream
        stream = FakeInputStream(**kwargs)
        return stream

    service = AudioCaptureService(stream_factory=factory)
    service.start()

    stop_flag = threading.Event()
    errors = []

    def feeder():
        try:
            while not stop_flag.is_set():
                if stream:
                    stream.feed(160, value=0.1)
                time.sleep(0.001)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=feeder, daemon=True)
    thread.start()

    time.sleep(0.02)
    audio = service.stop()
    stop_flag.set()
    thread.join(timeout=1.0)

    assert not errors
    assert not service.is_recording
    if audio is not None:
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32
