import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import build_opener,ProxyHandler,Request
import wave

import pytest

FOLDER=Path(__file__).parents[1]/'scripts/voice_gateway'
sys.path.insert(0,str(FOLDER))
SPEC=importlib.util.spec_from_file_location('voice_gateway_server',FOLDER/'server.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def wav():
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(b'\0\0'*1600)
    return output.getvalue()


def multipart(audio,model='whisper-1'):
    return (b'--control\r\nContent-Disposition: form-data; name="model"\r\n\r\n'+model.encode()+
        b'\r\n--control\r\nContent-Disposition: form-data; name="file"; filename="ignored.wav"\r\n'+
        b'Content-Type: audio/wav\r\n\r\n'+audio+b'\r\n--control--\r\n')


class FakeRecognizer:
    def __init__(self):self.calls=0
    def transcribe(self,audio):
        self.calls+=1
        return {'text':'Nao apague a nota.','model':'tiny'}


class FakeState:
    def __init__(self):
        self.model,self.status,self.lock,self.recognizer='tiny','ready',threading.Lock(),FakeRecognizer()
    def snapshot(self):return {'status':self.status,'model':self.model}


@pytest.fixture
def api():
    state=FakeState()
    server=MODULE.Gateway(('127.0.0.1',0),state,'control-secret')
    def relay(path,raw=None):
        if path=='/health':return 'application/json',b'{"status":"ready"}'
        if path.startswith('/profiles/'):return 'application/json',b'{"id":"120f734a","name":"jarvis"}'
        return 'audio/wav',wav()
    server.relay=relay
    runner=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
    runner.start()
    client=build_opener(ProxyHandler({}))
    def request(path,body=None,kind='multipart/form-data; boundary=control',headers=None):
        request=Request(f'http://127.0.0.1:{server.server_port}'+path,data=body,
                        headers={'Content-Type':kind,**(headers or {})})
        try:
            with client.open(request,timeout=2) as response:return response.status,response.read()
        except HTTPError as error:
            with error:return error.code,error.read()
    yield state,request
    server.shutdown();server.server_close();runner.join(timeout=2)


def test_transcription_preserves_raw_audio_and_returns_text_without_execution(api):
    state,request=api
    raw=wav()
    assert MODULE.parse_audio('multipart/form-data; boundary=control',multipart(raw),'tiny')==raw
    status,body=request('/v1/audio/transcriptions',multipart(raw))
    assert status==200 and json.loads(body)['text']=='Nao apague a nota.'
    assert state.recognizer.calls==1


@pytest.mark.parametrize('audio,model',[(b'not WAV','whisper-1'),(wav(),'another-model')])
def test_invalid_audio_or_model_is_rejected_before_decode(api,audio,model):
    state,request=api
    assert request('/v1/audio/transcriptions',multipart(audio,model))[0]==422
    assert state.recognizer.calls==0


def test_busy_and_loading_are_explicit_without_queue(api):
    state,request=api
    with state.lock:assert request('/v1/audio/transcriptions',multipart(wav()))[0]==409
    state.status='loading'
    assert request('/stt/health')[0]==503
    assert request('/v1/audio/transcriptions',multipart(wav()))[0]==503
    assert state.recognizer.calls==0


def test_saved_voice_and_wav_relay_contract(api):
    _,request=api
    assert json.loads(request('/profiles/120f734a')[1])['id']=='120f734a'
    body=json.dumps({'model':'tts-1','voice':'120f734a','input':'Controle.','response_format':'wav'}).encode()
    status,raw=request('/v1/audio/speech',body,'application/json')
    assert status==200 and raw[:4]==b'RIFF'
    body=json.dumps({'voice':'alloy'}).encode()
    assert request('/v1/audio/speech',body,'application/json')[0]==404


def test_browser_and_unauthorized_shutdown_rejected(api):
    state,request=api
    assert request('/v1/audio/transcriptions',multipart(wav()),headers={'Origin':'https://example.com'})[0]==403
    assert request('/shutdown',b'{}','application/json')[0]==403
    assert state.recognizer.calls==0
