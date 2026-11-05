"""Inventário técnico sem enumeração de arquivos, contas ou processos pessoais."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise ValueError('Inventário já existe; escolha outro nome.')
    from agent_resources import sample
    report={'timestamp':time.time(),'python':sys.version,'platform':platform.platform(),'logical_cpus':os.cpu_count(),'resources':sample(),'packages':{},'volumes':{}}
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            report['cpu_name']=winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
    for package in ('PySide6','httpx','faster-whisper','ctranslate2','numpy','onnxruntime','google-api-python-client','playwright','pywinauto','pypdf','python-docx','openpyxl','reportlab'):
        try:report['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:report['packages'][package]=None
    for volume in ('C:/','F:/'):
        usage=shutil.disk_usage(volume);report['volumes'][volume]={'total_bytes':usage.total,'free_bytes':usage.free}
    if shutil.which('nvidia-smi'):
        reply=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        report['gpu_inventory']=reply.stdout.strip() if reply.returncode==0 else 'unavailable'
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
