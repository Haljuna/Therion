"""Serviço de captura de áudio local isolado."""

from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd
from therion.voice.endpointing import SpeechEndpoint
from therion.voice.activity import StreamingSpeechActivity


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
        activity_factory=None,
    ) -> None:
        self._sample_rate = sample_rate
        self._stream_factory = stream_factory or self._default_stream_factory
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._recording: bool = False
        self._level = 0.0
        self._lock = threading.Lock()
        self._endpoint = None
        self._last_frame_at = 0.0
        self._activity_factory = activity_factory or StreamingSpeechActivity
        self._held: list[np.ndarray] | None = None   # blocos ao vivo guardados até o áudio inicial tardio chegar

    @property
    def level(self) -> float:
        """Intensidade da captura já autorizada; nunca abre outro microfone."""
        with self._lock:
            return self._level if self._recording else 0.0

    @property
    def utterance_complete(self):
        with self._lock:
            return bool(self._endpoint and self._endpoint.complete)

    @property
    def endpoint_reason(self):
        with self._lock:
            return self._endpoint.reason if self._endpoint else None

    @property
    def has_speech(self):
        with self._lock:
            return bool(self._endpoint and self._endpoint.speech_seconds >= 0.2)

    @property
    def input_stalled(self):
        with self._lock:
            return self._recording and time.monotonic() - self._last_frame_at > 3

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self, *, automatic=False, preroll=None, no_speech_seconds: float | None = None) -> bool:
        """Inicia a captura. Retorna False se já estiver gravando ou em caso de erro.

        `preroll` é o áudio que vem antes do microfone: um array, ou uma função lida logo depois de o
        microfone abrir (o detector do nome segue ouvindo enquanto o dispositivo abre; assim nada se perde).
        """
        late = preroll if callable(preroll) else None
        if late is not None:
            preroll = None
        with self._lock:
            if self._recording:
                return False
            self._chunks.clear()
            self._level = 0.0
            self._endpoint = None
            self._last_frame_at = time.monotonic()
            self._recording = True
            self._held = [] if late is not None else None

        try:
            if automatic:
                if self._sample_rate != 16000:
                    raise ValueError('A detecção de fala automática requer 16 kHz.')
                endpoint = SpeechEndpoint(
                    self._sample_rate, activity=self._activity_factory(), no_speech_seconds=no_speech_seconds)
                if preroll is not None:
                    # Mesmo caminho dos blocos ao vivo, para a fala do áudio inicial contar.
                    for i in range(0, len(preroll), 1280):
                        endpoint.feed(preroll[i:i + 1280])
                with self._lock:
                    if not self._recording:
                        return False
                    self._endpoint = endpoint
            if preroll is not None and len(preroll):
                with self._lock:
                    self._chunks.append(np.asarray(preroll, dtype=np.float32).copy())
            stream = self._stream_factory(
                samplerate=self._sample_rate,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                callback=self._audio_callback,
            )
            self._stream = stream
            stream.start()
            if late is not None:
                self._take_late_preroll(late)
        except Exception:
            self._cleanup_stream()
            with self._lock:
                self._recording = False
                self._held = None
                self._chunks.clear()
            return False

        with self._lock:
            self._stream = stream
            self._recording = True
            # Abrir o dispositivo pode levar segundos; o silêncio só conta a partir daqui.
            self._last_frame_at = time.monotonic()
        return True

    def _take_late_preroll(self, late) -> None:
        audio = late()
        audio = np.zeros(0, np.float32) if audio is None else np.asarray(audio, dtype=np.float32)
        with self._lock:
            held, self._held = self._held or [], None
            if not self._recording:
                return
            # Um pouco de áudio repetido na emenda é melhor que um buraco no meio da frase.
            blocks = [audio[i:i + 1280] for i in range(0, len(audio), 1280)] + held
            for block in blocks:
                if self._endpoint is not None and not self._endpoint.complete:
                    self._endpoint.feed(block)
                self._chunks.append(block.copy())

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
                rms = float(np.sqrt(np.mean(indata[:, 0] ** 2))) if frames else 0.0
                self._level = min(1.0, max(0.0, (rms - 0.003) * 5)) if np.isfinite(rms) else 0.0
                self._last_frame_at = time.monotonic()
                if self._held is not None:   # o áudio inicial ainda vai entrar na frente
                    self._held.append(indata[:, 0].copy())
                    return
                if self._endpoint is not None:
                    if self._endpoint.complete:
                        return
                    self._endpoint.feed(indata[:, 0])
                self._chunks.append(indata[:, 0].copy())

    @staticmethod
    def _default_stream_factory(**kwargs) -> sd.InputStream:
        return sd.InputStream(**kwargs)
