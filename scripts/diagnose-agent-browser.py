"""Diagnóstico de execução do navegador, sem perfil pessoal ou site externo."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--executable',type=Path,required=True);parser.add_argument('--fixture-root',type=Path,required=True)
    args=parser.parse_args();args.fixture_root.mkdir(parents=True,exist_ok=False)
    process=None;tree=None;result={}
    try:
        process=subprocess.Popen([str(args.executable),'--headless','--disable-gpu','--disable-background-networking',
            '--no-first-run','--no-default-browser-check','--disable-sync','--user-data-dir='+str(args.fixture_root/'profile'),
            '--dump-dom','about:blank'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from therion.voice.process_tree import OwnedProcessTree
        tree=OwnedProcessTree(process.pid)
        output,error=process.communicate(timeout=15)
        result={'exit':process.returncode,'stdout':output.decode(errors='replace')[-500:],'stderr':error.decode(errors='replace')[-1000:]}
    except OSError as error:result={'type':type(error).__name__,'winerror':getattr(error,'winerror',None),'error':str(error)}
    finally:
        if tree:tree.close()
        if process is not None:
            if process.poll() is None:process.kill()
            process.wait(timeout=5)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
