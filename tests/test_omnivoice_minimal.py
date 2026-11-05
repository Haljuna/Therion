"""Contrato do serviço isolado, sem carregar pesos ou tocar no perfil pessoal."""
import importlib.util
import io
import json
from pathlib import Path
import threading
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
import wave

import pytest

SPEC = importlib.util.spec_from_file_location('minimal_voice', Path(__file__).parents[1]/'scripts/omnivoice_minimal/server.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeEngine:
    profile = {'id': 'test_voice', 'name': 'Teste'}

    def __init__(self):
        self.gate = threading.Lock()
        self.ready, self.fail, self.calls = True, False, 0

    def status(self):
        return {'status': 'ready' if self.ready else 'loading'}

    def synthesize(self, text):
        self.calls += 1
        if self.fail:
            raise RuntimeError('synthetic_failure')
        target = io.BytesIO()
        with wave.open(target, 'wb') as audio:
            audio.setparams((1,2,24000,0,'NONE','not compressed'))
            audio.writeframes(b'\0\0'*2400)
        return target.getvalue(), {'generation_seconds': 0.01}


@pytest.fixture
def api():
    engine = FakeEngine()
    server = MODULE.Server(('127.0.0.1', 0), engine, 'test_shutdown_secret')
    runner = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
    runner.start()
    client = build_opener(ProxyHandler({}))

    def request(path, payload=None, headers=None):
        request = Request(f'http://127.0.0.1:{server.server_port}'+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with client.open(request, timeout=2) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.headers, error.read()
    request.port = server.server_port
    yield engine, request
    server.shutdown()
    server.server_close()
    runner.join(timeout=2)


def speech(**changes):
    return {'model': 'tts-1', 'voice': 'test_voice', 'input': 'Teste de áudio.',
            'language': 'pt', 'response_format': 'wav', **changes}


def test_saved_profile_and_actual_wav_contract(api):
    engine, request = api
    assert json.loads(request('/profiles/test_voice')[2])['id'] == 'test_voice'
    status, headers, content = request('/v1/audio/speech', speech())
    assert status == 200 and headers['Content-Type'] == 'audio/wav'
    with wave.open(io.BytesIO(content)) as audio:
        assert audio.getframerate() == 24000 and audio.getnframes() == 2400
    assert engine.calls == 1


@pytest.mark.parametrize('changes,expected', [({'voice':'alloy'},404),
    ({'response_format':'mp3'},422), ({'input':'x'*501},422),
    ({'input':' '},422), ({'speed':2},422)])
def test_rejects_voice_substitution_and_unsupported_requests(api, changes, expected):
    engine, request = api
    assert request('/v1/audio/speech', speech(**changes))[0] == expected
    assert engine.calls == 0


def test_busy_and_loading_do_not_queue_generation(api):
    engine, request = api
    engine.ready = False
    assert request('/health')[0] == 503
    assert request('/v1/audio/speech', speech())[0] == 503
    engine.ready = True
    with engine.gate:
        assert request('/v1/audio/speech', speech())[0] == 409
    assert engine.calls == 0


def test_no_automatic_retry_or_lock_leak_after_error(api):
    engine, request = api
    engine.fail = True
    assert request('/v1/audio/speech', speech())[0] == 500
    assert engine.calls == 1 and not engine.gate.locked()


def test_browser_origin_and_wrong_host_are_rejected(api):
    engine, request = api
    assert request('/v1/audio/speech', speech(), {'Origin':'https://example.com'})[0] == 403
    assert request('/health', headers={'Host':'example.com'})[0] == 403
    assert engine.calls == 0


def test_shutdown_requires_token_and_idle_engine(api):
    engine, request = api
    assert request('/shutdown', {})[0] == 403
    with engine.gate:
        assert request('/shutdown', {}, {'Authorization':'Bearer test_shutdown_secret'})[0] == 409


def test_current_therion_bridge_works_without_configuration_change(api, tmp_path):
    engine, request = api
    root = Path(__file__).parents[1]
    output = tmp_path/'control.wav'
    result = subprocess.run([sys.executable, str(root/'therion/voice/voicestudio_worker.py'),
        '--serve', '--endpoint', f'http://127.0.0.1:{request.port}/v1/audio/speech',
        '--voice', 'test_voice'], input=json.dumps({'id':1, 'text':'Teste de fala.',
        'output':str(output), 'stream':False})+'\n', capture_output=True, text=True, timeout=5)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0 and any(event['event'] == 'audio' for event in events)
    assert not any(event['event'] == 'error' for event in events)
    assert output.is_file() and engine.calls == 1


def test_changed_reference_is_rejected_before_loading_weights(tmp_path):
    source = tmp_path/'reference.wav'
    source.write_bytes(b'changed reference')
    engine = MODULE.Engine({'reference_path':str(source), 'reference_sha256':'incorrect'},
                           tmp_path, tmp_path, tmp_path)
    engine.load()
    assert engine.status()['status'] == 'error'
    assert engine.status()['failure_type'] == 'ValueError'
    assert engine.model is None


def test_cache_cleanup_preserves_encoded_audio_and_model(tmp_path):
    from types import SimpleNamespace
    engine = MODULE.Engine({},tmp_path,tmp_path,tmp_path)
    cache = {'reserved':2506*1024**2,'calls':0}
    def empty():
        cache.update(reserved=1960*1024**2,calls=cache['calls']+1)
    engine.torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=empty,
        memory_reserved=lambda:cache['reserved'], memory_allocated=lambda:1937*1024**2))
    model, prompt = object(), object()
    engine.model, engine.prompt = model, prompt
    engine._synthesize = lambda text:(b'unchanged WAV bytes',{'generation_seconds':1.2})
    raw,metrics = engine.synthesize('controle')
    assert raw==b'unchanged WAV bytes' and engine.model is model and engine.prompt is prompt
    assert cache['calls']==1 and metrics['cuda_released_mib']==546
    assert engine.status()['cuda_reserved_mib']==1960


def test_cache_cleanup_runs_on_generation_failure_without_retry(tmp_path):
    from types import SimpleNamespace
    engine = MODULE.Engine({},tmp_path,tmp_path,tmp_path)
    calls=[]
    engine.torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda:calls.append('cleanup'),
        memory_reserved=lambda:1960*1024**2, memory_allocated=lambda:1937*1024**2))
    def fail(text):calls.append('generate');raise RuntimeError('synthetic')
    engine._synthesize=fail
    with pytest.raises(RuntimeError,match='synthetic'):engine.synthesize('controle')
    assert calls==['generate','cleanup']
