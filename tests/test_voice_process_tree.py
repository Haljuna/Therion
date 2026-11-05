"""Somente subprocessos de fixture; nenhum processo pessoal é selecionado."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import pytest

from therion.voice.process_tree import OwnedProcessTree


@pytest.mark.skipif(os.name!='nt',reason='Ownership nativo Windows.')
def test_owned_tree_terminates_existing_children_and_preserves_sibling(tmp_path):
    fixture=tmp_path/'parent.py'
    fixture.write_text('''import subprocess,sys,json,time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'child':child.pid}),flush=True)
time.sleep(120)
''',encoding='utf-8')
    parent=subprocess.Popen([sys.executable,str(fixture)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    sibling=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    tree=None;sibling_tree=OwnedProcessTree(sibling.pid)
    try:
        rows=queue.Queue();threading.Thread(target=lambda:rows.put(parent.stdout.readline()),daemon=True).start()
        child=json.loads(rows.get(timeout=5))['child'];tree=OwnedProcessTree(parent.pid)
        assert child in tree.handles and parent.pid in tree.assigned
        tree.terminate();deadline=time.monotonic()+3
        while not tree.is_quiescent and time.monotonic()<deadline:time.sleep(.01)
        assert tree.is_quiescent
        parent.wait(timeout=3)
        assert sibling.poll() is None
    finally:
        if tree:tree.close()
        elif parent.poll() is None:OwnedProcessTree(parent.pid).close()
        sibling_tree.close();sibling.wait(timeout=3)
        parent.wait(timeout=3);parent.stdout.close()


@pytest.mark.skipif(os.name!='nt',reason='Limite nativo Windows.')
def test_owned_worker_memory_limit_refuses_large_allocation():
    code="import sys; sys.stdin.readline()\ntry:\n data=bytearray(256*1024**2); print('unlimited',flush=True)\nexcept MemoryError:\n print('limited',flush=True)"
    process=subprocess.Popen([sys.executable,'-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    tree=OwnedProcessTree(process.pid,max_memory_bytes=64*1024**2)
    try:
        output,error=process.communicate('start\n',timeout=5)
        assert output.strip()=='limited' and process.returncode==0,error
    finally:
        tree.close()
        if process.poll() is None:process.kill();process.wait(timeout=3)
