"""Comparação alternada de parsing local, com documento fictício e hash por hit."""
import argparse
import json
from pathlib import Path
import statistics
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Saída já existe.')
    args.fixture_root.mkdir(parents=True,exist_ok=False)
    from docx import Document
    from therion.integrations.documents import DocumentSession
    path=args.fixture_root/'fixture.docx';document=Document()
    for index in range(120):document.add_paragraph('Projeto Aurora, etapa '+str(index)+'. Texto técnico fictício para comparar a leitura local.')
    document.save(path)
    sessions={key:DocumentSession({'read_roots':[str(args.fixture_root)],'cache_enabled':key=='cache'}) for key in ('original','cache')}
    samples={key:[] for key in sessions};expected=None
    for iteration in range(35):
        for key in (('original','cache') if iteration%2==0 else ('cache','original')):
            start=time.perf_counter();row=sessions[key].dispatch('read',{'path':str(path)});elapsed=time.perf_counter()-start
            row.pop('cache_hit',None)
            if expected is None:expected=row
            if row!=expected:raise AssertionError('Resultados de leitura divergentes.')
            if iteration>=5:samples[key].append(elapsed)
    report={'fixture':'120 parágrafos fictícios DOCX','iterations':30,'order':'alternada','warmup':5,'results_equal':True,'raw_seconds':samples,
        'median_seconds':{key:statistics.median(rows) for key,rows in samples.items()},
        'p95_seconds':{key:sorted(rows)[28] for key,rows in samples.items()},'default_enabled':False}
    report['p95_ratio']=report['p95_seconds']['cache']/report['p95_seconds']['original']
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='raw_seconds'},ensure_ascii=False))
    for session in sessions.values():session.close()


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));main()
