"""Verifica o caminho integrado com audio sintetico, sem microfone ou reproducao."""
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
from PySide6.QtCore import Qt
from therion.voice.service import VoiceModelService
from therion.voice.transcription import VoiceTranscriptionService


def main():
    config=json.loads((Path(os.environ['APPDATA'])/'Therion/config.json').read_text(encoding='utf-8-sig'))
    voice=config['voice']
    model=VoiceModelService(voice.get('model_path'),provider=voice['provider'],endpoint=voice['endpoint'])
    assert model.load()
    model._thread.join(5)
    assert model.state=='ready'
    with wave.open(str(ROOT/'tmp/asr-comparison-20261020/plano.wav')) as wav:
        assert wav.getsampwidth()==2
        data=np.frombuffer(wav.readframes(wav.getnframes()),'<i2').astype(np.float32).reshape(-1,wav.getnchannels()).mean(axis=1)/32768
        rate=wav.getframerate()
    data=np.interp(np.arange(round(len(data)*16000/rate))*rate/16000,np.arange(len(data)),data).astype(np.float32)
    service=VoiceTranscriptionService(model.model)
    result={}
    ready=threading.Event()
    service.transcribed.connect(lambda generation,text:(result.update(text=text),ready.set()),Qt.DirectConnection)
    service.transcription_failed.connect(lambda generation,error:(result.update(error=error),ready.set()),Qt.DirectConnection)
    started=time.perf_counter()
    assert service.transcribe_async(data,1) and ready.wait(20)
    result['stt_seconds']=round(time.perf_counter()-started,3)
    assert 'engenharia econômica' in result.get('text','').casefold()
    result['whisper_imported']='faster_whisper' in sys.modules
    client=build_opener(ProxyHandler({}))
    def post(url,payload,timeout):
        with client.open(Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=timeout) as response:return response.read()
    started=time.perf_counter()
    response=json.loads(post(config['ai']['endpoint'],{'model':config['ai']['model'],'messages':[{'role':'user','content':'Responda em uma frase curta: olá!'}],
        'think':False,'stream':False,'keep_alive':'30m','options':{'num_ctx':8192,'num_predict':40}},60))
    result['ai_seconds']=round(time.perf_counter()-started,3)
    answer=response['message']['content'].strip()
    assert response['done'] and answer
    started=time.perf_counter()
    audio=post(config['tts']['voicestudio_endpoint'],{'model':'tts-1','voice':config['tts']['voicestudio_voice'],
        'input':answer,'language':'pt','response_format':'wav'},90)
    result['tts_seconds']=round(time.perf_counter()-started,3)
    with wave.open(io.BytesIO(audio)) as wav:
        result['audio_seconds']=round(wav.getnframes()/wav.getframerate(),3)
        assert wav.getnframes()>0
    result.update(status='passed',ai_model=config['ai']['model'],synthetic_only=True,playback=False)
    (ROOT/'tmp/parakeet-therion-20261020/integrated-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
