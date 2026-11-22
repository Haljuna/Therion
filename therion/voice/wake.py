"""Lógica pura da palavra de ativação: portão de disparo e buffer circular.

O áudio do buffer vive só na memória; nada é gravado nem enviado antes do disparo.
"""
import time

import numpy as np


class WakeGate:
    """Dispara quando a nota passa do limiar, no máximo uma vez por `refractory` segundos."""

    def __init__(self, threshold=0.5, refractory=2.0, clock=time.monotonic):
        self.threshold = threshold
        self.refractory = refractory
        self.muted = False
        self._clock = clock
        self._last = None

    def feed(self, score: float) -> bool:
        if self.muted or score < self.threshold:
            return False
        now = self._clock()
        if self._last is not None and now - self._last < self.refractory:
            return False
        self._last = now
        return True


class RingBuffer:
    """Guarda os últimos `seconds` de áudio int16 mono, endereçados por amostras totais."""

    def __init__(self, seconds=3.0, rate=16000):
        self._data = np.zeros(int(seconds * rate), np.int16)
        self._total = 0

    def push(self, block: np.ndarray) -> None:
        cap = self._data.size
        self._total += block.size
        block = block[-cap:]  # bloco maior que o buffer: só o fim cabe
        n = block.size
        start = (self._total - n) % cap
        first = min(n, cap - start)
        self._data[start:start + first] = block[:first]
        self._data[:n - first] = block[first:]

    def mark(self) -> int:
        return self._total

    def since(self, mark: int) -> np.ndarray:
        cap = self._data.size
        if mark > self._total or self._total - mark > cap:
            return np.zeros(0, np.float32)
        idx = np.arange(mark, self._total) % cap
        return self._data[idx].astype(np.float32) / 32768
