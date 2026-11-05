import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt

import therion.voice.http_model as module
from therion.voice.transcription import VoiceTranscriptionService
from therion.voice.service import VoiceModelService


class Client:
    def __init__(self,result=None,block=None):
        self.calls=[]
        self.result=result or {'model':'parakeet','text':'Não abra o Chrome.','confidence_gate_passed':None}
        self.block=block
    def open(self,request,timeout):
        self.calls.append(request)
        if isinstance(request,str):return io.BytesIO(b'{"status":"ready","model":"parakeet"}')
        if self.block:self.block.wait(3)
        return io.BytesIO(json.dumps(self.result).encode())


def make(monkeypatch,**kwargs):
    client=Client(**kwargs)
    monkeypatch.setattr(module,'build_opener',lambda *args:client)
    return module.HttpVoiceModel(module.ENDPOINT),client


def test_pcm_request_preserves_negation_without_fabricated_confidence(monkeypatch):
    model,client=make(monkeypatch)
    segments,info=model.transcribe(np.ones(16000,np.float32)*.1,language='pt')
    assert segments[0].text=='Não abra o Chrome.' and info.language=='pt'
    assert not hasattr(segments[0],'avg_logprob')
    assert b'RIFF' in client.calls[-1].data and b'parakeet' in client.calls[-1].data


def test_non_local_endpoint_rejected_before_network(monkeypatch):
    monkeypatch.setattr(module,'build_opener',lambda *args:pytest.fail('network'))
    with pytest.raises(ValueError):module.HttpVoiceModel('https://example.com/audio')


def test_wrong_model_and_unreliable_audio_fail(monkeypatch):
    model,_=make(monkeypatch,result={'model':'tiny','text':'algo'})
    with pytest.raises(ValueError):model.transcribe(np.ones(1600,np.float32))
    model,_=make(monkeypatch,result={'model':'parakeet','text':'abra','confidence_gate_passed':False})
    with pytest.raises(ValueError):model.transcribe(np.ones(1600,np.float32))


def test_timeout_is_not_retried(monkeypatch):
    model,client=make(monkeypatch)
    attempts=[]
    def fail(*args,**kwargs):attempts.append(1);raise TimeoutError()
    client.open=fail
    with pytest.raises(TimeoutError):model.transcribe(np.ones(1600,np.float32))
    assert attempts==[1]


def test_cancelled_generation_discards_response_and_allows_next_turn(monkeypatch):
    gate=threading.Event()
    model,_=make(monkeypatch,block=gate)
    current=[1]
    service=VoiceTranscriptionService(model,is_current_generation=lambda generation:generation==current[0])
    texts=[]
    service.transcribed.connect(lambda gen,text:texts.append((gen,text)),Qt.DirectConnection)
    assert service.transcribe_async(np.ones(1600,np.float32),1)
    current[0]=2
    gate.set()
    service._thread.join(3)
    assert texts==[] and not service.is_busy
    assert service.transcribe_async(np.ones(1600,np.float32),2)
    service._thread.join(3)
    assert texts==[(2,'Não abra o Chrome.')]


def test_http_service_does_not_require_local_model_directory(monkeypatch):
    model,_=make(monkeypatch)
    monkeypatch.setattr(module,'HttpVoiceModel',lambda endpoint:model)
    service=VoiceModelService(None,provider='parakeet_http',endpoint=module.ENDPOINT)
    assert service.load()
    service._thread.join(3)
    assert service.state=='ready' and service.model is model
