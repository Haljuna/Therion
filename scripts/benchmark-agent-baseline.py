"""Mede rotas legadas em fontes fictícias e AppData separado, sem inferência/voz."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def percentile(values):
    return sorted(values)[math.ceil(len(values)*.95)-1]


def child(args):
    started=time.perf_counter()
    state=Path(args.state).absolute();state.mkdir(parents=True,exist_ok=False)
    for variable,name in [('APPDATA','roaming'),('LOCALAPPDATA','local'),('TEMP','temp'),('TMP','temp')]:
        folder=state/name;folder.mkdir(exist_ok=True);os.environ[variable]=str(folder)
    source=Path(args.source).resolve();sys.path.insert(0,str(source))
    from therion.core.orchestrator import Orchestrator
    imported=time.perf_counter()-started
    vault=state/'vault';notes=vault/'10 - Projetos'/'Therion';notes.mkdir(parents=True)
    for index in range(300):(notes/f'Aurora-{index:03d}.md').write_text(f'Aurora: informação fictícia PONTE-42, item {index}.',encoding='utf-8')
    started=time.perf_counter()
    host=Orchestrator(simulate=True,vault_root=str(vault),log_dir=str(state/'logs'))
    construction=time.perf_counter()-started
    timings={'search':[],'read':[]};cold={}
    try:
        for iteration in range(21):
            host.clear_session()
            for kind,command in [('search','busque no segundo cérebro Aurora'),('read','leia a primeira nota')]:
                started=time.perf_counter();result=host.process_command(command);elapsed=time.perf_counter()-started
                if result.status!='success':raise RuntimeError(f'{kind}: {result.status}; não contabilizei como sucesso.')
                if iteration==0:cold[kind]=elapsed
                else:timings[kind].append(elapsed)
    finally:
        started=time.perf_counter();host.close();shutdown=time.perf_counter()-started
    return {'source':str(source),'import_seconds':imported,'construction_seconds':construction,'close_seconds':shutdown,
        'cold_seconds':cold,'warm_seconds':timings,'warm_p95_seconds':{key:percentile(rows) for key,rows in timings.items()}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--child',action='store_true');parser.add_argument('--source');parser.add_argument('--state')
    parser.add_argument('--baseline',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.child:
        print(json.dumps(child(args),ensure_ascii=False));return
    if args.baseline is None or args.output is None:parser.error('Informe --baseline e --output.')
    if args.output.exists():raise ValueError('Saída já existe; não sobrescrevi.')
    root=Path(__file__).resolve().parents[1];fixture=args.output.parent/('benchmark-fixtures-'+uuid.uuid4().hex)
    fixture.mkdir(parents=True,exist_ok=False)
    report={'scope':'Somente construção/encerramento do Orchestrator e busca/leitura legadas; sem modelo, voz, microfone ou conta pessoal. Não mede inicialização visual completa.',
        'fixture_notes':300,'repetitions_per_source':3,'sources':{}}
    for label,source in [('baseline',args.baseline),('current',root)]:
        rows=[]
        for repeat in range(3):
            process=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child','--source',str(source),
                '--state',str(fixture/f'{label}-{repeat}')],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,
                env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if process.returncode:raise RuntimeError(f'Benchmark {label} falhou: '+process.stderr[-1000:])
            rows.append(json.loads(process.stdout.strip().splitlines()[-1]))
        report['sources'][label]=rows
    report['warm_p95_ratio']={kind:percentile([value for row in report['sources']['current'] for value in row['warm_seconds'][kind]])/
        percentile([value for row in report['sources']['baseline'] for value in row['warm_seconds'][kind]]) for kind in ('search','read')}
    with args.output.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'output':str(args.output),'warm_p95_ratio':report['warm_p95_ratio']},ensure_ascii=False))


if __name__=='__main__':main()
