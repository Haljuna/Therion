"""Avaliação opcional com frases fictícias; não captura nem reproduz áudio."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
import wave

ROOT=Path(__file__).resolve().parents[1]
TEXTS=('Olá. Esta é uma amostra fictícia de voz do Therion.',
       'A reunião fictícia começa às 14:30. O código é 42.',
       'Não envie a mensagem. Apenas revise o relatório.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True,type=Path)
    parser.add_argument('--state-root',required=True,type=Path)
    parser.add_argument('--allow-online',action='store_true')
    parser.add_argument('--voice',choices=('pt-BR-AntonioNeural','pt-BR-FranciscaNeural'),default='pt-BR-AntonioNeural')
    args=parser.parse_args()
    if not args.allow_online:parser.error('A avaliação envia somente as três frases fictícias à Microsoft. Use --allow-online para executá-la.')
    python=args.python.resolve(strict=True)
    state=args.state_root.resolve()/('edge-eval-'+uuid.uuid4().hex);state.mkdir(parents=True)
    env=dict(os.environ)
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        path=state/key;path.mkdir();env[key]=str(path)
    worker=ROOT/'therion/voice/edge_worker.py'
    report={'started_at':datetime.now(timezone.utc).isoformat(),'state_root':str(state),
        'voice':args.voice,'worker_sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),
        'personal_data_used':False,'microphone_used':False,'playback_used':False,'samples':[]}
    messages=queue.Queue();process=None;errors=None
    try:
        errors=(state/'worker.stderr.log').open('w',encoding='utf-8')
        started=time.monotonic()
        process=subprocess.Popen([str(python),str(worker),'--serve','--allow-online','--voice',args.voice],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        def read():
            for line in process.stdout:
                try:messages.put((time.monotonic(),json.loads(line)))
                except ValueError:messages.put((time.monotonic(),{'event':'invalid_protocol'}))
        thread=threading.Thread(target=read,daemon=True);thread.start()
        received,ready=messages.get(timeout=20)
        if ready.get('event')!='ready':raise RuntimeError('Dependências ou autorização indisponíveis.')
        report['startup_seconds']=round(received-started,3)
        for index,text in enumerate(TEXTS):
            output=state/f'sample-{index}.wav'
            request={'id':index,'text':text,'output':str(output),'stream':True}
            sent=time.monotonic();process.stdin.write(json.dumps(request)+'\n');process.stdin.flush()
            first_audio=None;parts=[]
            while True:
                received,event=messages.get(timeout=45)
                if event.get('event')!='audio' or event.get('id')!=index:
                    report['provider_error']={key:event[key] for key in ('code','failure_type') if key in event}
                    raise RuntimeError('Síntese online indisponível; não usei outro serviço.')
                if first_audio is None:first_audio=received
                part=event.get('part',0)
                path=output if part==0 else output.with_name(f'{output.stem}-{part}{output.suffix}')
                with wave.open(str(path)) as audio:
                    if audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=24000 or audio.getnframes()<=0:
                        raise RuntimeError('Áudio não passou na verificação do formato.')
                    duration=audio.getnframes()/audio.getframerate()
                parts.append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'audio_seconds':round(duration,3)})
                if event.get('last') is True:break
            report['samples'].append({'text':text,'first_audio_seconds':round(first_audio-sent,3),
                'total_seconds':round(received-sent,3),'parts':parts})
        report['status']='completed'
    except Exception as error:
        report.update(status='unavailable',error_type=type(error).__name__,
            message='Avaliação online não concluiu. Nenhum serviço pago, conta pessoal ou fallback foi usado.')
    finally:
        if process is not None:
            try:
                if process.stdin:process.stdin.close()
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
            if process.stdout:process.stdout.close()
            report['worker_exit_code']=process.returncode
        if errors:errors.close()
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        path=state/'evaluation.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'report':str(path),'status':report['status'],'samples':len(report['samples'])},ensure_ascii=False),flush=True)
    return 0 if report['status']=='completed' else 1


if __name__=='__main__':sys.exit(main())
