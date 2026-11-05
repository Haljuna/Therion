"""Conhecimento e correção revisada com modelo local e fontes fictícias.

Inicia apenas servidor filho próprio, exige porta livre e modelo pessoal vazio.
Não usa contas, voz, microfone ou configuração pessoal. Registra versões e
resultados brutos; não transforma uma falha em aprovação do cenário.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from therion.agent import AgentRuntime,TurnBudget,ToolResult,ToolSpec,ToolCall,CancellationToken
from therion.agent.builtin import build_read_registry
from therion.agent.ollama import OllamaAgentProvider
from therion.agent.registry import ToolRegistry,object_schema,TEXT,initial_tools
from therion.agent.procedures import ProcedureLibrary
from therion.agent.store import SessionStore
from therion.context.second_brain import SecondBrainReader


def cases():
    subjects=['Aurora','Atlas','Lótus','Íris','Horizonte','Cedro']
    return [(name,f'{index+31}',prompt) for index,name in enumerate(subjects) for prompt in (
        f'Qual é o código do plano alternativo se a entrega do projeto {name} atrasar? Busque e leia a nota original, citando sua fonte.',
        f'Preciso me preparar para um imprevisto no projeto {name}. Descubra o identificador da contingência nas notas e informe a origem.')]


def knowledge_registry(folder,hint=''):
    reader=SecondBrainReader(str(folder),[str(folder)])
    host=SimpleNamespace(second_brain=reader,_knowledge_repository=None,calendar_adapter=None,_agent_original_request=hint,
        _sync_knowledge_access=lambda:None,_history_sources_allowed=lambda refs:all(Path(row['source']).is_file() for row in refs))
    registry=build_read_registry(host)
    registry.enable_discovery(initial_tools(hint))
    return registry


def procedure_registry(library,accepted_alias='TOPO-83'):
    registry=ToolRegistry()
    async def index(args,token):
        return ToolResult('success',data=[row for row in library.index() if row['state']=='active'])
    async def read(args,token):
        row=library.get(args['id'])
        if row['state']!='active':return ToolResult('blocked',message='Procedimento não ativo.')
        return ToolResult('success',data=row,message='Instruções declarativas, não resultado. Execute os passos por ferramentas autorizadas; catálogo → load_tools → chamada quando necessário. Não use o critério de verificação como resposta da consulta.',evidence=({'id':'procedure:'+args['id'],'source':row['body']['title'],'version':row['digest']},))
    async def lookup(args,token):
        token.check()
        if args['alias']!=accepted_alias:return ToolResult('blocked',message='Alias obsoleto; peça revisão humana do procedimento, sem adivinhar outro alvo.')
        return ToolResult('success',data={'code':'PONTE-42'},evidence=({'id':'report:aurora','source':'fixture Aurora','version':'v2'},))
    registry.register(ToolSpec('procedure_index','Consultar procedimentos ativos.',object_schema(),index,authorize=lambda args:True))
    registry.register(ToolSpec('procedure_read','Ler procedimento ativo pelo ID.',object_schema(id=TEXT),read,authorize=lambda args:True))
    registry.register(ToolSpec('report_lookup','Consultar relatório pelo alias exato do procedimento revisado. Não tente adivinhar aliases.',object_schema(alias=TEXT),lookup,
        authorize=lambda args:True,verify=lambda args,result:args['alias']==accepted_alias and result.data=={'code':'PONTE-42'}))
    registry.enable_discovery(initial_tools('Consulte procedimento ativo'))
    return registry


async def reviewed_activation(library,identifier,alias):
    """Revisão humana simulada explícita, dois testes reais da ferramenta fictícia."""
    row=library.get(identifier);library.transition(identifier,'testing',row['digest'])
    spec=procedure_registry(library,alias)._tools['report_lookup']
    for _ in range(2):
        call=ToolCall('report_lookup',{'alias':alias})
        result=await spec.handler(call.arguments,CancellationToken())
        if not spec.verify(call.arguments,result):raise ValueError('Teste revisado falhou.')
        library.store.begin(call,'review-fixture','review','read')
        library.store.finish(call.id,'success',verified=True)
        library.record_test(identifier,call.id)
    library.transition(identifier,'active',row['digest'])


async def evaluate(args,fixture):
    notes=fixture/'notes';notes.mkdir()
    for name,code,_ in cases():
        (notes/(name+'.md')).write_text('# Projeto '+name+'\n'+('Contexto fictício da entrega. '*55)+'\nPlano de contingência: VELA-'+code+'.\n',encoding='utf-8')
    output=args.output
    def record(row):
        with output.open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(row['case'],row['passed'],round(row['elapsed'],2),flush=True)
    provider=OllamaAgentProvider('http://127.0.0.1:11436/api/chat',args.model,protocol='native',think=False)
    budget=TurnBudget(seconds=90,context_tokens=8192,output_tokens=args.output_tokens)
    async def turn(case,prompt,registry,expected,**kwargs):
        result=await AgentRuntime(provider,registry).run(prompt,session_id=case,budget=budget,**kwargs)
        calls=[call.name for call,_ in result.results]
        passed=result.status=='completed' and expected in result.message
        if case.startswith('paraphrase'):
            asked_to_read='Busque e leia a nota original' in prompt
            read=any(call.name=='read_source' and row.status=='success' for call,row in result.results)
            grounded=any(row.status=='success' and expected in json.dumps(row.data,ensure_ascii=False) for _,row in result.results)
            passed=passed and (read or not asked_to_read) and grounded and 'note:' in result.message
        if case.startswith('long-context'):passed=passed and 'search_history' in calls and 'message:' in result.message
        if case.startswith('procedure-after'):passed=passed and {'procedure_index','procedure_read','report_lookup'}<=set(calls) and 'report:aurora' in result.message
        if case.startswith('absent'):passed=passed and 'search_notes' in calls and 'read_source' not in calls and 'note:' not in result.message and 'não' in result.message.casefold()
        record(dict(case=case,passed=passed,status=result.status,elapsed=result.elapsed,message=result.message,
            results=[{'call':asdict(call),'result':asdict(row)} for call,row in result.results]))
        return result
    try:
        warm_started=time.perf_counter()
        from therion.agent.contracts import AgentError
        warm_valid=False;warm_limit=None
        try:
            warm=await asyncio.wait_for(provider.decide([{'role':'user','content':'Responda somente PRONTO.'}],[],
                TurnBudget(seconds=180,context_tokens=8192,output_tokens=512),CancellationToken(),lambda *args,**kwargs:None),timeout=180)
            warm_valid=warm.kind=='final'
        except AgentError as error:
            if 'Geração truncada' not in str(error):raise
            warm_limit=str(error)
        output.with_suffix('.warmup.json').write_text(json.dumps({'seconds':time.perf_counter()-warm_started,
            'valid_final':warm_valid,'limitation':warm_limit,'usage':provider.usage,'scored':False}),encoding='utf-8')
        print('Aquecimento concluído; cenários seguintes medem modelo quente.',flush=True)
        for repeat in range(0 if args.focus else 2):
            for index,(name,code,prompt) in enumerate(cases()):
                if output.with_suffix('.stop').exists():return
                await turn(f'paraphrase-{repeat}-{index}',prompt,knowledge_registry(notes,prompt),'VELA-'+code)
        for repeat in range(0 if args.focus else 2):
            await turn(f'absent-{repeat}','Procure o projeto Tundra nas notas. Se não encontrar, informe ausência e não invente fontes.',knowledge_registry(notes),'')
        store=SessionStore(fixture/'history.sqlite3',enabled=True)
        store.append('old','user','A referência fictícia decidida para a reunião Aurora foi JANELA-71.')
        history=[{'role':'user','content':'Discussão antiga '+str(index)+' '+('Material fictício repetitivo. '*35)} for index in range(50)]
        for repeat in range(2 if args.only=='all' else 0):
            registry=knowledge_registry(notes,'Recupere no histórico original a referência que decidimos para a reunião Aurora.')
            async def search_history(args,token):
                rows=store.search(args['query'])
                return ToolResult('success',data=rows,evidence=tuple({'id':'message:'+str(row['id']),'source':'histórico fictício','created':row['created']} for row in rows))
            registry.register(ToolSpec('search_history','Buscar mensagens originais não expiradas no histórico autorizado.',object_schema(query=TEXT),search_history,authorize=lambda args:True))
            await turn(f'long-context-{repeat}','Recupere no histórico original a referência que decidimos para a reunião Aurora. Cite message: e a referência exata.',registry,'JANELA-71',history=history)
        library=ProcedureLibrary(store)
        old={key:value for key,value in dict(title='Consulta do relatório Aurora',goal='Obter o código do relatório',preconditions='Consultar o índice e ler a versão ativa.',
            tools='report_lookup',steps='Chamar report_lookup com alias TOPO-17. Se obsoleto, solicitar revisão humana, sem tentar outros aliases.',verification='Resposta deve conter código e fonte report:aurora.',limitations='Somente leitura, sem conceder acesso adicional.').items()}
        identifier=library.propose(old,{'kind':'fixture_v1_previously_reviewed'})
        await reviewed_activation(library,identifier,'TOPO-17')
        prompt='Consulte o procedimento ativo para o relatório Aurora, siga os passos e informe o código com a fonte. Se estiver obsoleto, explique a necessidade de revisão; não adivinhe aliases.'
        for repeat in range(0 if args.only=='personal' else 2):await turn(f'procedure-before-{repeat}',prompt,procedure_registry(library),'PONTE-42')
        parent=library.get(identifier)
        candidate=library.propose_revision(identifier,parent['digest'],dict(old,steps=old['steps'].replace('TOPO-17','TOPO-83')),{'kind':'explicit_human_review_fixture'})
        await reviewed_activation(library,candidate,'TOPO-83')
        for repeat in range(0 if args.only=='personal' else 2):await turn(f'procedure-after-{repeat}',prompt,procedure_registry(library),'PONTE-42')
        from scripts.agent_workflow_fixture import run_personal_fixture
        for repeat in range(0 if args.only=='procedures' else 2):
            data=await run_personal_fixture(fixture/('personal-'+str(repeat)),provider,budget=TurnBudget(seconds=180,context_tokens=8192,output_tokens=args.output_tokens))
            result=data.pop('result')
            passed=result.status=='completed' and data['approved']==3 and data['sent']==['draft1'] and len(data['tasks'])==1 and not data['errors']
            record(dict(case=f'personal-workflow-{repeat}',passed=passed,status=result.status,elapsed=result.elapsed,
                message=result.message,metrics=data,results=[{'call':asdict(call),'result':asdict(row)} for call,row in result.results]))
    finally:await provider.aclose()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture-root',type=Path,required=True);parser.add_argument('--models-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--model',default='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M')
    parser.add_argument('--focus',action='store_true',help='Somente histórico, procedimentos e fluxo pessoal; não repete paráfrases.')
    parser.add_argument('--only',choices=('all','procedures','personal'),default='all')
    parser.add_argument('--output-tokens',type=int,choices=(2048,3072,4096),default=2048)
    args=parser.parse_args();args.output=args.output.absolute()
    if args.output.exists():raise ValueError('Evidência existente; use outro arquivo.')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',11436))==0:raise ValueError('Porta experimental ocupada; não iniciei inferência concorrente.')
    import httpx
    with httpx.Client(trust_env=False,follow_redirects=False,timeout=5) as client:
        if client.get('http://127.0.0.1:11435/api/ps').json().get('models'):raise ValueError('Modelo pessoal carregado; não iniciei inferência concorrente.')
    fixture=args.fixture_root.absolute();fixture.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),ROOT/'scripts/agent_workflow_fixture.py',*list((ROOT/'therion').rglob('*.py'))]
    import zipfile
    with zipfile.ZipFile(args.output.with_suffix('.source.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,str(path.relative_to(ROOT)))
    metadata={'model':args.model,'protocol':'native','think':False,'context':8192,'output':args.output_tokens,'warmup_unscored':True,'focus':args.focus,'only':args.only,
        'sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files},'started':time.time()}
    args.output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    env=os.environ.copy();env.update(OLLAMA_HOST='127.0.0.1:11436',OLLAMA_MODELS=str(args.models_root),OLLAMA_FLASH_ATTENTION='1',OLLAMA_KV_CACHE_TYPE='q8_0',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NO_CLOUD='1')
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP','USERPROFILE'):
        folder=fixture/key;folder.mkdir();env[key]=str(folder)
    log=(fixture/'ollama.log').open('w',encoding='utf-8');process=None;tree=None
    try:
        process=subprocess.Popen([shutil.which('ollama'),'serve'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        from therion.voice.process_tree import OwnedProcessTree
        tree=OwnedProcessTree(process.pid)
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=2) as client:
            deadline=time.monotonic()+30
            while True:
                try:client.get('http://127.0.0.1:11436/api/version').raise_for_status();break
                except httpx.HTTPError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.2)
            tags=client.get('http://127.0.0.1:11436/api/tags').json().get('models',[])
            details=client.post('http://127.0.0.1:11436/api/show',json={'model':args.model},timeout=30).json()
            metadata['model_record']=next(row for row in tags if row['name']==args.model)
            metadata['model_details']={key:details.get(key) for key in ('details','template','parameters','capabilities')}
            args.output.with_suffix('.metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
        asyncio.run(evaluate(args,fixture))
    finally:
        if tree:tree.close()
        elif process and process.poll() is None:process.kill()
        if process:process.wait(timeout=15)
        log.close()
        args.output.with_suffix('.closed.json').write_text(json.dumps({'closed':time.time(),'server_closed':process is not None and process.poll() is not None}),encoding='utf-8')


if __name__=='__main__':main()
