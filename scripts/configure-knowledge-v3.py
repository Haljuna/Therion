"""Prévia por padrão; --apply requer hash explícito da configuração previamente revisada."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.config.knowledge import configuration_proposal,apply_configuration
from therion.context.second_brain import SecondBrainReader


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default=str(Path(os.environ['APPDATA'])/'Therion'/'config.json'))
    parser.add_argument('--vault',default=SecondBrainReader.DEFAULT_VAULT_ROOT)
    parser.add_argument('--authorization',required=True)
    parser.add_argument('--expires-at',required=True)
    parser.add_argument('--read-all',action='store_true')
    parser.add_argument('--supervised-memory',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-sha256')
    args=parser.parse_args()
    proposal=configuration_proposal(args.config,args.vault,args.authorization,args.expires_at,
        read_all=args.read_all,supervised_memory=args.supervised_memory)
    if args.apply:
        backup=apply_configuration(proposal,args.expected_sha256)
        print('Configuração publicada e verificada. Backup: '+backup)
    else:
        print('Somente prévia; nada foi alterado.')
    print(json.dumps(dict(config=proposal['path'],sha256=proposal['sha256'],
        knowledge_access=proposal['policy'],read_scope=proposal['vault'],
        write_scope='90 - Sistema da IA/Notas de Rascunho da IA/Registros',
        per_session=3,per_day=10,review_days=30,
        ai_model=proposal['updated'].get('ai',{}).get('model'),
        voice=proposal['updated'].get('tts',{}).get('voice')),ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
