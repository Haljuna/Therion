"""Compara alocação ORT sem trocar modelo, perfil, texto ou reproduzir áudio."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from importlib.util import spec_from_file_location,module_from_spec
spec=spec_from_file_location('voice_probe',Path(__file__).with_name('evaluate-agent-voice.py'))
probe=module_from_spec(spec);spec.loader.exec_module(probe)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--python',type=Path,required=True);parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--fixture-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    if args.output.exists():raise ValueError('Saída já existe.')
    fixture=args.fixture_root.absolute();fixture.mkdir(parents=True,exist_ok=False)
    environment=os.environ.copy()
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder=fixture/key;folder.mkdir();environment[key]=str(folder)
    text='Olá. O projeto Aurora precisa de revisão. Prepare as próximas tarefas e aguarde minha confirmação.'
    report={'voice':'alex_santa_c','reference':text,'microphone':False,'playback':False,'profiles':{}}
    for efficient in (False,True):
        name='memory_efficient' if efficient else 'original';events=queue.Queue();log=(fixture/(name+'.log')).open('w',encoding='utf-8')
        command=[str(args.python),str(root/'therion/voice/kokoro_worker.py'),'--serve','--root',str(args.model_root),'--voice','alex_santa_c']
        if efficient:command.append('--memory-efficient')
        process=subprocess.Popen(command,env=dict(environment,PYTHONIOENCODING='utf-8'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,
            text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        def reader(stream=process.stdout,output=events):
            for line in stream:output.put(line)
            output.put(None)
        threading.Thread(target=reader,daemon=True).start()
        def receive(timeout):
            row=events.get(timeout=timeout)
            if row is None:raise RuntimeError('Worker encerrou.')
            return json.loads(row)
        try:
            ready=receive(180)
            if ready.get('event')!='ready':raise RuntimeError('Prontidão não confirmada.')
            samples=[]
            for index in range(8):
                output=fixture/(name+'.wav');process.stdin.write(json.dumps({'id':str(index),'text':text,'output':str(output)})+'\n');process.stdin.flush()
                row=receive(90)
                if row.get('event')!='audio':raise RuntimeError('Síntese não confirmada.')
                row['memory']=probe.resident_process(ready['pid']);row['sha256']=hashlib.sha256(output.read_bytes()).hexdigest();samples.append(row)
            report['profiles'][name]={'ready':ready,'samples':samples}
        finally:
            if process.poll() is None:
                process.stdin.close()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15,check=False);process.wait(timeout=10)
            for stream in (process.stdin,process.stdout):
                if stream and not stream.closed:stream.close()
            log.close()
    report['audio_identical']=len({row['sha256'] for value in report['profiles'].values() for row in value['samples']})==1
    report['unique_hashes_per_profile']={name:len({row['sha256'] for row in value['samples']}) for name,value in report['profiles'].items()}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'audio_identical':report['audio_identical'],**{name:{'last_memory':value['samples'][-1]['memory'],'last_seconds':value['samples'][-1]['seconds']} for name,value in report['profiles'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
