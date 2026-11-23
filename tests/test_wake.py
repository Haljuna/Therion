import threading

import numpy as np

from therion.voice.wake import RingBuffer, WakeGate, WakeListener


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_fires_once_above_the_threshold_and_respects_two_seconds():
    clock = Clock(); gate = WakeGate(0.5, 2.0, clock)
    assert [gate.feed(s) for s in (.1, .6, .9)] == [False, True, False]
    clock.now = 1.9; assert gate.feed(.9) is False
    clock.now = 2.1; assert gate.feed(.9) is True


def test_a_muted_gate_never_fires():
    gate = WakeGate(); gate.muted = True; assert gate.feed(.99) is False


def test_ring_buffer_hands_over_only_the_audio_after_the_mark():
    ring = RingBuffer(seconds=1.0, rate=10)
    ring.push(np.full(4, 1000, np.int16)); mark = ring.mark(); ring.push(np.full(3, -1000, np.int16))
    assert np.allclose(ring.since(mark), -1000 / 32768)
    ring.push(np.zeros(20, np.int16)); assert ring.since(mark).size == 0   # já saiu do buffer


def test_ring_buffer_wraps_around_and_keeps_order():
    ring = RingBuffer(seconds=1.0, rate=10)
    ring.push(np.arange(1, 8, dtype=np.int16)); mark = ring.mark()
    ring.push(np.arange(8, 14, dtype=np.int16))   # passa do fim e volta ao começo
    assert np.allclose(ring.since(mark) * 32768, np.arange(8, 14))
    assert ring.since(-1).size == 0


def test_ring_buffer_oversize_push_keeps_only_the_tail():
    ring = RingBuffer(seconds=1.0, rate=10)
    mark = ring.mark(); ring.push(np.arange(25, dtype=np.int16))
    assert ring.since(mark).size == 0             # o começo não cabe: nada de pedaço parcial
    assert np.allclose(ring.since(ring.mark() - 10) * 32768, np.arange(15, 25))


class FakeStream:
    """Entrega os blocos assim que `start()` é chamado, como um microfone que já está falando."""

    def __init__(self, callback, blocks=()):
        self.callback, self.blocks = callback, blocks
        self.stopped = self.closed = False

    def start(self):
        for b in self.blocks:
            self.callback(b)

    def stop(self): self.stopped = True
    def close(self): self.closed = True


class FakeModel:
    def __init__(self, scores):
        self.scores, self.calls = list(scores), 0

    def predict(self, block):
        self.calls += 1
        return {'therion': self.scores.pop(0) if self.scores else 0.0}


def _blocks(n):
    return [np.full(1280, i + 1, np.int16) for i in range(n)]


def _model_file(tmp_path):
    f = tmp_path / 'therion.onnx'; f.write_bytes(b'x'); return str(f)


def test_listener_calls_back_with_the_audio_after_the_wake_word(tmp_path):
    got, done = [], threading.Event()
    def on_wake(audio, score): got.append((audio, score)); done.set()
    listener = WakeListener(
        _model_file(tmp_path), on_wake,
        model_factory=lambda p: FakeModel([0, 0, .9, 0, 0]),
        stream_factory=lambda cb: FakeStream(cb, _blocks(5)))
    assert listener.start() is True
    assert done.wait(3); listener.stop()
    assert len(got) == 1 and got[0][1] == .9
    assert np.allclose(got[0][0], np.concatenate([np.full(1280, 4), np.full(1280, 5)]) / 32768)


def test_paused_listener_feeds_nothing_to_the_model(tmp_path):
    model = FakeModel([])
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: model,
                            stream_factory=lambda cb: FakeStream(cb, _blocks(3)))
    listener.pause(); assert listener.start() is True
    threading.Event().wait(0.5); listener.stop()
    assert model.calls == 0


def test_missing_model_file_means_no_listener_and_no_error(tmp_path):
    assert WakeListener(str(tmp_path / 'nao.onnx'), lambda a, s: None).start() is False


def test_a_microphone_that_fails_to_open_is_reported_once_and_retried(tmp_path):
    opened, problems, ok = [], [], threading.Event()
    def factory(cb):
        opened.append(1)
        if len(opened) <= 3:
            raise OSError('sem microfone')
        ok.set(); return FakeStream(cb)
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: FakeModel([]),
                            stream_factory=factory, on_problem=problems.append, retry_seconds=0)
    assert listener.start() is True
    assert ok.wait(3); listener.stop()
    assert len(opened) == 4 and len(problems) == 1


def test_stop_is_safe_twice_and_joins_the_thread(tmp_path):
    streams = []
    def factory(cb): streams.append(FakeStream(cb)); return streams[-1]
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: FakeModel([]),
                            stream_factory=factory)
    assert listener.start() is True
    thread = listener._thread
    listener.stop(); listener.stop()
    assert not thread.is_alive() and streams[0].stopped and streams[0].closed


def test_a_silent_microphone_is_reported_as_microphone_and_reopened(tmp_path, monkeypatch):
    monkeypatch.setattr('therion.voice.wake.SILENCE_LIMIT', 0.3)
    opened, problems, ok = [], [], threading.Event()
    def factory(cb):
        opened.append(1)
        if len(opened) == 2:
            ok.set()
        return FakeStream(cb)
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: FakeModel([]),
                            stream_factory=factory, on_problem=problems.append, retry_seconds=0)
    assert listener.start() is True
    assert ok.wait(3); listener.stop()
    assert problems == ['microfone']


def test_a_detector_error_is_reported_once_and_the_stream_reopened(tmp_path):
    opened, problems, ok = [], [], threading.Event()
    class Boom(FakeModel):
        def predict(self, block):
            raise RuntimeError('modelo quebrou')
    def factory(cb):
        opened.append(1)
        if len(opened) == 2:
            ok.set()
        return FakeStream(cb, _blocks(1))
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: Boom([]),
                            stream_factory=factory, on_problem=problems.append, retry_seconds=0)
    assert listener.start() is True
    assert ok.wait(3); listener.stop()
    assert problems == ['detector']


def test_an_error_in_on_wake_keeps_the_stream_and_is_not_a_problem(tmp_path):
    opened, problems, called = [], [], threading.Event()
    def on_wake(audio, score):
        called.set(); raise ValueError('quem recebe errou')
    def factory(cb):
        opened.append(1); return FakeStream(cb, _blocks(5))
    listener = WakeListener(_model_file(tmp_path), on_wake, model_factory=lambda p: FakeModel([0, 0, .9, 0, 0]),
                            stream_factory=factory, on_problem=problems.append, retry_seconds=0)
    assert listener.start() is True
    assert called.wait(3); threading.Event().wait(0.5); listener.stop()
    assert len(opened) == 1 and problems == []


def test_a_full_queue_drops_blocks_instead_of_growing():
    import queue
    q = queue.Queue(38)
    for _ in range(1000):
        WakeListener._push(q, _blocks(1)[0])
    assert q.qsize() == 38


def test_start_after_stop_runs_again(tmp_path):
    listener = WakeListener(_model_file(tmp_path), lambda a, s: None, model_factory=lambda p: FakeModel([]),
                            stream_factory=lambda cb: FakeStream(cb))
    assert listener.start() is True; listener.stop()
    assert listener.start() is True
    assert listener._thread.is_alive(); listener.stop()


def test_a_stopped_thread_still_blocked_is_not_revived_by_a_new_start(tmp_path):
    release, entered, opened = threading.Event(), threading.Event(), []
    def on_wake(audio, score):
        entered.set(); release.wait(5)           # segura a thread antiga dentro do on_wake
    def factory(cb):
        opened.append(1); return FakeStream(cb, _blocks(5) if len(opened) == 1 else ())
    listener = WakeListener(_model_file(tmp_path), on_wake, model_factory=lambda p: FakeModel([0, 0, .9, 0, 0]),
                            stream_factory=factory, retry_seconds=0)
    assert listener.start() is True and entered.wait(3)
    old = listener._thread
    listener.stop()                              # junta só 2 s: a thread antiga continua presa
    assert old.is_alive()
    assert listener.start() is True
    release.set(); old.join(3)
    assert not old.is_alive()                    # terminou em vez de voltar ao laço
    threading.Event().wait(0.3)
    assert sum(t.name == 'wake-listener' and t.is_alive() for t in threading.enumerate()) == 1
    listener.stop()


def test_the_audio_after_the_name_keeps_growing_for_a_late_reader(tmp_path):
    got, done = [], threading.Event()
    def on_wake(audio, score): got.append(audio); done.set()
    listener = WakeListener(_model_file(tmp_path), on_wake, model_factory=lambda p: FakeModel([0, 0, .9]),
                            stream_factory=lambda cb: FakeStream(cb, _blocks(9)))
    assert listener.start() is True
    assert done.wait(3)
    threading.Event().wait(0.3); listener.stop()
    later = listener.since(listener.wake_mark)   # o que a captura lê depois de abrir o microfone
    assert len(got[0]) == 4 * 1280 and len(later) == 6 * 1280
    assert np.allclose(later[-1280:], 9 / 32768)


def test_a_mark_taken_later_hands_over_only_the_audio_from_there(tmp_path):
    got, done = [], threading.Event()
    def on_wake(audio, score): got.append(audio); done.set()
    listener = WakeListener(_model_file(tmp_path), on_wake, model_factory=lambda p: FakeModel([0, 0, .9]),
                            stream_factory=lambda cb: FakeStream(cb, _blocks(9)))
    assert listener.start() is True
    assert done.wait(3)
    threading.Event().wait(0.3); listener.stop()
    mark = listener.mark()   # 23/11: no barge-in a captura começa quando a fala parou, não no disparo
    assert listener.since(mark).size == 0 and mark - listener.wake_mark == 6 * 1280
