import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication
from therion.voice.speech_output import SpeechOutput


@pytest.fixture
def service():
    app = QApplication.instance() or QApplication([])
    with patch('therion.voice.speech_output.QSoundEffect'):
        instance = SpeechOutput({})
        instance.sound.isPlaying.return_value = False
        yield instance
        instance.stop()


def test_cancelled_result_never_plays_and_deletes_audio(service):
    folder = Path(tempfile.mkdtemp(prefix='therion-tts-test-'))
    output = folder / 'speech.wav'
    output.write_bytes(b'old audio')
    token = service.generation
    service._pending = {'id': token, 'output': str(output)}
    service.folder = folder
    service.stop()
    service._message({'event':'audio', 'id':token})
    service.sound.play.assert_not_called()
    assert not folder.exists()


def test_warm_service_reuses_process_between_responses(service):
    service.is_ready = True
    service.process = MagicMock()
    service.speak('Olá, Marcus.')
    service.process.write.assert_called_once()
    assert service.state == 'synthesizing'
    process = service.process
    output = Path(service._pending['output'])
    output.write_bytes(b'audio')
    service._message({'event':'audio', 'id':service.generation, 'seconds':0.2})
    service.stop()
    service.speak('Como posso ajudar?')
    assert service.process is process
    assert process.write.call_count == 2
    service.release()


def test_failure_preserves_text_and_reports_error(service):
    errors = []
    service.failed.connect(errors.append)
    service.speak('x' * 2001)
    assert errors
    assert service.process is None
    service.sound.play.assert_not_called()


def test_clear_stops_playback_and_removes_temporary(service):
    folder = Path(tempfile.mkdtemp(prefix='therion-tts-test-'))
    (folder / 'speech.wav').write_bytes(b'audio')
    service.folder = folder
    service.stop()
    service.sound.stop.assert_called()
    assert not folder.exists()


def test_microphone_resume_waits_for_all_audio_parts(service):
    folder = Path(tempfile.mkdtemp(prefix='therion-tts-test-'))
    service.folder=folder
    service._pending={'output':str(folder/'speech.wav'),'id':service.generation}
    service._busy=True
    completed=[]
    service.completed.connect(lambda:completed.append(True))
    (folder/'speech.wav').write_bytes(b'first')
    service._message({'event':'audio','id':service.generation,'part':0,'last':False})
    (folder/'speech-1.wav').write_bytes(b'second')
    service._message({'event':'audio','id':service.generation,'part':1,'last':True})
    assert not completed
    service._playing=True
    service._playing_changed()
    assert not completed
    assert service.sound.play.call_count==2
    service._playing=True
    service._playing_changed()
    assert completed==[True]
    assert not folder.exists()


def test_approved_profile_is_forwarded_to_worker(service, tmp_path):
    for name in ('python.exe', 'kokoro-v1.0.onnx', 'voices-v1.0.bin'):
        (tmp_path / name).write_bytes(b'fixture')
    service.config = {'python_path': str(tmp_path / 'python.exe'), 'model_root': str(tmp_path),
                      'voice': 'alex_santa_c'}
    with patch('therion.voice.speech_output.QProcess') as factory:
        assert service.warmup() is True
        arguments = factory.return_value.setArguments.call_args.args[0]
        assert arguments[-2:] == ['--voice', 'alex_santa_c']
        factory.return_value.start.assert_called_once()
        service.release()


def queue_last_audio(service, tmp_path, duration=2.0):
    service.folder = tmp_path
    service._busy = True
    service._pending = {'output': str(tmp_path/'speech.wav'), 'id': service.generation}
    (tmp_path/'speech.wav').write_bytes(b'fixture')
    service._message({'event': 'audio', 'id': service.generation, 'last': True, 'audio_seconds': duration})


def test_player_never_starts_reports_failure_instead_of_hanging(service, tmp_path):
    errors = []; completed = []
    service.failed.connect(errors.append)
    service.completed.connect(lambda: completed.append(True))
    queue_last_audio(service, tmp_path)
    assert not service.timer.isActive() and service.playback_timer.isActive()
    assert service.playback_timer.interval() == 10000
    service._playback_timeout()
    assert errors and not completed and service.state == 'idle'
    assert service._active_audio is None and not service.playback_timer.isActive()
    assert not (tmp_path/'speech.wav').exists()


def test_player_missing_end_event_has_duration_bound_and_never_reports_success(service, tmp_path):
    errors = []; completed = []
    service.failed.connect(errors.append)
    service.completed.connect(lambda: completed.append(True))
    queue_last_audio(service, tmp_path, 3.5)
    service.sound.isPlaying.return_value = True
    service._playing_changed()
    assert service.playback_timer.interval() == 13500
    service._playback_timeout()
    assert errors and not completed and service.state == 'idle'


def test_normal_completion_disarms_player_watchdog_once(service, tmp_path):
    errors = []; completed = []
    service.failed.connect(errors.append)
    service.completed.connect(lambda: completed.append(True))
    queue_last_audio(service, tmp_path)
    service.sound.isPlaying.return_value = True
    service._playing_changed()
    service.sound.isPlaying.return_value = False
    service._playing_changed()
    service._playback_timeout()
    assert completed == [True] and not errors and not service.playback_timer.isActive()


def test_worker_exit_during_playback_reports_failure(service, tmp_path):
    errors = []; completed = []
    service.failed.connect(errors.append)
    service.completed.connect(lambda: completed.append(True))
    queue_last_audio(service, tmp_path)
    process = MagicMock(); service.process = process
    service._exited(process, 1)
    assert errors and not completed and service.state == 'idle'
    assert not service.playback_timer.isActive()


def test_watchdog_after_cancel_does_not_report_failure(service, tmp_path):
    errors = []; service.failed.connect(errors.append)
    queue_last_audio(service, tmp_path)
    service.stop()
    service._playback_timeout()
    assert not errors and service.state == 'idle'


def test_generation_failure_after_first_chunk_clears_playback_and_ignores_late_result(service, tmp_path):
    errors = []; completed = []
    service.failed.connect(errors.append)
    service.completed.connect(lambda: completed.append(True))
    service.config = {'provider': 'voicestudio'}
    service.folder = tmp_path
    token = service.generation
    service._pending = {'output': str(tmp_path/'speech.wav'), 'id': token}
    service._busy = True
    (tmp_path/'speech.wav').write_bytes(b'fixture')
    service._message({'event': 'audio', 'id': token, 'part': 0, 'last': False, 'audio_seconds': 1})
    assert service.playback_timer.isActive()
    service._message({'event': 'error', 'id': token, 'code': 'service_unavailable'})
    service._message({'event': 'audio', 'id': token, 'part': 1, 'last': True})
    assert len(errors) == 1 and not completed and service.state == 'idle'
    assert service._pending is None and not service.playback_timer.isActive()
    assert service.sound.play.call_count == 1


@pytest.mark.parametrize('duration', [float('nan'), float('inf'), -1, '3', True])
def test_invalid_duration_cannot_disable_watchdog(service, tmp_path, duration):
    queue_last_audio(service, tmp_path, duration)
    service.sound.isPlaying.return_value = True
    service._playing_changed()
    assert service.playback_timer.interval() == 130000
