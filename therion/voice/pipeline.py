"""Pipeline de coordenação entre captura e transcrição de voz."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    import numpy as np
    from therion.voice.capture import AudioCaptureService
    from therion.voice.transcription import VoiceTranscriptionService


class VoicePipeline(QObject):
    """Coordena o fluxo de push-to-talk: captura -> parada -> transcrição.

    Gerencia o ciclo de vida via generations, garante single-flight
    e descarta resultados ou erros se a operação for cancelada.
    """

    STATE_IDLE = "idle"
    STATE_RECORDING = "recording"
    STATE_TRANSCRIBING = "transcribing"

    transcribed = Signal(int, str)
    transcription_failed = Signal(int, str)
    state_changed = Signal(str)

    def __init__(
        self,
        capture_service: AudioCaptureService,
        transcription_service: VoiceTranscriptionService,
    ) -> None:
        super().__init__()
        self._capture = capture_service
        self._transcription = transcription_service
        self._state = self.STATE_IDLE
        self._generation = 0
        self._lock = threading.Lock()

        # Vincula a checagem de geração da transcrição a este pipeline
        self._transcription._is_current_generation = self.is_current_generation

        self._transcription.transcribed.connect(self._on_transcribed)
        self._transcription.transcription_failed.connect(self._on_transcription_failed)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def is_current_generation(self, generation: int) -> bool:
        with self._lock:
            return self._generation == generation

    def start(self) -> bool:
        """Inicia a captura de áudio com uma nova generation.

        Retorna False se o pipeline não estiver ocioso (idle) ou se a captura falhar.
        """
        with self._lock:
            if self._state != self.STATE_IDLE:
                return False
            self._generation += 1
            gen = self._generation

        success = self._capture.start()
        if not success:
            with self._lock:
                if self._generation == gen:
                    self._state = self.STATE_IDLE
            return False

        with self._lock:
            if self._generation != gen:
                self._capture.cancel()
                return False
            self._state = self.STATE_RECORDING

        self.state_changed.emit(self.STATE_RECORDING)
        return True

    def stop(self) -> bool:
        """Para a gravação e envia o áudio para transcrição.

        Retorna False se não estiver gravando, se o áudio for inválido/curto,
        ou se o disparo da transcrição falhar.
        """
        with self._lock:
            if self._state != self.STATE_RECORDING:
                return False
            gen = self._generation

        audio = self._capture.stop()
        if audio is None or len(audio) == 0:
            with self._lock:
                if self._generation == gen:
                    self._state = self.STATE_IDLE
            self.state_changed.emit(self.STATE_IDLE)
            return False

        with self._lock:
            if self._generation != gen:
                return False
            self._state = self.STATE_TRANSCRIBING

        self.state_changed.emit(self.STATE_TRANSCRIBING)

        dispatched = self._transcription.transcribe_async(audio, gen)
        if not dispatched:
            with self._lock:
                if self._generation == gen:
                    self._state = self.STATE_IDLE
            self.state_changed.emit(self.STATE_IDLE)
            return False

        return True

    def cancel(self) -> None:
        """Cancela a operação atual, invalidando a generation e parando a captura."""
        with self._lock:
            old_state = self._state
            self._generation += 1
            self._state = self.STATE_IDLE

        self._capture.cancel()
        if old_state != self.STATE_IDLE:
            self.state_changed.emit(self.STATE_IDLE)

    def _on_transcribed(self, generation: int, text: str) -> None:
        with self._lock:
            if generation != self._generation or self._state != self.STATE_TRANSCRIBING:
                return
            self._state = self.STATE_IDLE

        self.state_changed.emit(self.STATE_IDLE)
        self.transcribed.emit(generation, text)

    def _on_transcription_failed(self, generation: int, error_message: str) -> None:
        with self._lock:
            if generation != self._generation or self._state != self.STATE_TRANSCRIBING:
                return
            self._state = self.STATE_IDLE

        self.state_changed.emit(self.STATE_IDLE)
        self.transcription_failed.emit(generation, error_message)
