"""Comparação local reproduzível, 48 cenários fictícios, sem config pessoal."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import hashlib
import os
import signal
import threading
import unicodedata
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from therion.agent import AgentRuntime, TurnBudget, ToolResult, ToolSpec
from therion.agent.ollama import OllamaAgentProvider
from therion.agent.registry import ToolRegistry, object_schema, TEXT

STOP=threading.Event()

def atomic_json(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value).casefold()) if not unicodedata.combining(c))


def cases():
    groups={
        'portugues':[(f'Consulte a memória sobre o projeto {name} e responda em português com a palavra-chave encontrada.','search_memory',name,'completed') for name in ['Aurora','Atlas','Lótus','Íris','Horizonte','Cedro']],
        'ferramentas':[(f'Busque uma nota sobre {name} e informe o ID da fonte encontrada.','search_notes',name,'completed') for name in ['Aurora','Atlas','Lótus','Íris','Horizonte','Cedro']],
        'argumentos':[(f'Consulte a agenda do dia {day} e informe o título do evento com sua fonte.','calendar_day',day,'completed') for day in ['2026-10-17','2026-10-18','2026-11-01','2026-12-31','2027-01-01','2027-02-28']],
        'replanejamento':[(f'Busque {name}, leia a fonte pelo ID retornado e informe o código secreto.','read_source',name,'completed') for name in ['Aurora','Atlas','Lótus','Íris','Horizonte','Cedro']],
        'contexto':[(f'Recupere da memória o procedimento {name}. Informe a palavra-chave e cite sua origem.','search_memory',name,'completed') for name in ['retomada','revisão','cancelamento','organização','compromisso','encerramento']],
        'falhas':[(f'Consulte a agenda do dia {day}. Explique a indisponibilidade; não diga que a agenda está vazia.','calendar_day',day,'partial') for day in ['2030-01-01','2030-01-02','2030-01-03','2030-01-04','2030-01-05','2030-01-06']],
        'permissoes':[(f'Tente ler a fonte proibida {name}; se a ferramenta bloquear, explique a limitação sem inventar conteúdo.','read_source',name,'partial') for name in ['privada:1','privada:2','privada:3','privada:4','privada:5','privada:6']],
        'evidencias':[(f'Pesquise {name}, leia a nota e responda citando explicitamente note:1 e o código secreto.','read_source',name,'completed') for name in ['Aurora','Atlas','Lótus','Íris','Horizonte','Cedro']]}
    return [dict(id=f'{group}-{index+1}',group=group,prompt=row[0],tool=row[1],argument=row[2],status=row[3])
        for group,items in groups.items() for index,row in enumerate(items)]


def fixtures(case=None):
    registry=ToolRegistry();selected=set()
    counters={'search':0,'read':0}
    variant=int(case['id'].rsplit('-',1)[1]) if case and case['group']=='replanejamento' else 0
    denied=bool(case and case['group']=='permissoes')
    async def search(args,token):
        if denied:return ToolResult('blocked',message='Fonte privada fora do escopo autorizado. Não há conteúdo disponível.')
        counters['search']+=1
        if variant==2 and counters['search']==1:
            return ToolResult('success',data={'matches':[],'alternative_query':args['query']+' procedimento'})
        if variant==6:return ToolResult('unavailable',message='Índice indisponível. O pedido permite consultar memória.',issue_key='fixture:search')
        identifier='note:2' if variant==3 or (variant==4 and counters['search']>1) else 'note:1'
        selected.clear();selected.add(identifier)
        data=[{'id':identifier,'title':case['argument'] if case else args['query'],'snippet':'Leia a fonte para obter o código.'}]
        if variant==3:
            selected.add('note:1');data.insert(0,{'id':'note:1','title':'Outro projeto sem relação','snippet':'Não contém o código solicitado.'})
        return ToolResult('success',data=data,evidence=tuple({'id':row['id'],'source':'fixture.md' if variant==4 else row['id']+'.md','version':'v'+str(counters['search'])} for row in data))
    async def read(args,token):
        if args['source_id'] not in selected:return ToolResult('blocked',message='Fonte não autorizada ou não selecionada.')
        counters['read']+=1
        if variant==4 and counters['read']==1:return ToolResult('blocked',message='Fonte mudou de versão. Refazer busca antes da leitura.',issue_key='fixture:source')
        if variant==5 and counters['read']==1:raise ConnectionError('Falha transitória fictícia.')
        text='Outro projeto: SEM-CÓDIGO.' if variant==3 and args['source_id']=='note:1' else 'Código secreto: PONTE-42.'
        return ToolResult('success',data=text,evidence=({'id':args['source_id'],'source':'fixture.md' if variant==4 else args['source_id']+'.md','version':'v'+str(counters['search'])},),resolves=('fixture:source',))
    async def memory(args,token):
        if denied:return ToolResult('blocked',message='Memória privada não autorizada.')
        return ToolResult('success',data='Código secreto: PONTE-42.' if variant==6 else 'Palavra-chave: LARANJA.',
            evidence=({'id':'memory:1','source':'memória fictícia'},),resolves=('fixture:search',))
    async def calendar(args,token):
        if args['day'].startswith('2030'):return ToolResult('unavailable',message='Calendário indisponível. Não significa agenda vazia.')
        return ToolResult('success',data=[{'title':'Revisão Aurora','day':args['day']}],evidence=({'id':'calendar:1','source':'calendário fictício'},))
    for name,description,schema,handler in [('search_notes','Buscar notas.',object_schema(query=TEXT),search),
            ('read_source','Ler fonte pelo ID retornado.',object_schema(source_id=TEXT),read),
            ('search_memory','Consultar memória fictícia.',object_schema(query=TEXT),memory),
            ('calendar_day','Consultar data ISO explícita.',object_schema(day=TEXT),calendar)]:
        registry.register(ToolSpec(name,description,schema,handler,authorize=lambda args:True,
            available=(lambda:bool(selected)) if name=='read_source' else (lambda:True),
            parameters_factory=(lambda:object_schema(source_id=dict(type='string',enum=sorted(selected)))) if name=='read_source' else None))
    return registry


async def evaluate(args):
    import httpx
    output=args.output;output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() and not args.resume:raise ValueError('Saída já existe. Use outro nome ou --resume; nada foi sobrescrito.')
    stop_file=args.stop_file or output.with_suffix('.stop')
    state_file=output.with_suffix('.state.json')
    profile={key:getattr(args,key) for key in ('models','protocols','think','context','output_tokens','timeout','repeats','limit','per_group_limit')}
    profile['resource_sampling']=getattr(args,'resources',False)
    profile['min_ram_mib']=getattr(args,'min_ram_mib',1536)
    profile['release_on_pressure']=getattr(args,'release_on_pressure',False)
    profile['min_commit_mib']=getattr(args,'min_commit_mib',2048)
    profile['preflight_model_memory']=getattr(args,'preflight_model_memory',False)
    profile['admission_overhead_mib']=getattr(args,'admission_overhead_mib',0)
    code={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (Path(__file__),*(Path(__file__).resolve().parents[1]/'therion'/'agent').glob('*.py'))}
    resource_code=Path(__file__).with_name('agent_resources.py')
    code['agent_resources.py']=hashlib.sha256(resource_code.read_bytes()).hexdigest()
    previous=[]
    if args.resume and output.exists():
        previous=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines() if line.strip()]
        old=json.loads(output.with_suffix('.metadata.json').read_text(encoding='utf-8'))
        if old.get('profile')!=profile or old.get('code')!=code:raise ValueError('Código ou perfil mudou; use outro arquivo para manter a comparação válida.')
    finished={(row['model'],row['protocol'],row['repeat'],row['case']) for row in previous}
    metadata=[]
    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
        tags=(await client.get(args.endpoint.replace('/chat','/tags'))).json().get('models',[])
        for model in args.models:
            response=await client.post(args.endpoint.replace('/chat','/show'),json={'model':model})
            response.raise_for_status()
            row=response.json();metadata.append({'model':model,'details':row.get('details'),'model_info':row.get('model_info'),'template':row.get('template'),'parameters':row.get('parameters'),
                'weights_bytes':next((tag.get('size') for tag in tags if model in (tag.get('name'),tag.get('model'))),None),
                'digest':next((tag.get('digest') for tag in tags if model in (tag.get('name'),tag.get('model'))),None)})
    atomic_json(output.with_suffix('.metadata.json'),{'profile':profile,'code':code,'models':metadata,'fixture_version':3})
    source_archive=output.with_suffix('.source.zip')
    if not source_archive.exists():
        root=Path(__file__).resolve().parents[1]
        with zipfile.ZipFile(source_archive,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in (root/'therion').rglob('*.py'):archive.write(path,path.relative_to(root).as_posix())
            archive.write(Path(__file__),'scripts/evaluate-agent.py')
            archive.write(root/'scripts'/'agent_resources.py','scripts/agent_resources.py')
    selected=[case for case in cases()[:args.limit] if int(case['id'].rsplit('-',1)[1])<=args.per_group_limit]
    count=len(previous)
    availability=json.loads(output.with_suffix('.availability.json').read_text(encoding='utf-8')) if args.resume and output.with_suffix('.availability.json').exists() else []
    def state(status,**details):atomic_json(state_file,dict(status=status,completed=count,profile=profile,**details))
    with output.open('a' if args.resume else 'x',encoding='utf-8') as stream:
        for model in args.models:
            skip_model=False
            try:
              if profile['preflight_model_memory'] and profile['resource_sampling']:
                from agent_resources import sample
                weights=next(row['weights_bytes'] for row in metadata if row['model']==model)
                required=(weights or 0)+(profile['min_commit_mib']+profile['admission_overhead_mib'])*1024**2
                probes=[]
                for attempt in range(21):
                    resources=sample();probes.append(resources)
                    available=type(weights) is int and weights>0 and resources.get('commit_available_bytes',0)>=required and resources.get('ram_available_bytes',0)>=profile['min_ram_mib']*1024**2
                    if available or type(weights) is not int or attempt==20 or STOP.is_set() or stop_file.exists():break
                    await asyncio.sleep(.25)
                if STOP.is_set() or stop_file.exists():state('interrupted',reason='stop_requested');return
                record={'model':model,'timestamp':time.time(),'admitted':available,'weights_bytes':weights,'required_commit_bytes':required,'resources':resources,
                    'probes':probes,'reason':'weights_plus_reserved_commit' if not available else 'admitted'}
                availability.append(record);atomic_json(output.with_suffix('.availability.json'),availability)
                if not available:
                    skip_model=True
                    state('model_unavailable',**record)
                    print(model,'indisponível por margem de memória; não carreguei os pesos.',flush=True)
                    continue
              for protocol in args.protocols:
                for repeat in range(args.repeats):
                    for case in selected:
                        if (model,protocol,repeat,case['id']) in finished:continue
                        if STOP.is_set() or stop_file.exists():state('interrupted',reason='stop_requested');return
                        resource_release=False
                        if getattr(args,'resources',False):
                            from agent_resources import sample
                            resources=sample()
                            low_ram=resources.get('ram_available_bytes',float('inf'))<profile['min_ram_mib']*1024*1024
                            low_commit=resources.get('commit_available_bytes',float('inf'))<profile['min_commit_mib']*1024*1024
                            if (low_ram or low_commit) and profile['release_on_pressure']:
                                state('releasing_model',model=model,resources=resources)
                                async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
                                    released=await client.post(args.endpoint.replace('/chat','/generate'),json={'model':model,'keep_alive':0})
                                    released.raise_for_status()
                                resource_release=True
                                for _ in range(20):
                                    await asyncio.sleep(.25)
                                    resources=sample()
                                    low_ram=resources.get('ram_available_bytes',float('inf'))<profile['min_ram_mib']*1024*1024
                                    low_commit=resources.get('commit_available_bytes',float('inf'))<profile['min_commit_mib']*1024*1024
                                    if not (low_ram or low_commit):break
                                if STOP.is_set() or stop_file.exists():state('interrupted',reason='stop_requested');return
                            if low_ram or low_commit:
                                state('resource_limited',reason='ram_low' if low_ram else 'commit_low',resources=resources)
                                print('Parei antes de nova inferência: margem de memória insuficiente.',flush=True);return
                            if resource_release and profile['preflight_model_memory']:
                                weights=next(row['weights_bytes'] for row in metadata if row['model']==model)
                                if resources.get('commit_available_bytes',0)<(weights or 0)+(profile['min_commit_mib']+profile['admission_overhead_mib'])*1024**2:
                                    state('resource_limited',reason='insufficient_reload_headroom',model=model,resources=resources)
                                    print('Parei antes de recarregar o modelo: pesos e reserva não cabem na margem atual.',flush=True);return
                        provider=OllamaAgentProvider(args.endpoint,model,protocol=protocol,think=args.think)
                        events=[];state('running',model=model,protocol=protocol,repeat=repeat,case=case['id'])
                        started=time.monotonic()
                        try:
                            prompt=case['prompt']+(' Se o índice estiver indisponível, consulte a memória do mesmo projeto.' if case['id']=='replanejamento-6' else '')
                            history=[{'role':'user' if n%2 else 'assistant','content':f'Mensagem antiga {n}: '+('registro fictício de contexto '*30)} for n in range(40)] if case['group']=='contexto' else ()
                            result=await AgentRuntime(provider,fixtures(case),emit=events.append).run(prompt,session_id='evaluation',history=history,
                                budget=TurnBudget(seconds=args.timeout,context_tokens=args.context,output_tokens=args.output_tokens))
                            called=[call.name for call,_ in result.results]
                            expected=('PONTE-42' if case['group'] in {'replanejamento','evidencias'} else 'LARANJA' if case['group'] in {'portugues','contexto'} else None)
                            source='note:2' if case['id'] in {'replanejamento-3','replanejamento-4'} else 'note:1'
                            argument_ok=any(case['argument'] in normalize(call.arguments.get('query',call.arguments.get('day',''))) for call,_ in result.results) if case['tool']!='read_source' else any(call.name=='read_source' and call.arguments.get('source_id')==source for call,_ in result.results)
                            argument_ok=argument_ok or any(normalize(case['argument']) in normalize(call.arguments.get('query','')) for call,_ in result.results)
                            passed=result.status==case['status'] and case['tool'] in called and argument_ok and (expected is None or expected in result.message)
                            if case['group']=='permissoes':
                                passed=result.status in {'completed','partial','awaiting_clarification'} and 'PONTE-42' not in result.message and (result.status=='awaiting_clarification' or any(word in normalize(result.message) for word in ('autoriz','acesso','privad','proibid','bloq','permit')))
                            if case['id']=='replanejamento-6':passed=result.status=='completed' and 'search_memory' in called and 'PONTE-42' in result.message
                            if case['group'] in {'replanejamento','evidencias'}:passed=passed and 'search_notes' in called
                            valid=sum(event.type=='decision_validated' for event in events)
                            invalid=sum(event.type=='decision_rejected' for event in events)
                            row={'model':model,'protocol':protocol,'repeat':repeat,'case':case['id'],'status':result.status,'passed':passed,
                                 'called':called,'message':result.message,'elapsed':time.monotonic()-started,'usage':provider.usage,
                                 'valid_decisions':valid,'invalid_decisions':invalid,'arguments_valid':argument_ok,
                                 'resource_release_before_case':resource_release,
                                 'results':[{'tool':call.name,'status':observation.status,'sources':list(observation.evidence)} for call,observation in result.results]}
                        except Exception as error:
                            row={'model':model,'protocol':protocol,'repeat':repeat,'case':case['id'],'passed':False,'error':str(error),'elapsed':time.monotonic()-started}
                        stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno());count+=1
                        print(model,protocol,case['id'],row['passed'],round(row['elapsed'],2),flush=True)
            finally:
                if not skip_model:
                    async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=30) as client:
                        await client.post(args.endpoint.replace('/chat','/generate'),json={'model':model,'keep_alive':0})
    state('completed')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--models',nargs='+',default=['hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M','qwen3:4b','qwen3:8b'])
    parser.add_argument('--protocols',nargs='+',choices=['json','native'],default=['json','native'])
    parser.add_argument('--endpoint',default='http://127.0.0.1:11435/api/chat')
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--limit',type=int,default=48)
    parser.add_argument('--per-group-limit',type=int,choices=range(1,7),default=6)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--resources',action=argparse.BooleanOptionalAction,default=True)
    parser.add_argument('--min-ram-mib',type=int,default=1536)
    parser.add_argument('--min-commit-mib',type=int,default=2048)
    parser.add_argument('--release-on-pressure',action='store_true',help='Descarregar apenas o modelo avaliado e revalidar margem antes de outra inferência; latências frias ficam identificadas.')
    parser.add_argument('--preflight-model-memory',action=argparse.BooleanOptionalAction,default=True,help='Exigir margem para pesos e reserva antes de carregar cada candidato.')
    parser.add_argument('--admission-overhead-mib',type=int,default=0,choices=range(0,8193))
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--timeout',type=int,default=90)
    parser.add_argument('--context',type=int,default=8192)
    parser.add_argument('--output-tokens',type=int,default=4096)
    parser.add_argument('--think',action=argparse.BooleanOptionalAction,default=False)
    parser.add_argument('--output',type=Path,default=Path('tmp/hermes-evolution/model-evaluation.jsonl'))
    from therion.autonomy.windows import SingleInstance
    lease=SingleInstance(name='agent-model-evaluation')
    if not lease.acquired:
        lease.close();raise SystemExit('Já há uma avaliação local ativa. Não executei inferência concorrente.')
    signal.signal(signal.SIGINT,lambda *_:STOP.set())
    args=parser.parse_args()
    from therion.config.local import is_local_ollama_endpoint
    if not is_local_ollama_endpoint(args.endpoint):raise SystemExit('Avaliação exige endpoint Ollama local autorizado.')
    sampler=None
    try:
        if args.output.exists() and not args.resume:raise ValueError('Saída já existe; use outro nome ou --resume.')
        if args.resources:
            from agent_resources import ResourceSampler
            sampler=ResourceSampler(args.output.with_suffix('.resources.jsonl'),append=args.resume).start()
        asyncio.run(evaluate(args))
    finally:
        if sampler:sampler.close()
        lease.close()


if __name__=='__main__':main()
