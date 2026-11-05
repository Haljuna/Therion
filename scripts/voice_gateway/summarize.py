"""Recalcula medidas e criterios a partir das transcricoes registradas."""
import json
from pathlib import Path
import statistics
from benchmark import normalize, word_error

folder=Path(__file__).resolve().parents[2]/'tmp/asr-comparison-20261020'
fixtures={row['name']:row for row in json.loads((folder/'fixtures.json').read_text(encoding='utf-8-sig'))}
summary=[]
for kind in ('baseline','tiny','parakeet','turbo'):
    report=json.loads((folder/(kind+'-result.json')).read_text(encoding='utf-8'))
    for case in report['cases']:
        fixture=fixtures[case['case']]
        tokens=' '.join(normalize(case['text']))
        case['critical_passed']=all(any(' '.join(normalize(option)) in tokens for option in
            ([alternatives] if isinstance(alternatives,str) else alternatives))
            for alternatives in fixture.get('critical',[]))
        case['wer']=word_error(fixture['text'],case['text'])
        if case['case']=='silencio':case['critical_passed']=not case['text']
    (folder/(kind+'-result.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    speech=[row for row in report['cases'] if row['case']!='silencio']
    row={'model':kind,'status':report['status'],'speech_trials':len(speech)}
    if speech:
        row.update(mean_seconds=round(statistics.mean(c['processing_seconds'] for c in speech),3),
            median_seconds=round(statistics.median(c['processing_seconds'] for c in speech),3),
            mean_wer=round(statistics.mean(c['wer'] for c in speech),3),
            critical_passed=sum(c['critical_passed'] for c in speech),
            load_seconds=report['load_seconds'],memory=report['memory_after_test'])
    summary.append(row)
(folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary))
