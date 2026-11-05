"""Resume evidências brutas sem modificar resultados nem escolher modelo."""
import argparse
from collections import defaultdict,Counter
import json
import math
from pathlib import Path


def summarize(path):
    groups=defaultdict(list)
    for line in path.read_text(encoding='utf-8').splitlines():
        row=json.loads(line);groups[(row['model'],row['protocol'])].append(row)
    result=[]
    for (model,protocol),rows in groups.items():
        times=sorted(row['elapsed'] for row in rows)
        valid=sum(row['valid_decisions'] for row in rows);invalid=sum(row['invalid_decisions'] for row in rows)
        result.append(dict(model=model,protocol=protocol,cases=len(rows),passed=sum(row['passed'] for row in rows),
            valid_decisions=valid,invalid_decisions=invalid,structural_percent=round(100*valid/max(1,valid+invalid),2),
            completion_percent=round(100*sum(row['passed'] for row in rows)/len(rows),2),
            p50_seconds=times[math.ceil(len(times)*.5)-1],p95_seconds=times[math.ceil(len(times)*.95)-1],
            pressure_releases=sum(bool(row.get('resource_release_before_case')) for row in rows),
            statuses=dict(Counter(row['status'] for row in rows)),failures=[{'case':row['case'],'repeat':row['repeat'],'status':row['status'],'message':row['message']} for row in rows if not row['passed']]))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=summarize(args.source)
    if args.output:args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{key:value for key,value in row.items() if key!='failures'} for row in result],ensure_ascii=False,indent=2))
