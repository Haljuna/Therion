"""Worker próprio via JSONL, com timeout e encerramento da árvore possuída."""
import json
import os
import queue
import subprocess
import sys
import threading
from copy import deepcopy
import time
import uuid
from collections import deque
from pathlib import Path


class WorkerOperationError(ValueError):
    """Recusa do adapter: mantém a sessão para nova observação."""


class OwnedWorker:
    def __init__(self, kind, config, *, max_response_chars=2_000_000):
        self.kind, self.config = kind, deepcopy(config)
        self.process = None
        self.tree=None
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.errors = deque(maxlen=8)
        self.max_response_chars=max_response_chars

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return
        root = Path(__file__).resolve().parents[2]
        env={key:value for key,value in os.environ.items() if key.upper() in {
            'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA',
            'PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','COMSPEC'}}
        env['PYTHONIOENCODING']='utf-8'
        browser_path=os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
        if browser_path:env['PLAYWRIGHT_BROWSERS_PATH']=browser_path
        self.queue = queue.Queue()
        self.process=subprocess.Popen([sys.executable,'-m','therion.integrations.worker',self.kind],
            cwd=root,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',bufsize=1,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        process, output = self.process, self.queue
        if os.name=='nt':
            from therion.voice.process_tree import OwnedProcessTree
            try:
                # O filho aguarda o primeiro JSON antes de importar adapters.
                # Limita também parsers/MCP e descendentes do navegador.
                self.tree=OwnedProcessTree(process.pid,max_memory_bytes=(2048 if self.kind=='browser' else 512)*1024**2)
            except BaseException:
                self.close();raise
        self.errors.clear()
        def errors():
            for line in process.stderr:self.errors.append(line.strip()[:500])
        threading.Thread(target=errors,daemon=True).start()
        def read():
            while True:
                line=process.stdout.readline(self.max_response_chars+1)
                if not line:break
                if len(line)>self.max_response_chars:
                    output.put({'error':'Resposta de worker acima do limite.','fatal':True});break
                try:output.put(json.loads(line))
                except ValueError:continue
            output.put({'error':'Worker encerrado. '+' '.join(self.errors)[-1000:]})
        threading.Thread(target=read,daemon=True).start()

    def call(self, operation, arguments, token, timeout=30):
        with self.lock:
            token.check();self.start()
            identifier=uuid.uuid4().hex
            self.process.stdin.write(json.dumps({'id':identifier,'operation':operation,
                'arguments':arguments,'config':self.config},ensure_ascii=False)+'\n')
            self.process.stdin.flush()
            deadline=time.monotonic()+timeout
            try:
                while time.monotonic()<deadline:
                    token.check()
                    try:row=self.queue.get(timeout=.05)
                    except queue.Empty:continue
                    if row.get('id') not in (None,identifier):continue
                    if row.get('error'):
                        if row.get('fatal'):self.close()
                        raise WorkerOperationError(row['error'])
                    return row['result']
                raise TimeoutError('Worker excedeu o prazo.')
            except WorkerOperationError:
                raise
            except BaseException:
                self.close();raise

    def close(self):
        process,self.process=self.process,None
        tree,self.tree=self.tree,None
        if tree:tree.close()
        if process is None:return
        if process.poll() is None:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                    timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            else:process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream:stream.close()
