"""Amostragem local de RAM do sistema e VRAM; sem processos/arquivos pessoais."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time


def sample():
    result={'timestamp':time.time()}
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in
                ('total_physical','available_physical','total_pagefile','available_pagefile','total_virtual','available_virtual','extended')]
        state=Memory();state.length=ctypes.sizeof(state)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            result.update(ram_total_bytes=state.total_physical,ram_available_bytes=state.available_physical,
                commit_limit_bytes=state.total_pagefile,commit_available_bytes=state.available_pagefile)
    executable=shutil.which('nvidia-smi')
    if executable:
        try:
            command=[executable,'--query-gpu=memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits']
            completed=subprocess.run(command,capture_output=True,text=True,timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if completed.returncode==0:
                result['gpu']=[dict(zip(('used_mib','total_mib','utilization_percent'),map(float,line.split(',')))) for line in completed.stdout.splitlines()]
        except (OSError,ValueError,subprocess.TimeoutExpired):result['gpu_unavailable']=True
    return result


class ResourceSampler:
    def __init__(self,output,*,append=False,interval=5):
        self.output=Path(output);self.append=append;self.interval=interval
        self.stop=threading.Event();self.thread=None

    def start(self):
        self.output.parent.mkdir(parents=True,exist_ok=True)
        stream=self.output.open('a' if self.append else 'x',encoding='utf-8')
        def run():
            try:
                while not self.stop.is_set():
                    stream.write(json.dumps(sample(),ensure_ascii=False)+'\n');stream.flush()
                    self.stop.wait(self.interval)
            finally:stream.close()
        self.thread=threading.Thread(target=run,daemon=True,name='therion-resource-sampler');self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=5)


if __name__=='__main__':print(json.dumps(sample()),flush=True)
