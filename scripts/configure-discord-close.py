"""Configurar saída normal do Discord ao fechar, somente com ele encerrado."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime,timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from therion.autonomy.apps import process_paths


def configure(path,*,running,apply=False):
    path=Path(path)
    if running():raise ValueError('Saia do Discord pela bandeja antes de alterar a preferência.')
    before=path.read_bytes();original=json.loads(before.decode('utf-8-sig'))
    if not isinstance(original,dict):raise ValueError('Configuração do Discord inválida.')
    updated=copy.deepcopy(original);updated['MINIMIZE_TO_TRAY']=False
    report={'preference':'MINIMIZE_TO_TRAY','before':original.get('MINIMIZE_TO_TRAY','default:true'),
            'after':False,'applied':False,'only_this_preference':True}
    if not apply or original==updated:return report
    if running() or path.read_bytes()!=before:raise ValueError('Discord ou configuração mudou durante a revisão.')
    backup=path.with_name('settings.before-close-exit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    backup.write_bytes(before)
    if backup.read_bytes()!=before:raise ValueError('Backup não conferido.')
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.close-exit-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(updated,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        if running() or path.read_bytes()!=before:raise ValueError('Discord ou configuração mudou antes da aplicação.')
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    if json.loads(path.read_text(encoding='utf-8'))!=updated:raise ValueError('Preferência não persistiu.')
    report.update(applied=True,backup=str(backup))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    root=Path(os.environ['LOCALAPPDATA'])/'Discord'
    def running():
        return any(Path(p).name.casefold()=='discord.exe' and Path(p).is_relative_to(root) for p in process_paths())
    report=configure(Path(os.environ['APPDATA'])/'discord/settings.json',running=running,apply=args.apply)
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
