"""Ativa/restaura somente os campos do teste, preservando outras configurações."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
from urllib.request import build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'tmp/parakeet-therion-20261020'
FIELDS=(('voice','provider'),('voice','endpoint'),('tts','voicestudio_endpoint'))
TARGET=('parakeet_http','http://127.0.0.1:3902/v1/audio/transcriptions','http://127.0.0.1:3902/v1/audio/speech')


def switch(mode,config,runtime=RUNTIME):
    runtime=Path(runtime)
    runtime.mkdir(parents=True,exist_ok=True)
    backup=runtime/'config-before-parakeet.json'
    before=config.read_bytes()
    data=json.loads(before.decode('utf-8-sig'))
    original=copy.deepcopy(data)
    if mode=='activate':
        if all(data.get(section,{}).get(key)==value for (section,key),value in zip(FIELDS,TARGET)):
            return {'status':'already_active'}
        if data.get('voice',{}).get('provider','whisper')!='whisper':raise ValueError('Provedor de entrada inesperado')
        if data.get('tts',{}).get('voicestudio_voice')!='120f734a':raise ValueError('Perfil de voz inesperado')
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:3902/health',timeout=4) as response:
            health=json.load(response)
        if health.get('status')!='ready' or health.get('model')!='parakeet':raise ValueError('Gateway não está pronto')
        with backup.open('xb') as output:output.write(before)
        for (section,key),value in zip(FIELDS,TARGET):data.setdefault(section,{})[key]=value
    else:
        saved=json.loads(backup.read_text(encoding='utf-8-sig'))
        for (section,key),value in zip(FIELDS,TARGET):
            if data.get(section,{}).get(key)!=value:raise ValueError('Campo foi alterado depois do teste; restauração bloqueada')
            if key in saved.get(section,{}):data[section][key]=saved[section][key]
            else:data[section].pop(key,None)
    assert data.get('ai')==original.get('ai')
    after=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    handle,temporary=tempfile.mkstemp(prefix='.parakeet.',dir=config.parent)
    try:
        with os.fdopen(handle,'wb') as output:output.write(after);output.flush();os.fsync(output.fileno())
        if config.read_bytes()!=before:raise RuntimeError('Configuração mudou durante a operação')
        os.replace(temporary,config)
    finally:Path(temporary).unlink(missing_ok=True)
    assert json.loads(config.read_text(encoding='utf-8'))==data
    result={'status':mode,'ai_unchanged':True,'fields':['.'.join(pair) for pair in FIELDS]}
    (runtime/(mode+'-result.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=('activate','restore'))
    parser.add_argument('--runtime',type=Path,default=RUNTIME)
    args=parser.parse_args()
    print(json.dumps(switch(args.mode,Path(os.environ['APPDATA'])/'Therion/config.json',args.runtime)))
