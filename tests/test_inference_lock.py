"""Mutex de inferência entre processos, sem chamar modelo ou serviço pessoal."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import pytest
import httpx

from therion.core.inference_lock import ProcessRLock
from therion.agent import AgentRuntime
from therion.agent.registry import ToolRegistry
from therion.agent.ollama import OllamaAgentProvider


@pytest.mark.skipif(os.name!='nt',reason='Mutex nativo da sessão Windows.')
def test_process_mutex_reentrant_and_released(tmp_path):
    name='fixture-'+uuid.uuid4().hex
    lock=ProcessRLock(name)
    child=tmp_path/'probe.py'
    child.write_text('''import sys,json
from therion.core.inference_lock import ProcessRLock
lock=ProcessRLock(sys.argv[1]);acquired=lock.acquire(blocking=False)
print(json.dumps({'acquired':acquired}),flush=True)
if acquired:lock.release()
''',encoding='utf-8')
    def probe():
        process=subprocess.run([sys.executable,str(child),name],capture_output=True,text=True,timeout=10,
            env=dict(os.environ,PYTHONPATH=str(Path.cwd())),creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode==0,process.stderr
        return json.loads(process.stdout)['acquired']
    assert lock.acquire(False) and lock.acquire(False)
    try:
        assert probe() is False
        lock.release();assert probe() is False
    finally:lock.release()
    assert probe() is True


def test_async_calls_on_same_thread_are_serialized():
    active=[0];peak=[0]
    async def transport(request):
        active[0]+=1;peak[0]=max(peak[0],active[0])
        await asyncio.sleep(.04);active[0]-=1
        return httpx.Response(200,content=b'{"message":{"content":"Pronto."},"done":true}\n')
    def factory(**kwargs):return httpx.AsyncClient(transport=httpx.MockTransport(transport),**kwargs)
    async def execute():
        runtimes=[AgentRuntime(OllamaAgentProvider('http://127.0.0.1:11435/api/chat','fixture',protocol='native',client_factory=factory),ToolRegistry()) for _ in range(2)]
        results=await asyncio.gather(*(runtime.run('oi',session_id=str(index)) for index,runtime in enumerate(runtimes)))
        assert all(row.status=='completed' for row in results)
    asyncio.run(execute())
    assert peak[0]==1 and active[0]==0
