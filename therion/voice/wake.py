"""Lógica pura da palavra de ativação: portão de disparo e buffer circular.

O áudio do buffer vive só na memória; nada é gravado nem enviado antes do disparo.
"""
import os
import queue
import threading
import time
from typing import Callable

import numpy as np

RATE = 16000
BLOCK = 1280           # 80 ms, o que o openWakeWord espera
AFTER_WAKE_BLOCKS = 4  # ~300 ms de fala depois do nome antes de entregar o áudio
QUEUE_BLOCKS = 38      # ~3 s de blocos; se o detector atrasar, descarta o excedente
SILENCE_LIMIT = 5.0    # sem nenhum bloco do microfone por tanto tempo: reabre


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
        if mark < 0 or mark > self._total or self._total - mark > cap:
            return np.zeros(0, np.float32)
        idx = np.arange(mark, self._total) % cap
        return self._data[idx].astype(np.float32) / 32768


class _Silence(Exception):
    pass


def _default_model(model_path: str):
    import openwakeword
    # O openWakeWord procura melspectrogram/embedding dentro do pacote (resources/models),
    # que não existe aqui; apontar para a pasta do modelo evita qualquer download.
    folder = os.path.dirname(model_path)
    return openwakeword.Model(
        wakeword_models=[model_path], inference_framework='onnx',
        melspec_model_path=os.path.join(folder, 'melspectrogram.onnx'),
        embedding_model_path=os.path.join(folder, 'embedding_model.onnx'))


def _default_stream(callback):
    import sounddevice as sd
    return sd.InputStream(samplerate=RATE, channels=1, dtype='int16', blocksize=BLOCK,
                          callback=lambda indata, frames, t, status: callback(indata[:, 0].copy()))


class WakeListener:
    """Lê o microfone numa thread e chama `on_wake(áudio_depois_do_nome, score)` ao ouvir o nome.

    `stream_factory(callback)` devolve um stream com start/stop/close; o callback recebe
    um bloco int16 mono. `on_wake` roda na thread do detector; se ela levantar erro, só vai
    para o log. `on_problem` é chamado uma vez por tipo de falha por sessão do objeto.
    `start()` depois de `stop()` religa o detector (o `stop` é limpo no `start`).
    """

    def __init__(self, model_path: str, on_wake: Callable[[np.ndarray, float], None], *,
                 threshold=0.5, model_factory=None, stream_factory=None,
                 on_problem: Callable[[str], None] | None = None, retry_seconds=10.0):
        self._path = model_path
        self._on_wake = on_wake
        self._model_factory = model_factory or _default_model
        self._stream_factory = stream_factory or _default_stream
        self._on_problem = on_problem
        self._retry = retry_seconds
        self.gate = WakeGate(threshold)
        self._ring = RingBuffer(3.0, RATE)
        self._queue = queue.Queue(QUEUE_BLOCKS)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._reported: set[str] = set()

    def start(self) -> bool:
        if self._thread or not os.path.isfile(self._path):
            return False
        self._stop.clear()
        try:
            self._model = self._model_factory(self._path)
        except Exception:  # sem openwakeword ou modelo ilegível: o Therion segue sem o detector
            return False
        self._name = os.path.splitext(os.path.basename(self._path))[0]
        self._thread = threading.Thread(target=self._run, name='wake-listener', daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread:
            thread.join(2)

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def _push(self, block) -> None:
        try:
            self._queue.put_nowait(block)
        except queue.Full:  # detector atrasado: descarta em vez de crescer sem limite
            pass

    def _problem(self, kind: str) -> None:
        if kind not in self._reported:
            self._reported.add(kind)
            if self._on_problem:
                self._on_problem(kind)

    def _run(self) -> None:
        while not self._stop.is_set():
            stream = None
            try:
                self._queue = queue.Queue(QUEUE_BLOCKS)  # nada de blocos velhos do stream anterior
                stream = self._stream_factory(self._push)
                stream.start()
            except Exception:
                self._problem('microfone')
                if stream is not None:
                    self._close(stream)
                self._stop.wait(self._retry)
                continue
            try:
                self._loop()
            except _Silence:
                self._problem('microfone')
            except Exception:
                self._problem('detector')
            finally:
                self._close(stream)
            if not self._stop.is_set():
                self._stop.wait(self._retry)

    @staticmethod
    def _close(stream) -> None:
        for step in (stream.stop, stream.close):
            try:
                step()
            except Exception:
                pass

    def _loop(self) -> None:
        pending = None  # [mark, score, blocos que faltam]
        quiet = 0.0
        while not self._stop.is_set():
            try:
                block = self._queue.get(timeout=0.2)
            except queue.Empty:
                quiet += 0.2
                if pending:  # a fala parou antes dos 300 ms: entrega o que há
                    self._deliver(pending)
                    pending = None
                if quiet >= SILENCE_LIMIT:
                    raise _Silence()
                continue
            quiet = 0.0
            if self._paused.is_set():
                pending = None
                continue
            self._ring.push(block)
            score = self._model.predict(block).get(self._name, 0.0)
            if pending:
                pending[2] -= 1
                if pending[2] <= 0:
                    self._deliver(pending)
                    pending = None
            elif self.gate.feed(score):
                pending = [self._ring.mark(), score, AFTER_WAKE_BLOCKS]

    def _deliver(self, pending) -> None:
        try:
            self._on_wake(self._ring.since(pending[0]), pending[1])
        except Exception as exc:  # erro de quem recebe não é falha do microfone nem do detector
            print(f'[wake] on_wake falhou: {exc!r}')
