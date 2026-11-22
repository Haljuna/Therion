import numpy as np

from therion.voice.wake import RingBuffer, WakeGate


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
