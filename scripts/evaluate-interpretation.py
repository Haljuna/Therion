"""Avaliação pontual de leitura interpretativa com nota inteiramente fictícia."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--endpoint', required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='therion-interpretation-eval-'))
    vault = root/'vault'
    note = vault/'10 - Projetos'/'Therion'/'Atividade fictícia.md'
    note.parent.mkdir(parents=True)
    note.write_text('# Atividade fictícia\nEntregar três tabelas-verdade: AND, OR e NOT.\n'
        'AND produz 1 somente se todas as entradas forem 1. OR produz 1 se ao menos uma entrada for 1. '
        'NOT inverte a entrada. A entrega é sexta-feira.\nMARCADOR-DO-TEXTO-INTEGRAL-FICTICIO', encoding='utf-8')
    provider = OllamaProvider(model=args.model, endpoint=args.endpoint, think=True, timeout=25)
    orch = Orchestrator(vault_root=str(vault), log_dir=str(root/'logs'), ai_core=AICore(provider, []))
    start = time.monotonic()
    result = orch.process_command('leia no segundo cérebro 10 - Projetos/Therion/Atividade fictícia.md')
    report = {'model': args.model, 'seconds': round(time.monotonic()-start,3), 'status':result.status,
        'message': result.message, 'speech_message':result.speech_message,
        'integral_marker_in_answer':'MARCADOR-DO-TEXTO-INTEGRAL-FICTICIO' in result.message,
        'source_present':'Fonte:' in result.message, 'scope':'nota fictícia; sem memória pessoal ou ações externas'}
    orch.close()
    (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True), flush=True)
    print('Evidência: '+str(root/'report.json'), flush=True)


if __name__ == '__main__':
    main()
