"""Mede consultas autorizadas sem voz, histórico pessoal ou efeitos externos."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',choices=['exam','study','project','spoken_exam','all_exams','activity'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Saída já existe.')
    args.output.mkdir(parents=True)
    config_path=Path(os.environ['APPDATA'])/'Therion'/'config.json'
    def loader():
        config=json.loads(config_path.read_text(encoding='utf-8-sig'))
        if 'knowledge_access' in config:
            config['knowledge_access']['supervised_memory']=False
        return config
    config=loader()
    for name in ('LOCALAPPDATA','TEMP','TMP'):
        directory=args.output/name.lower();directory.mkdir()
        os.environ[name]=str(directory)
    from therion.context.second_brain import SecondBrainReader
    from therion.core.ai_core import AICore
    from therion.core.ai_provider_ollama import OllamaProvider
    from therion.core.orchestrator import Orchestrator
    from therion.memory.runtime import KnowledgeRuntime
    from therion.agent.ollama import OllamaAgentProvider
    settings=deepcopy(config.get('agent',{}))
    settings.update(enabled=True,history_enabled=False,learning_enabled=False,timeout_seconds=45)
    for key in ('gmail_enabled','browser_enabled','desktop_enabled','documents_enabled','web_enabled','mcp_enabled','tasks_enabled'):
        settings[key]=False
    ai=config['ai']
    provider=OllamaProvider(model=ai['model'],endpoint=ai['endpoint'],think=ai.get('think',False),
                            timeout=45,context_tokens=8192)
    knowledge=KnowledgeRuntime(SecondBrainReader.DEFAULT_VAULT_ROOT,args.output/'memory',loader)
    host=Orchestrator(simulate=True,vault_root=SecondBrainReader.DEFAULT_VAULT_ROOT,knowledge_runtime=knowledge,
                      ai_core=AICore(provider,[]),agent_config=settings,
                      agent_state_root=args.output/'agent',log_dir=str(args.output/'logs'))
    host._agent_temporary=True
    traces=[]
    for name in ('search_notes','read_note'):
        original=getattr(host.second_brain,name)
        def wrap(original,name):
            def call(*a,**kw):
                started=time.perf_counter()
                try:
                    result=original(*a,**kw)
                    traces.append({'operation':name,'seconds':round(time.perf_counter()-started,4),
                        'query_or_path':str(a[0]) if a else '',
                        'result_count':len(result) if isinstance(result,list) else int(bool(result.success))})
                    return result
                except Exception:
                    traces.append({'operation':name,'seconds':round(time.perf_counter()-started,4),'failed':True})
                    raise
            return call
        setattr(host.second_brain,name,wrap(original,name))
    original_decide=OllamaAgentProvider.decide
    async def decide(self,*a,**kw):
        started=time.perf_counter()
        try:return await original_decide(self,*a,**kw)
        finally:traces.append({'operation':'inference','seconds':round(time.perf_counter()-started,4)})
    OllamaAgentProvider.decide=decide
    cases={'exam':('02 - Faculdade','Qual prova eu tenho primeiro?'),
           'spoken_exam':('02 - Faculdade','Tênio, qual a minha próxima prova da faculdade?'),
           'all_exams':('02 - Faculdade','Busca todas as provas que eu tenho.'),
           'activity':('02 - Faculdade','Qual a próxima atividade da faculdade?'),
           'study':('02 - Faculdade','O que preciso estudar nesta semana?'),
           'project':('10 - Projetos/Therion','O que ficou pendente no projeto Therion?')}
    scope,question=cases[args.case]
    started=time.perf_counter()
    print(json.dumps({'started':args.case}),flush=True)
    try:
        result=host.process_command(f'raízes: {scope} :: {question}')
        report={'case':args.case,'question':question,'scope':scope,'status':result.status,'message':result.message,
                'elapsed_seconds':round(time.perf_counter()-started,3),'trace':traces,
                'model':ai['model'],'notes_modified':False,'voice_measured':False}
    except Exception as error:
        report={'case':args.case,'status':'evaluation_failed','exception_type':type(error).__name__,
                'elapsed_seconds':round(time.perf_counter()-started,3),'trace':traces}
    finally:
        OllamaAgentProvider.decide=original_decide
        host.close()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
