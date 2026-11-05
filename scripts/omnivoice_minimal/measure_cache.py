"""Mede cache e latencia com texto sintetico; sem microfone ou reproducao."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time
from urllib.request import build_opener, ProxyHandler, Request
import wave


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=('before','after'))
    args=parser.parse_args()
    folder=Path(__file__).resolve().parents[2]/'tmp/voice-cache-20261020'
    folder.mkdir(parents=True,exist_ok=True)
    config=Path(os.environ['APPDATA'])/'Therion/config.json'
    report={'phase':args.phase,'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
        'synthetic_only':True,'cases':[]}
    client=build_opener(ProxyHandler({}))
    with client.open('http://127.0.0.1:3901/health',timeout=3) as response:report['health_before']=json.load(response)
    text='Olá, Marcus. A transcrição e a voz estão prontas. Este é um teste de memória, mantendo a mesma voz e os mesmos parâmetros de geração.'
    for repeat in range(3):
        request=Request('http://127.0.0.1:3901/v1/audio/speech',data=json.dumps({
            'model':'tts-1','voice':'120f734a','input':text,'language':'pt','response_format':'wav'}).encode(),
            headers={'Content-Type':'application/json'})
        started=time.perf_counter()
        with client.open(request,timeout=90) as response:raw=response.read(12000001)
        seconds=time.perf_counter()-started
        with wave.open(io.BytesIO(raw)) as wav:
            assert wav.getnframes()>0 and wav.getframerate()==24000 and wav.getsampwidth()==2
            duration=wav.getnframes()/wav.getframerate()
        with client.open('http://127.0.0.1:3901/health',timeout=3) as response:health=json.load(response)
        row={'repeat':repeat,'http_seconds':round(seconds,4),'audio_seconds':round(duration,3),
            'seconds_per_audio_second':round(seconds/duration,4),**health['last_generation']}
        report['cases'].append(row)
        (folder/(args.phase+'-'+str(repeat)+'.wav')).write_bytes(raw)
        print(json.dumps(row),flush=True)
    (folder/(args.phase+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
