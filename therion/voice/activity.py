"""VAD local em fluxo usando o Silero já empacotado pelo faster-whisper."""
import numpy as np


class StreamingSpeechActivity:
    FRAME = 512

    def __init__(self, session=None):
        if session is None:
            from faster_whisper.vad import get_vad_model
            session = get_vad_model().session
        self.session = session
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(64, dtype=np.float32)
        self.pending = np.empty(0, dtype=np.float32)
        self.active = False

    def __call__(self, samples):
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not np.all(np.isfinite(samples)):
            raise ValueError('Áudio inválido para detecção de fala.')
        self.pending = np.concatenate((self.pending, samples))
        voiced = False
        processed = False
        while len(self.pending) >= self.FRAME:
            frame = self.pending[:self.FRAME]
            self.pending = self.pending[self.FRAME:]
            audio = np.concatenate((self.context, frame))[None, :]
            probability, self.h, self.c = self.session.run(None, {'input': audio, 'h': self.h, 'c': self.c})
            value = float(np.asarray(probability).reshape(-1)[0])
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Probabilidade de fala inválida.')
            self.active = value >= (0.35 if self.active else 0.55)
            voiced |= self.active
            processed = True
            self.context = frame[-64:].copy()
        return voiced if processed else self.active
