"""Serviço de captura de áudio local isolado."""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np
import sounddevice as sd


class AudioCaptureService:
    """Captura áudio do microfone em memória via sounddevice.

    Opera exclusivamente em 16 kHz mono float32.
    Garante single-flight, cancelamento seguro e descarte de áudio curto.
    """

    SAMPLE_RATE: int = 16_000
    CHANNELS: int = 1
    DTYPE: str = "float32"
    MIN_DURATION_SECONDS: float = 0.2

    def __init__(
        self,
        *,
        stream_factory: Callable[..., sd.InputStream] | None = None,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        self._sample_rate = sample_rate
        self._stream_factory = stream_factory or self._default_stream_factory
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._recording: bool = False
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> bool:
        """Inicia a captura. Retorna False se já estiver gravando ou em caso de erro."""
        with self._lock:
            if self._recording:
                return False
            self._chunks.clear()

        try:
            stream = self._stream_factory(
                samplerate=self._sample_rate,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                callback=self._audio_callback,
            )
            stream.start()
        except Exception:
            self._cleanup_stream()
            with self._lock:
                self._recording = False
                self._chunks.clear()
            return False

        with self._lock:
            self._stream = stream
            self._recording = True
        return True

    def stop(self) -> np.ndarray | None:
        """Para a captura e retorna o áudio concatenado, ou None se curto demais/inválido."""
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            chunks = self._chunks
            self._chunks = []

        self._cleanup_stream()

        if not chunks:
            return None

        audio = np.concatenate(chunks)
        min_samples = int(self._sample_rate * self.MIN_DURATION_SECONDS)
        if len(audio) < min_samples:
            return None

        return audio

    def cancel(self) -> None:
        """Cancela a captura imediatamente e descarta qualquer buffer acumulado."""
        with self._lock:
            self._recording = False
            self._chunks.clear()

        self._cleanup_stream()

    def _cleanup_stream(self) -> None:
        """Fecha o stream ativo de forma segura e idempotente."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        with self._lock:
            if self._recording:
                self._chunks.append(indata[:, 0].copy())

    @staticmethod
    def _default_stream_factory(**kwargs) -> sd.InputStream:
        return sd.InputStream(**kwargs)
