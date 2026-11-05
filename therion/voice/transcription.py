"""Serviço de transcrição local isolado."""

from __future__ import annotations

import threading
import math
import re
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal

MEMORY_EXHAUSTED = 'voice_memory_exhausted'
UNCLEAR_AUDIO = 'voice_unclear_audio'


class UnclearAudio(ValueError):
    """A captura não deve virar uma mensagem ou confirmação do usuário."""


def is_memory_failure(error: Exception) -> bool:
    return isinstance(error, MemoryError) or any(marker in str(error).casefold() for marker in (
        'mkl_malloc', 'failed to allocate memory', 'unable to allocate',
        'out of memory', 'std::bad_alloc',
    ))


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
    # "abre" evita que o comando de abrir aplicativo seja transcrito como "abril".
    # Saudações abrem o panorama; em 03/11 "Boa noite" saiu como "Banuichi".
    # "tarefa"/"conclua" evitam "Come a tarefa" no lugar de "Qual é a tarefa"/"Conclua a tarefa".
    HOTWORDS: str = "Therion, Obsidian, Segundo Cérebro, cancele, abre, Bom dia, Boa tarde, Boa noite, tarefa, conclua"
    # Ancora o modelo no português falado: em 03/11 "Boa noite" saiu como "Bandwitch" (inglês).
    INITIAL_PROMPT: str = "Conversa em português do Brasil com o assistente Therion."

    def __init__(
        self,
        model: object,
        *,
        is_current_generation: Callable[[int], bool] | None = None,
        vocabulary_provider: Callable[[], list[str]] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._is_current_generation = is_current_generation
        self._vocabulary_provider = vocabulary_provider
        self._busy: bool = False
        self._active_generation: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.fast_mode = False
        self._closing = False

    @property
    def is_quiescent(self):
        with self._lock:return not self._busy and (self._thread is None or not self._thread.is_alive())

    def shutdown(self):
        with self._lock:
            self._closing=True
            self._active_generation=None

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def transcribe_async(self, audio: np.ndarray, generation: int) -> bool:
        """Inicia a transcrição em segundo plano.

        Retorna False se já houver uma transcrição em andamento.
        """
        with self._lock:
            if self._closing or self._busy:
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
                # A conversa contínua mantém a mesma precisão da gravação manual.
                beam_size=self.BEAM_SIZE,
                temperature=0.0,
                vad_filter=self.VAD_FILTER,
                condition_on_previous_text=self.CONDITION_ON_PREVIOUS_TEXT,
                hotwords=self._hotwords(),
                initial_prompt=self.INITIAL_PROMPT,
            )
            texts = []
            for segment in segments:
                # Rejeitar a captura inteira: eliminar só um trecho poderia
                # apagar uma negação e transformar a frase em autorização.
                if not self._reliable(segment):
                    raise UnclearAudio()
                texts.append(segment.text.strip())
            transcript = " ".join(texts).strip()
            # Em silêncio o Whisper pode repetir o próprio prompt; isso não é fala do usuário.
            if transcript and transcript.rstrip('.').casefold() in self.INITIAL_PROMPT.rstrip('.').casefold():
                raise UnclearAudio()
            error_message = None
        except Exception as exc:
            transcript = None
            error_message = (UNCLEAR_AUDIO if isinstance(exc, UnclearAudio) else
                MEMORY_EXHAUSTED if is_memory_failure(exc) else str(exc))

        with self._lock:
            self._busy = False

        if not self._check_generation_valid(generation):
            return

        if error_message is not None:
            self.transcription_failed.emit(generation, error_message)
        else:
            self.transcribed.emit(generation, transcript)

    def _hotwords(self) -> str:
        words = self.HOTWORDS.split(', ')
        if self._vocabulary_provider is not None:
            try:
                candidates = self._vocabulary_provider()
                for name in candidates:
                    name = ' '.join(re.findall(r'[\wÀ-ÿ-]+', str(name)))[:80]
                    if name and name.casefold() not in {word.casefold() for word in words}:
                        if len(', '.join(words + [name])) > 512:
                            break
                        words.append(name)
            except (OSError, ValueError, TypeError):
                pass  # Falha do catálogo não substitui áudio nem concede acesso.
        return ', '.join(words)

    @staticmethod
    def _reliable(segment) -> bool:
        # Limiares do decoder; o faster-whisper pode devolver texto mesmo
        # quando a última tentativa não atende aos critérios de confiança.
        for field, threshold, above in (
            ('avg_logprob', -1.0, False),
            ('no_speech_prob', 0.6, True),
            ('compression_ratio', 2.4, True),
        ):
            value = getattr(segment, field, None)
            if value is None:
                continue  # Compatibilidade com adapters sem métricas.
            if not math.isfinite(value) or (value > threshold if above else value < threshold):
                return False
        return True

    def _check_generation_valid(self, generation: int) -> bool:
        with self._lock:
            if self._closing:return False
        if self._is_current_generation is not None:
            return bool(self._is_current_generation(generation))
        with self._lock:
            return self._active_generation == generation
