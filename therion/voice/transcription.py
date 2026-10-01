"""Serviço de transcrição local isolado."""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal


class VoiceTranscriptionService(QObject):
    """Executa transcrição via faster-whisper de forma assíncrona.

    Recebe o modelo já carregado, roda em background thread,
    impede concorrência e descarta resultados de gerações obsoletas.
    """

    transcribed = Signal(int, str)
    transcription_failed = Signal(int, str)

    LANGUAGE: str = "pt"
    BEAM_SIZE: int = 5
    VAD_FILTER: bool = True
    CONDITION_ON_PREVIOUS_TEXT: bool = False
    HOTWORDS: str = (
        "Obsidian, aliases, Segundo Cérebro, álgebra linear, "
        "circuitos lógicos, matrizes, determinantes, cancele"
    )

    def __init__(
        self,
        model: object,
        *,
        is_current_generation: Callable[[int], bool] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._is_current_generation = is_current_generation
        self._busy: bool = False
        self._active_generation: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def transcribe_async(self, audio: np.ndarray, generation: int) -> bool:
        """Inicia a transcrição em segundo plano.

        Retorna False se já houver uma transcrição em andamento.
        """
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self._active_generation = generation

        self._thread = threading.Thread(
            target=self._worker,
            args=(audio, generation),
            name="therion-voice-transcribe",
            daemon=True,
        )
        self._thread.start()
        return True

    def _worker(self, audio: np.ndarray, generation: int) -> None:
        try:
            segments, _info = self._model.transcribe(
                audio,
                language=self.LANGUAGE,
                beam_size=self.BEAM_SIZE,
                vad_filter=self.VAD_FILTER,
                condition_on_previous_text=self.CONDITION_ON_PREVIOUS_TEXT,
                hotwords=self.HOTWORDS,
            )
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
            error_message = None
        except Exception as exc:
            transcript = None
            error_message = str(exc)

        with self._lock:
            self._busy = False

        if not self._check_generation_valid(generation):
            return

        if error_message is not None:
            self.transcription_failed.emit(generation, error_message)
        else:
            self.transcribed.emit(generation, transcript)

    def _check_generation_valid(self, generation: int) -> bool:
        if self._is_current_generation is not None:
            return bool(self._is_current_generation(generation))
        with self._lock:
            return self._active_generation == generation
