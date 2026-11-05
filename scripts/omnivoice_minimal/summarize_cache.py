"""Resume os controles sem confundir primeira geracao com estado aquecido."""
import ast
import json
from pathlib import Path
import statistics

root=Path(__file__).resolve().parents[2]
folder=root/'tmp/voice-cache-20261020'
before=json.loads((folder/'before.json').read_text())
after=json.loads((folder/'after.json').read_text())

def generation_call(path):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
        and node.func.attr=='generate']
    assert len(calls)==1
    return ast.dump(calls[0],include_attributes=False)

report={'config_unchanged':before['config_sha256']==after['config_sha256'],
    'generation_call_unchanged':generation_call(folder/'server-before.py')==generation_call(root/'scripts/omnivoice_minimal/server.py'),
    'same_steps':before['health_before']['steps']==after['health_before']['steps'],
    'before_reserved_mib':before['cases'][-1]['cuda_reserved_mib'],
    'after_reserved_mib':after['cases'][-1]['cuda_reserved_mib'],
    'before_warm_http_mean_seconds':round(statistics.mean(row['http_seconds'] for row in before['cases'][1:]),4),
    'after_warm_http_mean_seconds':round(statistics.mean(row['http_seconds'] for row in after['cases'][1:]),4),
    'after_first_http_seconds':after['cases'][0]['http_seconds'],
    'cleanup_mean_seconds':round(statistics.mean(row['cache_cleanup_seconds'] for row in after['cases']),4),
    'sample_count_per_phase':len(after['cases']),
    'audio_seed_fixed':False,'acoustic_comparison':False}
report['reserved_reduction_mib']=round(report['before_reserved_mib']-report['after_reserved_mib'],1)
assert report['config_unchanged'] and report['generation_call_unchanged'] and report['same_steps']
(folder/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
