"""Telemetria opcional da fixture: estados/contadores, nunca conteúdo da conversa."""
from collections import Counter
import ctypes
import json
import os
from pathlib import Path
import threading
import time

from PySide6.QtCore import QTimer


def private_memory(pid):
    if os.name!='nt' or type(pid) is not int or pid<=0:return None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
    kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return None
    try:
        class Counters(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in
                ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
        value=Counters();value.cb=ctypes.sizeof(value)
        query=ctypes.WinDLL('psapi').GetProcessMemoryInfo
        query.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
        return int(value.private) if query(handle,ctypes.byref(value),value.cb) else None
    finally:kernel.CloseHandle(handle)


def owned_tts_memory(speech, memory_reader):
    """Consultar somente handles já retidos pelo TTS; não adotar novos PIDs.

    O QProcess pode ser o redirecionador de venv. Não confundir sua memória
    pequena com a do Python que executa Kokoro. Identidade inclui criação.
    """
    process=getattr(speech,'process',None)
    tree=getattr(speech,'_process_trees',{}).get(process)
    if tree is None or tree.closed:return []
    rows=[]
    for pid,handle in list(tree.handles.items()):
        try:
            if tree.api.WaitForSingleObject(handle,0)!=258:continue
            created=tree._created(handle)
            size=memory_reader(pid)
            # O handle original vivo antes/depois evita consultar PID reutilizado.
            if tree.api.WaitForSingleObject(handle,0)!=258:continue
            rows.append({'pid':pid,'created':created,'private_bytes':size,'root':pid==tree.root})
        except (OSError,ValueError):continue
    return rows


def summarize(rows):
    if not rows:return {'samples':0,'duration_seconds':0,'memory_after_5min':{},'acceptance':'requires_review'}
    groups={};first_seen={}
    for row in rows:
        for label in ('ui','tts'):
            pid=row.get(label+'_pid');size=row.get(label+'_private_bytes')
            if type(pid) is not int or type(size) is not int:continue
            key=label+':'+str(pid);first_seen.setdefault(key,row['elapsed_seconds'])
            if row['elapsed_seconds']-first_seen[key]>=300:
                groups.setdefault(key,[]).append((row['elapsed_seconds'],size))
        for process in row.get('tts_processes',[]):
            pid,created,size=process.get('pid'),process.get('created'),process.get('private_bytes')
            if any(type(value) is not int for value in (pid,created,size)):continue
            key=f'tts_process:{pid}:{created}'
            first_seen.setdefault(key,row['elapsed_seconds'])
            if row['elapsed_seconds']-first_seen[key]>=300:
                groups.setdefault(key,[]).append((row['elapsed_seconds'],size))
    memory={key:{'samples':len(points),'first_bytes':points[0][1],'last_bytes':points[-1][1],
        'min_bytes':min(size for _,size in points),'max_bytes':max(size for _,size in points),
        'span_seconds':points[-1][0]-points[0][0]} for key,points in groups.items()}
    return {'samples':len(rows),'duration_seconds':rows[-1]['elapsed_seconds'],
        'phase_samples':dict(Counter(row['speech_state'] for row in rows)),
        'conversation_samples':sum(row['conversation'] for row in rows),
        'runtime_terminals':rows[-1]['event_counts'].get('terminal',0),
        'memory_after_5min':memory,'acceptance':'requires_review',
        'tts_descendants_observed':any(any(not process.get('root',True) for process in row.get('tts_processes',[])) for row in rows),
        'limits':['Tempo decorrido sozinho não comprova conversa ativa nem estabilidade.',
            'Memória é separada por PID, sem somar processos sucessivos como crescimento.',
            'tts_private_bytes mede o lançador; o motor real está em tts_processes por PID e criação.',
            'Não mede qualidade auditiva nem comprova residência contínua do Ollama.']}


class VoiceSessionMetrics:
    EVENTS=frozenset({'thinking','tool_started','tool_finished','terminal','decision_rejected'})

    def __init__(self,window,root,*,clock=time.monotonic,memory_reader=private_memory):
        self.window=window;self.root=Path(root);self.clock=clock;self.memory_reader=memory_reader
        self.started=clock();self.started_unix=time.time();self.counts=Counter();self.lock=threading.Lock();self.closed=False
        self.system_sampler=None
        self.path=self.root/'voice-session-metrics.jsonl';self.stream=self.path.open('x',encoding='utf-8')
        self.original=window._orchestrator._emit_agent_event
        def observe(event):
            self.original(event)
            if event.type in self.EVENTS:
                with self.lock:
                    if not self.closed:self.counts[event.type]+=1
        self.observer=observe;window._orchestrator._emit_agent_event=observe
        self.timer=QTimer(window);self.timer.setInterval(1000);self.timer.timeout.connect(self.sample)
        self.timer.start();self.sample()

    def sample(self):
        if self.closed:return
        window=self.window;speech=getattr(window,'_speech_output',None)
        process=getattr(speech,'process',None)
        tts_pid=int(process.processId()) if process is not None else None
        if not tts_pid:tts_pid=None
        state=getattr(speech,'state',None)
        if state not in {'idle','warming','synthesizing','playing'}:state='unavailable'
        tts_processes=owned_tts_memory(speech,self.memory_reader)
        sizes=[process['private_bytes'] for process in tts_processes]
        with self.lock:counts=dict(self.counts)
        row={'elapsed_seconds':round(self.clock()-self.started,3),'ui_pid':os.getpid(),'tts_pid':tts_pid,
            'ui_private_bytes':self.memory_reader(os.getpid()),
            'tts_private_bytes':self.memory_reader(tts_pid) if tts_pid is not None else None,
            'tts_processes':tts_processes,
            'tts_tree_private_bytes':sum(sizes) if sizes and all(type(size) is int for size in sizes) else None,
            'conversation':getattr(window,'_conversation_mode',False) is True,
            'processing':getattr(window,'_processing',False) is True,'speech_state':state,
            'stt_ready':getattr(getattr(window,'_voice_service',None),'state',None)=='ready',
            'tts_ready':getattr(speech,'is_ready',False) is True,'event_counts':counts}
        # Não reter amostras no processo medido: isso fabricaria crescimento de RAM.
        self.stream.write(json.dumps(row,ensure_ascii=False)+'\n');self.stream.flush()

    def close(self):
        if self.closed:return
        self.timer.stop();self.sample()
        with self.lock:self.closed=True
        host=self.window._orchestrator
        if host._emit_agent_event is self.observer:host._emit_agent_event=self.original
        self.stream.close()
        if self.system_sampler is not None:self.system_sampler.close()
        rows=[json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]
        report=summarize(rows);report['started_unix']=self.started_unix
        report['system_resources_file']='voice-session-system.jsonl' if self.system_sampler is not None else None
        config=self.window._config
        report['fixture_profile']={
            'model':config.get('ai',{}).get('model'),'voice':config.get('tts',{}).get('voice'),
            'tts_provider':config.get('tts',{}).get('provider'),
            'tts_memory_efficient':config.get('tts',{}).get('memory_efficient') is True,
            'streaming_prepare':config.get('tts',{}).get('streaming_prepare') is True}
        (self.root/'voice-session-metrics.summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
