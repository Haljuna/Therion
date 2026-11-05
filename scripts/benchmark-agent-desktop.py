"""Inicialização/encerramento Qt nativos, em processos e perfis fictícios."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def child(args):
    started=time.perf_counter();state=args.state.absolute();state.mkdir(parents=True,exist_ok=False)
    for key in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder=state/key;folder.mkdir();os.environ[key]=str(folder)
    sys.path.insert(0,str(args.source.absolute()))
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAccessible
    from therion.interface.desktop import MainWindow
    metrics={'import_seconds':time.perf_counter()-started}
    class ProbeWindow(MainWindow):
        def paintEvent(self,event):
            metrics.setdefault('first_paint_seconds',time.perf_counter()-started)
            super().paintEvent(event)
    app=QApplication([]);QAccessible.setActive(True)
    config={'runtime':{'real_actions_enabled':False},'calendar':{'enabled':False},
        'ai':{'enabled':False},'voice':{'enabled':False},'tts':{'enabled':False}}
    window=ProbeWindow(app,config=config,config_loader=lambda:config,config_writer=lambda _:None,log_dir=str(state/'logs'))
    metrics['constructed_seconds']=time.perf_counter()-started
    window.show()
    def finish():
        metrics['quit_started']=time.perf_counter()
        window._quit_application()
    QTimer.singleShot(800,finish)
    code=app.exec()
    metrics.update(shutdown_seconds=time.perf_counter()-metrics.pop('quit_started'),exit_code=code,
        native_platform=app.platformName(),accessibility_active=QAccessible.isActive(),source=str(args.source))
    print(json.dumps(metrics),flush=True)
    return code


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',action='store_true');parser.add_argument('--source',type=Path)
    parser.add_argument('--state',type=Path);parser.add_argument('--baseline',type=Path);parser.add_argument('--fixture-root',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.child:return child(args)
    if args.output.exists():raise ValueError('Saída já existe.')
    args.fixture_root.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];rows=[]
    for repeat in range(3):
        for label,source in [('baseline',args.baseline),('current',root)]:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child','--source',str(source),'--state',str(args.fixture_root/(label+'-'+str(repeat)))],
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,env=dict(os.environ,PYTHONIOENCODING='utf-8'),creationflags=subprocess.CREATE_NO_WINDOW)
            diagnostic=args.fixture_root/(label+'-'+str(repeat)+'.log');diagnostic.write_text(result.stderr,encoding='utf-8')
            row={'profile':label,'repeat':repeat,'process_exit':result.returncode,'stderr':str(diagnostic)}
            if result.returncode==0:row.update(json.loads(result.stdout.strip().splitlines()[-1]))
            rows.append(row)
    args.output.write_text(json.dumps({'scope':'Qt nativo com IA/voz/contas desligadas, sem config pessoal; três processos por versão. Não é medição de boot frio do computador.','runs':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows),flush=True)
    return int(any(row['process_exit']!=0 for row in rows))


if __name__=='__main__':raise SystemExit(main())
