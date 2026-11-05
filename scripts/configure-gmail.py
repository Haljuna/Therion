"""OAuth Gmail explícito, tokens separados; não executado na instalação."""
from pathlib import Path
import argparse
import os
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    from google_auth_oauthlib.flow import InstalledAppFlow
    from therion.integrations.gmail import SCOPES
    parser=argparse.ArgumentParser(description='Conectar Gmail somente após escolha explícita do usuário.')
    parser.add_argument('--credentials',required=True,type=Path)
    parser.add_argument('--mode',choices=SCOPES,default='read')
    parser.add_argument('--state-root',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'Therion'/'agent'/'credentials')
    args=parser.parse_args()
    scopes=[SCOPES['read']]
    if args.mode!='read':scopes.append(SCOPES[args.mode])
    credentials=InstalledAppFlow.from_client_secrets_file(str(args.credentials),scopes).run_local_server(port=0,timeout_seconds=180)
    args.state_root.mkdir(parents=True,exist_ok=True)
    from therion.agent.security import restrict_directory
    restrict_directory(args.state_root)
    target=args.state_root/'gmail-token.json'
    temp=target.with_suffix('.tmp');temp.write_text(credentials.to_json(),encoding='utf-8');os.replace(temp,target)
    print('Token Gmail salvo separadamente. Nenhuma mensagem foi lida ou enviada.')


if __name__=='__main__':main()
