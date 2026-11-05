import numpy as np
from therion.voice.endpointing import SpeechEndpoint


def feed(detector, seconds, amplitude):
    for _ in range(round(seconds*10)):
        detector.feed(np.full(1600, amplitude, dtype=np.float32))


def test_silence_does_not_submit_a_turn():
    detector = SpeechEndpoint()
    feed(detector, 10, 0)
    assert not detector.complete
    assert detector.speech_seconds == 0


def test_pause_inside_sentence_waits_but_final_pause_ends():
    detector = SpeechEndpoint()
    feed(detector, 0.5, 0.02)
    feed(detector, 0.3, 0)
    assert not detector.complete
    feed(detector, 0.4, 0.02)
    feed(detector, 0.8, 0)
    assert detector.complete and detector.reason == 'silence'


def test_continuous_audio_has_a_memory_bound():
    detector = SpeechEndpoint(max_seconds=2)
    feed(detector, 2.1, 0.02)
    assert detector.complete and detector.reason == 'limit'
    elapsed = detector.elapsed
    feed(detector, 2, 0.02)
    assert detector.elapsed == elapsed


def test_short_click_noise_is_not_a_phrase():
    detector = SpeechEndpoint()
    feed(detector, 0.1, 0.1)
    feed(detector, 1, 0)
    assert not detector.complete


def test_wait_before_speaking_does_not_shorten_phrase_limit():
    detector=SpeechEndpoint(max_seconds=3)
    feed(detector,10,0)
    feed(detector,2,0.02)
    assert not detector.complete
    feed(detector,1.2,0.02)
    assert detector.complete and detector.reason=='limit'
