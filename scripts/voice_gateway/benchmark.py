"""Comparacao isolada: uma instancia/modelo por processo; somente audios sinteticos."""
import argparse
import json
import os
from pathlib import Path
import re
import time
import unicodedata

os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
from asr import Recognizer, memory, process_memory


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    for pattern in ('quatorze e trinta','catorze e trinta','14h30','14:30'):
        text = text.replace(pattern,'14 30')
    return re.findall(r'\w+',text)


def word_error(reference, hypothesis):
    a,b = normalize(reference),normalize(hypothesis)
    previous = list(range(len(b)+1))
    for i,word in enumerate(a,1):
        current = [i]
        for j,other in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(word!=other)))
        previous = current
    return round(previous[-1]/max(1,len(a)),3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',choices=('baseline','tiny','parakeet','turbo'))
    parser.add_argument('--folder',required=True,type=Path)
    args = parser.parse_args()
    report = {'model':args.model,'cpu_threads':2,'device':'cpu','cases':[],'memory_before':memory()}
    started = time.perf_counter()
    try:
        model = Recognizer(args.model,threads=2)
        report['load_seconds'] = model.load_seconds
        report['memory_after_load'] = process_memory()
        fixtures = json.loads((args.folder/'fixtures.json').read_text(encoding='utf-8-sig'))
        for repeat in range(2):
            for row in fixtures:
                result = model.transcribe((args.folder/(row['name']+'.wav')).read_bytes())
                tokens = ' '.join(normalize(result['text']))
                result.update(case=row['name'],repeat=repeat,wer=word_error(row['text'],result['text']),
                    critical_passed=all(any(option in tokens for option in
                        ([alternatives] if isinstance(alternatives,str) else alternatives))
                        for alternatives in row.get('critical',[])))
                if row['name']=='silencio':result['critical_passed']=not result['text']
                report['cases'].append(result)
                print(json.dumps({'case':row['name'],'repeat':repeat,'seconds':result['processing_seconds'],
                                  'critical_passed':result['critical_passed']}),flush=True)
        report['memory_after_test'] = process_memory()
        report['status']='completed'
    except Exception as error:
        report.update(status='skipped_memory' if isinstance(error,MemoryError) else 'failed',
                      failure_type=type(error).__name__)
    report['wall_seconds']=round(time.perf_counter()-started,3)
    (args.folder/(args.model+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=True),flush=True)


if __name__=='__main__':main()
