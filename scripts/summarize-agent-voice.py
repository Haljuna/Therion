"""Métricas do ensaio sintético; não substitui microfone nem avaliação auditiva."""
import argparse
import json
import math
from pathlib import Path
import re
import unicodedata


def words(value):
    return re.findall(r'\w+',''.join(char for char in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(char)))


def distance(left,right):
    previous=list(range(len(right)+1))
    for index,word in enumerate(left,1):
        current=[index]
        for column,other in enumerate(right,1):current.append(min(current[-1]+1,previous[column]+1,previous[column-1]+(word!=other)))
        previous=current
    return previous[-1]


def summarize(path):
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    cycles=[row for row in rows if row.get('event')=='voice_cycle']
    profile=json.loads(path.with_suffix('').with_suffix('.voice-profile.json').read_text(encoding='utf-8'))
    closed_path=path.with_suffix('').with_suffix('.voice-closed.json')
    closed=json.loads(closed_path.read_text(encoding='utf-8')) if closed_path.exists() else {}
    warm=[row for row in cycles if row['timestamp']>=profile['soak_started']+300]
    result={'synthetic':True,'microphone':False,'playback':False,'voice':profile['voice'],'cycles':len(cycles),
        'warm_seconds':closed.get('closed',cycles[-1]['timestamp'])-profile['soak_started'],
        'owned_processes_closed':closed.get('owned_processes_closed',False),'memory':{}}
    for process in ('supervisor','tts_process'):
        points=[(row['timestamp'],row[process]['private_bytes']) for row in warm if row.get(process)]
        if len(points)<2:continue
        x=[point[0]-points[0][0] for point in points];y=[point[1] for point in points]
        mean_x=sum(x)/len(x);mean_y=sum(y)/len(y)
        slope=sum((a-mean_x)*(b-mean_y) for a,b in zip(x,y))/sum((a-mean_x)**2 for a in x)*3600
        result['memory'][process]={'samples_after_5min':len(points),'first_private_bytes':y[0],'last_private_bytes':y[-1],
            'min_private_bytes':min(y),'max_private_bytes':max(y),'linear_bytes_per_hour':slope}
    for label,values in [('tts_seconds',[row['tts']['seconds'] for row in cycles]),('stt_seconds',[row['stt_seconds'] for row in cycles])]:
        values=sorted(values);result[label]={'p50':values[math.ceil(len(values)*.5)-1],'p95':values[math.ceil(len(values)*.95)-1]}
    reference=[words(row['reference']) for row in cycles]
    errors=sum(distance(expected,words(row['transcript'])) for expected,row in zip(reference,cycles))
    negatives=[row for row in cycles if 'nao' in words(row['reference'])]
    result['synthetic_asr']={'word_errors':errors,'reference_words':sum(map(len,reference)),
        'word_error_rate':errors/max(1,sum(map(len,reference))), 'negation_cases':len(negatives),
        'negation_retained':sum('nao' in words(row['transcript']) for row in negatives),
        'reliable_cycles':sum(row['reliable'] for row in cycles)}
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=summarize(args.source)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
