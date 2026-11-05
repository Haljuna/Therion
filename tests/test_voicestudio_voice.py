import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch
import wave
from urllib.error import HTTPError

import pytest
from PySide6.QtWidgets import QApplication
from therion.config.local import _validate_config
from therion.voice import voicestudio_worker as worker
from therion.voice.providers import VOICESTUDIO_ENDPOINT, is_voicestudio_endpoint
from therion.voice.speech_output import SpeechOutput


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 2400)
    return buffer.getvalue()


class Response(io.BytesIO):
    def __init__(self, data, kind='audio/wav'):
        super().__init__(data)
        self.headers = {'Content-Type': kind}


class Client:
    def __init__(self, audio=None, profile='120f734a', failure=None):
        self.audio = wav_bytes() if audio is None else audio
        self.profile = profile
        self.failure = failure
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        if request.get_method() == 'GET':
            return Response(json.dumps({'id': self.profile}).encode(), 'application/json')
        if self.failure:
            raise self.failure
        return Response(self.audio)


@pytest.mark.parametrize('endpoint', [
    'https://127.0.0.1:3900/v1/audio/speech', 'http://localhost:3900/v1/audio/speech',
    'http://example.com:3900/v1/audio/speech', 'http://127.0.0.1/v1/audio/speech',
    'http://user@127.0.0.1:3900/v1/audio/speech', VOICESTUDIO_ENDPOINT+'?remote=true',
    VOICESTUDIO_ENDPOINT+'#x', VOICESTUDIO_ENDPOINT+'\n',
])
def test_only_literal_local_api(endpoint):
    assert not is_voicestudio_endpoint(endpoint)


def test_loopback_and_no_redirect_or_proxy():
    assert is_voicestudio_endpoint(VOICESTUDIO_ENDPOINT)
    assert is_voicestudio_endpoint('http://[::1]:3900/v1/audio/speech')
    assert worker.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com') is None
    assert not any(getattr(handler, 'proxies', None) for handler in worker.local_client().handlers)


def request_for(tmp_path, text='Olá. O código é 42.'):
    return {'text': text, 'output': str(tmp_path/'speech.wav'), 'id': 7, 'stream': True}


def test_saved_profile_generates_pcm_preserving_text(tmp_path):
    client = Client()
    events = []
    request = request_for(tmp_path)
    worker.synthesize(request, VOICESTUDIO_ENDPOINT, '120f734a', events.append, client)
    payload = json.loads(client.calls[1].data)
    assert payload == {'model': 'tts-1', 'voice': '120f734a', 'input': request['text'], 'language': 'pt', 'response_format': 'wav'}
    assert client.calls[0].full_url.endswith('/profiles/120f734a')
    assert events[0]['id'] == 7 and events[0]['last'] and events[0]['audio_seconds'] == .1
    assert events[0]['request_seconds'] >= events[0]['profile_seconds']
    assert events[0]['http_seconds'] >= 0 and events[0]['wav_seconds'] >= 0
    with wave.open(request['output']) as audio:
        assert audio.getnframes() == 2400 and audio.getsampwidth() == 2


def test_missing_profile_never_posts_or_falls_back(tmp_path):
    client = Client(profile='other')
    with pytest.raises(worker.VoiceStudioError, match='profile_unavailable'):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, client)
    assert len(client.calls) == 1
    assert not (tmp_path/'speech.wav').exists()


@pytest.mark.parametrize('status', [404, 401, 403])
def test_profile_http_error_never_posts_or_falls_back(tmp_path, status):
    class Refused(Client):
        def open(self, request, timeout):
            self.calls.append(request)
            raise HTTPError(request.full_url, status, 'fixture', {}, io.BytesIO(b'private body'))
    client = Refused()
    expected = worker.VoiceStudioError if status == 404 else HTTPError
    with pytest.raises(expected):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, client)
    assert len(client.calls) == 1 and client.calls[0].get_method() == 'GET'
    assert not (tmp_path/'speech.wav').exists()


def test_timeout_is_not_retried(tmp_path):
    client = Client(failure=TimeoutError())
    with pytest.raises(TimeoutError):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, client)
    assert len(client.calls) == 2


def test_chunks_keep_order_and_all_text(tmp_path):
    text = 'Esta é uma frase de teste que deve preservar a ordem e os números 42. ' * 7
    client = Client()
    events = []
    worker.synthesize(request_for(tmp_path, text), VOICESTUDIO_ENDPOINT, '120f734a', events.append, client)
    assert ''.join(json.loads(call.data)['input'] for call in client.calls[1:]) == text
    assert len(events) > 1
    assert [event['part'] for event in events] == list(range(len(events)))
    assert [event['last'] for event in events] == [False] * (len(events)-1) + [True]


def test_size_limit_and_wrong_media_type_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'MAX_AUDIO_BYTES', 100)
    with pytest.raises(worker.VoiceStudioError, match='invalid_audio'):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, Client())
    class WrongMedia(Client):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            if request.get_method() == 'POST':
                response.headers['Content-Type'] = 'application/json'
            return response
    with pytest.raises(worker.VoiceStudioError, match='invalid_audio'):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, WrongMedia())
    assert not (tmp_path/'speech.wav').exists()


@pytest.mark.parametrize('audio', [b'not audio', wav_bytes()[:-10]])
def test_invalid_or_truncated_audio_never_published(tmp_path, audio):
    with pytest.raises(worker.VoiceStudioError, match='invalid_audio'):
        worker.synthesize(request_for(tmp_path), VOICESTUDIO_ENDPOINT, '120f734a', lambda event: None, Client(audio=audio))
    assert list(tmp_path.iterdir()) == []


def test_proposal_preserves_kokoro_and_other_settings(tmp_path):
    spec = importlib.util.spec_from_file_location('configure_voice', Path(__file__).resolve().parents[1]/'scripts/configure-voice.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    python = tmp_path/'python.exe'
    python.touch()
    original = {'other': {'keep': True}, 'tts': {'voice': 'alex_santa_c', 'python_path': 'original', 'model_root': 'original-models'}}
    result = module.proposal(original, 'voicestudio', str(python), voicestudio_voice='120f734a')
    assert result['other'] == original['other']
    assert result['tts']['voice'] == 'alex_santa_c' and result['tts']['python_path'] == 'original'
    assert result['tts']['model_root'] == 'original-models' and result['tts']['enabled']
    assert not result['tts']['online_allowed'] and not result['tts']['streaming_prepare']
    assert 'provider' not in original['tts']
    # Pré-síntese local é opcional e explícita; a validação a preserva.
    streaming = module.proposal(original, 'voicestudio', str(python), voicestudio_voice='120f734a', streaming_prepare=True)
    assert _validate_config({'tts': streaming['tts']})['tts']['streaming_prepare'] is True
    invalid = dict(result['tts'], voicestudio_endpoint='http://remote:3900/v1/audio/speech')
    assert not _validate_config({'tts': invalid})['tts']['enabled']
    with pytest.raises(ValueError):
        module.proposal(original, 'voicestudio', str(python))


def test_qt_uses_local_worker_and_ignores_audio_after_cancel(tmp_path):
    qt = QApplication.instance() or QApplication([])
    python = tmp_path/'python.exe'
    python.touch()
    config = {'provider': 'voicestudio', 'voicestudio_python_path': str(python),
              'voicestudio_endpoint': VOICESTUDIO_ENDPOINT, 'voicestudio_voice': '120f734a'}
    with patch('therion.voice.speech_output.QSoundEffect'), patch('therion.voice.speech_output.QProcess') as factory:
        service = SpeechOutput(config)
        try:
            assert service.warmup()
            args = factory.return_value.setArguments.call_args.args[0]
            assert Path(args[0]).name == 'voicestudio_worker.py' and '--root' not in args
            assert args[-1] == '120f734a'
            service.is_ready = True
            service.speak('Teste fictício.')
            old_id = service.generation
            service.stop()
            service._message({'event': 'audio', 'id': old_id, 'last': True})
            service.sound.play.assert_not_called()
            assert service._pending is None
        finally:
            service.shutdown()
            service.deleteLater()
            qt.processEvents()
