"""Matriz local com STT/TTS residentes e áudio sintético, sem microfone/reprodução.

Usa servidor Ollama filho em porta própria. Não muda o perfil pessoal. Todos
os processos encerrados pertencem a este ensaio e são registrados na saída.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time


def resident_bytes(handle):
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
            ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
    row=Counters();row.cb=ctypes.sizeof(row)
    api=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    api.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if not api(int(handle),ctypes.byref(row),row.cb):return None
    return {'working_bytes':row.working,'private_bytes':row.private}


def resident_process(pid):
    kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return None
    try:return resident_bytes(handle)
    finally:
        kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tts-python',type=Path,required=True)
    parser.add_argument('--tts-root',type=Path,required=True)
    parser.add_argument('--stt-root',type=Path,required=True)
    parser.add_argument('--models-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fixture-root',type=Path,required=True)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--memory-efficient',action='store_true')
    parser.add_argument('--minimum-seconds',type=int,default=0,choices=range(0,7201))
    parser.add_argument('--models',nargs='+')
    parser.add_argument('--runtime-source',type=Path,help='Reusar fonte congelada para comparar candidatos sob o mesmo núcleo.')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    if args.output.exists():raise ValueError('Resultado já existe; escolha outro nome.')
    fixture=args.fixture_root.absolute();fixture.mkdir(parents=True,exist_ok=False)
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',11436))==0:raise ValueError('Porta experimental ocupada.')
    import httpx
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=5) as client:
        if client.get('http://127.0.0.1:11435/api/ps').json().get('models'):raise ValueError('Modelo pessoal carregado; não iniciei inferência concorrente.')
    source=fixture/'source';source.mkdir()
    runtime_source=args.runtime_source.resolve() if args.runtime_source else root
    files=[(path.relative_to(runtime_source),path) for path in [*list((runtime_source/'therion').rglob('*.py')),*list((runtime_source/'therion/voice/voices').glob('*.npy'))]]
    files.extend((path.relative_to(root),path) for path in [root/'scripts/evaluate-agent.py',root/'scripts/agent_resources.py',Path(__file__)])
    manifest={}
    for relative,path in files:
        target=source/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target);manifest[relative.as_posix()]=hashlib.sha256(target.read_bytes()).hexdigest()
    (source/'SOURCE-MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    sys.path.insert(0,str(source))
    environment=os.environ.copy()
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder=fixture/key;folder.mkdir();environment[key]=str(folder)
    environment.update(PYTHONIOENCODING='utf-8',PYTHONPATH=str(source),OLLAMA_HOST='127.0.0.1:11436',
        OLLAMA_MODELS=str(args.models_root),OLLAMA_FLASH_ATTENTION='1',OLLAMA_KV_CACHE_TYPE='q8_0',
        OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NO_CLOUD='1')
    # Bibliotecas dos filhos recebem o mesmo perfil temporário. O processo
    # supervisor só carrega STT, com arquivos de modelo já existentes.
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):os.environ[key]=environment[key]
    import tempfile
    tempfile.tempdir=None
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0);owned=[];streams=[];started=time.time();report={}
    events=queue.Queue();audio=fixture/'synthetic.wav';output=args.output.absolute();output.parent.mkdir(parents=True,exist_ok=True)
    def event(row):
        with output.with_suffix('.voice.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(dict(timestamp=time.time(),**row),ensure_ascii=False)+'\n')
    def launch(command,name,**options):
        log=(fixture/(name+'.log')).open('w',encoding='utf-8');streams.append(log)
        process=subprocess.Popen(command,env=environment,cwd=source,stderr=log,creationflags=flags,**options)
        owned.append((name,process));return process
    def receive(timeout):
        deadline=time.monotonic()+timeout
        while True:
            row=events.get(timeout=max(.01,deadline-time.monotonic()))
            if row is None:raise RuntimeError('TTS encerrou antes da resposta.')
            try:return json.loads(row)
            except ValueError:
                if time.monotonic()>=deadline:raise TimeoutError('TTS sem resposta estruturada.')
    try:
        from faster_whisper import WhisperModel
        before=time.perf_counter();stt=WhisperModel(str(args.stt_root),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,local_files_only=True)
        event({'event':'stt_ready','seconds':time.perf_counter()-before})
        tts=launch([str(args.tts_python),str(source/'therion/voice/kokoro_worker.py'),'--serve','--root',str(args.tts_root),'--voice','alex_santa_c']+(['--memory-efficient'] if args.memory_efficient else []),
            'tts',stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8')
        def read_tts():
            for line in tts.stdout:events.put(line)
            events.put(None)
        threading.Thread(target=read_tts,daemon=True).start()
        ready=receive(180)
        if ready.get('event')!='ready':raise RuntimeError('TTS não confirmou prontidão.')
        event(ready)
        def cycle(number):
            texts=['Olá. O projeto Aurora precisa de revisão. Prepare as próximas tarefas e aguarde minha confirmação.',
                'Não envie a mensagem. Prepare somente o rascunho e espere minha revisão.',
                'Consulte as notas do projeto Aurora e informe as fontes encontradas.']
            text=texts[number%len(texts)]
            tts.stdin.write(json.dumps({'id':str(number),'text':text,'output':str(audio),'stream':False})+'\n');tts.stdin.flush()
            result=receive(90)
            if result.get('event')!='audio':raise RuntimeError('Falha na síntese sintética.')
            # O aplicativo entrega PCM em memória ao STT. Não usar o leitor
            # opcional PyAV de arquivos para medir um caminho diferente.
            import wave
            import numpy as np
            with wave.open(str(audio),'rb') as stream:
                if stream.getnchannels()!=1 or stream.getsampwidth()!=2:raise ValueError('Fixture WAV precisa de PCM16 mono.')
                rate=stream.getframerate();pcm=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
            if rate!=16000:
                pcm=np.interp(np.arange(round(len(pcm)*16000/rate))*rate/16000,np.arange(len(pcm)),pcm).astype(np.float32)
            from therion.voice.transcription import VoiceTranscriptionService as Service
            before=time.perf_counter();segments,info=stt.transcribe(pcm,language=Service.LANGUAGE,beam_size=Service.BEAM_SIZE,
                temperature=0.0,vad_filter=Service.VAD_FILTER,condition_on_previous_text=Service.CONDITION_ON_PREVIOUS_TEXT,hotwords=Service.HOTWORDS)
            segments=list(segments);transcript=' '.join(segment.text for segment in segments)
            process=ctypes.WinDLL('kernel32').GetCurrentProcess;process.restype=ctypes.c_void_p
            event({'event':'voice_cycle','cycle':number,'tts':result,'stt_seconds':time.perf_counter()-before,
                'transcript':transcript,'reference':text,'reliable':all(Service._reliable(segment) for segment in segments),
                'voice':'alex_santa_c','input':'PCM16 mono, synthetic linear resampling to 16kHz','supervisor':resident_bytes(process()),'tts_process':resident_process(ready.get('pid',tts.pid))})
        cycle(0)
        soak_started=time.time()
        server=launch([shutil.which('ollama'),'serve'],'ollama',stdout=subprocess.DEVNULL)
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=2) as client:
            deadline=time.monotonic()+30
            while True:
                if server.poll() is not None:raise RuntimeError('Servidor experimental encerrou.')
                try:client.get('http://127.0.0.1:11436/api/version').raise_for_status();break
                except httpx.HTTPError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.2)
        log=output.with_suffix('.log').open('w',encoding='utf-8');streams.append(log)
        command=[sys.executable,str(source/'scripts/evaluate-agent.py'),'--endpoint','http://127.0.0.1:11436/api/chat',
            '--protocols','native','json','--release-on-pressure','--preflight-model-memory','--output',str(output)]
        if args.smoke:command+=['--per-group-limit','1','--repeats','1']
        if args.models:command+=['--models',*args.models]
        evaluation=launch(command,'evaluation',stdout=log)
        report={'started':started,'soak_started':soak_started,'minimum_seconds':args.minimum_seconds,'source':str(source),'voice':'alex_santa_c','memory_efficient':args.memory_efficient,'microphone':False,'playback':False,
            'pids':{name:process.pid for name,process in owned},'tts_worker_pid':ready.get('pid'),'environment':{key:environment[key] for key in environment if key.startswith('OLLAMA_')}}
        output.with_suffix('.voice-profile.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        number=0;next_cycle=time.monotonic()+60
        while evaluation.poll() is None or time.time()-soak_started<args.minimum_seconds:
            if evaluation.poll() not in (None,0) or (output.with_suffix('.stop').exists() and evaluation.poll() is not None):break
            if time.monotonic()>=next_cycle:
                number+=1;cycle(number);next_cycle=time.monotonic()+60
            time.sleep(.25)
        report['evaluation_exit']=evaluation.returncode
        if evaluation.returncode:raise RuntimeError('A matriz encerrou com erro; evidências preservadas.')
    finally:
        for name,process in reversed(owned):
            if process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=flags,timeout=15,check=False)
                process.wait(timeout=15)
            for stream in (process.stdin,process.stdout):
                if stream:stream.close()
        for stream in streams:stream.close()
        report.update(closed=time.time(),owned_processes_closed=all(process.poll() is not None for _,process in owned))
        output.with_suffix('.voice-closed.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
