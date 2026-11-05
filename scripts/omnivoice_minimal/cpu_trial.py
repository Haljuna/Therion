"""Comparacao CPU isolada: mesmas vozes/parametros, sem mudar o Therion."""
import argparse
import hashlib
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
FOLDER=ROOT/'tmp/jarvis-cpu-20261020'
TEXTS=['Olá, Marcus. Estou pronto para ajudar.']*2+[
    'Olá, Marcus. A transcrição e a voz estão prontas. Este é um teste de memória, mantendo a mesma voz e os mesmos parâmetros de geração.']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('device',choices=('cpu','gpu'))
    args=parser.parse_args()
    FOLDER.mkdir(parents=True,exist_ok=True)
    config=Path(os.environ['APPDATA'])/'Therion/config.json'
    report={'device':args.device,'config_before':hashlib.sha256(config.read_bytes()).hexdigest(),
        'cases':[],'synthetic_only':True,'playback':False}
    def save():
        report['config_unchanged']=report['config_before']==hashlib.sha256(config.read_bytes()).hexdigest()
        (FOLDER/(args.device+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Bound native inference and guarantee the test process cannot remain resident.
    limit={'deadline':time.monotonic()+300}
    def watchdog():
        while True:
            if time.monotonic()>limit['deadline']:
                report.update(status='timeout',phase_timeout=report.get('phase'))
                save()
                os._exit(124)
            time.sleep(.5)
    threading.Thread(target=watchdog,daemon=True).start()
    try:
        client=build_opener(ProxyHandler({}))
        if args.device=='cpu':
            os.environ.update(CUDA_VISIBLE_DEVICES='-1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
            sys.path.insert(0,str(ROOT/'scripts/voice_gateway'))
            from asr import memory,process_memory
            report['memory_before']=memory()
            if report['memory_before']['available_commit_gib']<6:raise MemoryError('Margem inferior a 6 GiB')
            report['phase']='imports'
            save()
            started=time.perf_counter()
            source=Path('F:/VoiceStudio/runtime/project')
            sys.path.insert(0,str(source))
            import torch
            from omnivoice import OmniVoice
            from omnivoice.models.omnivoice import VoiceClonePrompt
            torch.set_num_threads(4)
            report['import_seconds']=round(time.perf_counter()-started,3)
            checkpoint=Path('F:/VoiceStudio/models/models--k2-fsa--OmniVoice/snapshots/c5fdb5ccb189668d56333f77ba2629f4cd7535f4')
            report['phase']='load_weights'
            save()
            started=time.perf_counter()
            model=OmniVoice.from_pretrained(str(checkpoint),device_map='cpu',dtype=torch.float32,
                load_asr=False,local_files_only=True,disable_mmap=True)
            model.eval()
            report['load_seconds']=round(time.perf_counter()-started,3)
            assert str(model.device)=='cpu' and not torch.cuda.is_initialized()
            profile=json.loads((ROOT/'tmp/omnivoice-minimal-20261020/profile.json').read_text(encoding='utf-8'))
            identity=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()+
                (source/'omnivoice/models/omnivoice.py').read_bytes()+str(checkpoint.resolve()).encode()).hexdigest()[:32]
            reference=ROOT/'tmp/omnivoice-minimal-20261020'/('reference-'+identity+'.pt')
            prompt=VoiceClonePrompt.load(str(reference))
            report.update(threads=4,dtype='float32',gpu_initialized=torch.cuda.is_initialized(),
                memory_after_load=process_memory(),available_after_load=memory())
            save()
        for repeat,text in enumerate(TEXTS):
            report['phase']='synthesis_'+str(repeat)
            limit['deadline']=time.monotonic()+120
            save()
            print(json.dumps({'phase':report['phase'],'device':args.device}),flush=True)
            started=time.perf_counter()
            if args.device=='gpu':
                payload={'model':'tts-1','voice':'120f734a','input':text,'language':'pt','response_format':'wav'}
                with client.open(Request('http://127.0.0.1:3901/v1/audio/speech',data=json.dumps(payload).encode(),
                    headers={'Content-Type':'application/json'}),timeout=90) as response:raw=response.read(12000001)
            else:
                if profile.get('seed') is not None:torch.manual_seed(profile['seed'])
                with torch.inference_mode():
                    audio=model.generate(text=text,language='pt',voice_clone_prompt=prompt,
                        instruct=profile.get('instruct') or None,num_step=16,guidance_scale=2.0,
                        speed=1.0,denoise=True,preprocess_prompt=True,postprocess_output=True)[0]
                audio=audio.detach().float().cpu().reshape(-1)
                assert audio.numel() and torch.isfinite(audio).all()
                pcm=(audio.clamp(-1,1)*32767).round().to(torch.int16).numpy().astype('<i2').tobytes()
                output=io.BytesIO()
                with wave.open(output,'wb') as wav:
                    wav.setparams((1,2,model.sampling_rate,0,'NONE','not compressed'))
                    wav.writeframes(pcm)
                raw=output.getvalue()
            elapsed=time.perf_counter()-started
            with wave.open(io.BytesIO(raw)) as wav:
                duration=wav.getnframes()/wav.getframerate()
                assert duration>0 and wav.getframerate()==24000 and wav.getsampwidth()==2
            row={'repeat':repeat,'generation_seconds':round(elapsed,3),'audio_seconds':round(duration,3),
                'real_time_factor':round(elapsed/duration,3)}
            if args.device=='cpu':row.update(memory=process_memory(),available=memory(),gpu_initialized=torch.cuda.is_initialized())
            else:
                with client.open('http://127.0.0.1:3901/health',timeout=3) as response:row['gpu_metrics']=json.load(response)['last_generation']
            (FOLDER/(args.device+'-'+str(repeat)+'.wav')).write_bytes(raw)
            report['cases'].append(row)
            save()
            print(json.dumps(row),flush=True)
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',failure_type=type(error).__name__,error=str(error)[:300])
        raise
    finally:save()


if __name__=='__main__':main()
