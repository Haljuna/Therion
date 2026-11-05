"""Ownership e rearme são independentes da precisão acústica."""
import threading
from unittest.mock import Mock

from therion.voice.cycle import VoiceCycle
from therion.voice.pipeline import VoicePipeline


def test_cycle_blocks_capture_during_runtime_playback_and_drain():
    now=[0.0];cycle=VoiceCycle(lambda:now[0])
    assert cycle.can_capture
    cycle.runtime(True)
    assert cycle.state('idle')=='processing' and not cycle.can_capture
    cycle.playback(True);cycle.runtime(False)
    assert cycle.state('idle')=='speaking'
    cycle.playback(False)
    assert cycle.state('idle')=='rearming' and not cycle.can_capture
    now[0]=.61
    assert cycle.can_capture and cycle.state('idle')=='idle'


def test_pipeline_reserves_microphone_before_slow_start():
    entered=threading.Event();release=threading.Event();capture=Mock();transcription=Mock()
    def start():entered.set();release.wait(2);return True
    capture.start.side_effect=start
    pipeline=VoicePipeline(capture,transcription);results=[]
    first=threading.Thread(target=lambda:results.append(pipeline.start()))
    first.start();assert entered.wait(1)
    assert pipeline.start() is False
    release.set();first.join(timeout=2)
    assert results==[True] and capture.start.call_count==1
    pipeline.cancel()


def test_cancel_does_not_release_microphone_while_start_is_inflight():
    entered=threading.Event();release=threading.Event();capture=Mock();transcription=Mock()
    def start():entered.set();release.wait(2);return True
    capture.start.side_effect=start
    pipeline=VoicePipeline(capture,transcription);results=[]
    first=threading.Thread(target=lambda:results.append(pipeline.start()))
    first.start();assert entered.wait(1)
    pipeline.cancel()
    assert not pipeline.ready_to_capture and pipeline.start() is False
    release.set();first.join(timeout=2)
    assert results==[False] and pipeline.ready_to_capture
    pipeline.cancel()
