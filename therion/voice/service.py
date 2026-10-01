"""Serviço de carregamento do modelo de voz, em segundo plano."""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class VoiceModelService(QObject):
    """Carrega um modelo de voz sem bloquear a interface.

    O carregamento ocorre em thread daemon. Falhas não se propagam
    para quem chama ``load``; elas são comunicadas por ``load_failed``.
    """

    loaded = Signal(object)
    load_failed = Signal(str)
    state_changed = Signal(str)

    STATE_UNLOADED = "unloaded"
    STATE_LOADING = "loading"
    STATE_READY = "ready"
    STATE_ERROR = "error"

    def __init__(self, model_path, *, model_factory=None) -> None:
        super().__init__()
        self._model_path = model_path
        self._model_factory = model_factory
        self._state = self.STATE_UNLOADED
        self._model = None
        self._lock = threading.Lock()
        self._thread = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def model(self):
        return self._model

    def load(self) -> bool:
        """Inicia o carregamento. Retorna False se já houver um em andamento."""
        with self._lock:
            if self._state in (self.STATE_LOADING, self.STATE_READY):
                return False

            model_path = self._model_path
            if not model_path or not Path(model_path).is_dir():
                self._state = self.STATE_ERROR
                self._model = None
                error_msg = f"Caminho de modelo inválido: {model_path!r}"
            else:
                self._state = self.STATE_LOADING
                error_msg = None

        if error_msg is not None:
            self.state_changed.emit(self.STATE_ERROR)
            self.load_failed.emit(error_msg)
            return False

        self.state_changed.emit(self.STATE_LOADING)
        self._thread = threading.Thread(
            target=self._worker, name="therion-voice-load", daemon=True
        )
        self._thread.start()
        return True

    def _worker(self) -> None:
        try:
            factory = self._model_factory
            if factory is None:
                factory = self._default_factory
            instance = factory(str(self._model_path))
        except Exception as error:  # noqa: BLE001 - falha vira sinal, não exceção
            with self._lock:
                self._model = None
                self._state = self.STATE_ERROR
            self.state_changed.emit(self.STATE_ERROR)
            self.load_failed.emit(str(error))
            return

        with self._lock:
            self._model = instance
            self._state = self.STATE_READY
        self.state_changed.emit(self.STATE_READY)
        self.loaded.emit(instance)

    @staticmethod
    def _default_factory(path: str):
        from faster_whisper import WhisperModel

        return WhisperModel(path, device="cpu", compute_type="int8")
