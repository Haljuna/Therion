"""Captura automática usa probabilidade de fala, não apenas energia ambiente."""
from unittest.mock import MagicMock
import numpy as np
import pytest
from therion.voice.activity import StreamingSpeechActivity
from therion.voice.capture import AudioCaptureService
from therion.voice.endpointing import SpeechEndpoint
from tests.test_voice_conversation import window, activate


def frame():
    return np.full(1600, .04, dtype=np.float32)


def test_noise_above_old_energy_threshold_does_not_extend_speech():
    activity=MagicMock(side_effect=[True]*5+[False]*10)
    endpoint=SpeechEndpoint(activity=activity)
    for _ in range(15):endpoint.feed(frame())
    assert endpoint.complete and endpoint.reason=='silence'
    assert endpoint.elapsed<1.5 and endpoint.speech_seconds==pytest.approx(.5)


def test_background_noise_alone_does_not_become_a_phrase():
    endpoint=SpeechEndpoint(activity=lambda samples:False)
    for _ in range(205):endpoint.feed(frame())
    assert endpoint.complete and endpoint.reason=='idle' and endpoint.speech_seconds==0


def test_detector_failure_is_terminal_and_does_not_fallback_to_energy():
    activity=MagicMock(side_effect=RuntimeError('falha fictícia'))
    endpoint=SpeechEndpoint(activity=activity);endpoint.feed(frame())
    assert endpoint.complete and endpoint.reason=='detector_error' and endpoint.speech_seconds==0


def test_streaming_frames_keep_per_capture_state_and_bounded_remainder():
    session=MagicMock()
    session.run.return_value=(np.array([[.9]],dtype=np.float32),np.ones((1,1,128),dtype=np.float32),np.ones((1,1,128),dtype=np.float32))
    detector=StreamingSpeechActivity(session)
    assert detector(np.ones(1600,dtype=np.float32)*.02)
    assert session.run.call_count==3 and len(detector.pending)==64
    assert session.run.call_args.args[1]['input'].shape==(1,576)
    fresh=StreamingSpeechActivity(session)
    assert not fresh.h.any() and not fresh.c.any() and not fresh.active


def test_automatic_capture_installs_speech_detector_and_manual_does_not():
    factory=MagicMock(return_value=lambda samples:False)
    stream=MagicMock()
    service=AudioCaptureService(stream_factory=lambda **kwargs:stream,activity_factory=factory)
    assert service.start(automatic=True)
    service._audio_callback(frame()[:,None],1600,None,None)
    assert not service.has_speech
    service.cancel();assert service.start()
    assert factory.call_count==1 and service._endpoint is None
    service.cancel()


def test_unavailable_vad_prevents_automatic_capture_but_keeps_manual_capture():
    factory=MagicMock(side_effect=RuntimeError('indisponível fictício'))
    stream_factory=MagicMock(return_value=MagicMock())
    service=AudioCaptureService(stream_factory=stream_factory,activity_factory=factory)
    assert not service.start(automatic=True) and not service.is_recording
    stream_factory.assert_not_called()
    assert service.start();service.cancel()


def test_detector_runtime_failure_ends_conversation_and_releases_capture(window):
    activate(window)
    endpoint=window._voice_pipeline._capture._endpoint
    endpoint.complete=True;endpoint.reason='detector_error'
    window._poll_conversation()
    assert not window._conversation_mode and not window._voice_pipeline._capture.is_recording
