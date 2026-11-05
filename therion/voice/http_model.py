"""Adaptador do Parakeet residente, sem carregar Whisper nem repetir requisições."""
import io
import json
from types import SimpleNamespace
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
import wave

import numpy as np

ENDPOINT='http://127.0.0.1:3902/v1/audio/transcriptions'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class HttpVoiceModel:
    def __init__(self,endpoint):
        if endpoint != ENDPOINT:raise ValueError('Endpoint do teste Parakeet inválido')
        self.endpoint=endpoint
        self.client=build_opener(ProxyHandler({}),NoRedirect())
        with self.client.open('http://127.0.0.1:3902/stt/health',timeout=3) as response:
            state=json.loads(response.read(65536))
        if state.get('status')!='ready' or state.get('model')!='parakeet':
            raise RuntimeError('Parakeet não está pronto no serviço local')

    def transcribe(self,audio,**options):
        data=np.asarray(audio)
        if (data.ndim!=1 or not 0<len(data)<=480000 or
                not np.isfinite(data).all() or options.get('language','pt')!='pt'):
            raise ValueError('Áudio inválido: esperado mono 16 kHz, até 30 segundos')
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setparams((1,2,16000,0,'NONE','not compressed'))
            wav.writeframes((np.clip(data,-1,1)*32767).astype('<i2').tobytes())
        raw=output.getvalue()
        body=(b'--therion\r\nContent-Disposition: form-data; name="model"\r\n\r\nparakeet\r\n'
            b'--therion\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            b'Content-Type: audio/wav\r\n\r\n'+raw+b'\r\n--therion--\r\n')
        request=Request(self.endpoint,data=body,headers={'Content-Type':'multipart/form-data; boundary=therion'})
        # Timeout é falha; não reenvia áudio nem usa outro modelo.
        with self.client.open(request,timeout=15) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Resposta de transcrição acima do limite')
        result=json.loads(raw)
        if (result.get('model')!='parakeet' or not isinstance(result.get('text'),str)
                or len(result['text'])>10000):raise ValueError('Resposta de transcrição inválida')
        if result.get('confidence_gate_passed') is False:
            from therion.voice.transcription import UnclearAudio
            raise UnclearAudio()
        # Sherpa não fornece métricas equivalentes ao Whisper; não inventar scores.
        # O pipeline mantém confirmação de ações, geração e descarte após cancelamento.
        text=result['text'].strip()
        return ([SimpleNamespace(text=text)] if text else []), SimpleNamespace(language='pt')
