"""Ensaio público real, sem sessão pessoal; registra bloqueio sem contorná-lo."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from therion.agent.contracts import CancellationToken
from therion.integrations.rpc import OwnedWorker
from therion.integrations.documents import DocumentAdapter


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--channel',choices=['chromium','msedge'],default='chromium')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Não sobrescrever evidência anterior.')
    fixture=args.fixture_root.absolute();fixture.mkdir(parents=True,exist_ok=False)
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        path=fixture/key;path.mkdir();os.environ[key]=str(path)
    worker=OwnedWorker('browser',{'research':True,'domains':['*'],'channel':args.channel});token=CancellationToken()
    report={'started':time.time(),'query':'site:docs.ollama.com tool calling','personal_session':False,'browser_channel':args.channel,'status':'unavailable'}
    try:
        search=worker.call('search',{'query':report['query']},token,timeout=40)
        report['search']=search
        source=next((row for row in search['results'] if urlsplit(row['url']).hostname=='docs.ollama.com'),None)
        if source is None:raise ValueError('Busca sem fonte oficial pertinente; não inventei resultado.')
        data=worker.call('read_source',{'source_id':source['id']},token,timeout=30)
        if 'tool' not in data['text'].casefold():raise ValueError('Trecho consultado não sustenta o tema do ensaio.')
        report['source']={key:data.get(key) for key in ('id','url','version','accessed_at','partial','next_offset','total_characters')}
        artifacts=[];adapter=DocumentAdapter([fixture],[fixture])
        # A referência é verificável; nenhum resumo probabilístico nem cópia
        # de artigo é apresentado como avaliação de qualidade da pesquisa.
        body='Ensaio técnico fictício\nFoi consultada uma fonte oficial que menciona ferramentas.\nFonte: '+data['url']+'\nAcesso: '+data['accessed_at']+'\nVersão: '+data['version']
        for suffix in ('.txt','.md','.docx','.pdf','.xlsx'):
            target=fixture/('resultado'+suffix);written=adapter.write(target,body,None);read=adapter.read(target)
            if 'docs.ollama.com' not in str(read['sections']):raise ValueError('Arquivo gerado não preservou a referência.')
            artifacts.append({'path':str(target),'sha256':written['version'],'valid_reference':True})
        report.update(status='success',artifacts=artifacts)
    except (ValueError,OSError,TimeoutError) as error:report['limitation']=str(error)
    finally:
        worker.close();report['closed']=time.time();report['worker_closed']=worker.process is None
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('status','worker_closed','limitation') if key in report},ensure_ascii=False))


if __name__=='__main__':main()
