"""Ownership de uma árvore criada pelo chamador; nunca procura por nome.

Windows Job Object encerra filhos presentes/futuros. Handles retidos evitam
confundir PIDs reutilizados. A enumeração conserva apenas PID e parentesco.
"""
import ctypes
from ctypes import wintypes as W
import os


class ProcessEntry(ctypes.Structure):
    _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',ctypes.c_size_t),('module',W.DWORD),
        ('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('name',W.WCHAR*260)]


class Limits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',W.DWORD),
        ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',W.DWORD),('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_=[('basic',Limits),('io',ctypes.c_ulonglong*6),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
        ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]


class Accounting(ctypes.Structure):
    _fields_=[('times',ctypes.c_longlong*4),('faults',W.DWORD),('total',W.DWORD),('active',W.DWORD),('terminated',W.DWORD)]


class OwnedProcessTree:
    def __init__(self,pid,*,max_memory_bytes=None):
        if os.name!='nt' or type(pid) is not int or pid<=0 or pid==os.getpid():raise ValueError('Árvore precisa de PID de filho próprio no Windows.')
        if max_memory_bytes is not None and (type(max_memory_bytes) is not int or max_memory_bytes<32*1024**2):raise ValueError('Limite de memória inválido.')
        self.root=pid;self.handles={};self.job=None;self.assigned=set();self.closed=False
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,arguments,result in [
            ('OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),('CloseHandle',[W.HANDLE],W.BOOL),
            ('GetProcessTimes',[W.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p],W.BOOL),
            ('WaitForSingleObject',[W.HANDLE,W.DWORD],W.DWORD),('TerminateProcess',[W.HANDLE,W.UINT],W.BOOL),
            ('CreateJobObjectW',[ctypes.c_void_p,W.LPCWSTR],W.HANDLE),('SetInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD],W.BOOL),
            ('AssignProcessToJobObject',[W.HANDLE,W.HANDLE],W.BOOL),('TerminateJobObject',[W.HANDLE,W.UINT],W.BOOL),
            ('QueryInformationJobObject',[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p],W.BOOL),
            ('CreateToolhelp32Snapshot',[W.DWORD,W.DWORD],W.HANDLE),('Process32FirstW',[W.HANDLE,ctypes.POINTER(ProcessEntry)],W.BOOL),
            ('Process32NextW',[W.HANDLE,ctypes.POINTER(ProcessEntry)],W.BOOL)]:
            function=getattr(self.api,name);function.argtypes=arguments;function.restype=result
        root=self.api.OpenProcess(0x101101,False,pid)
        if not root:raise OSError('Não confirmei o processo filho para acompanhar seu encerramento.')
        self.handles[pid]=root
        try:
            self.created=self._created(root)
            self.job=self.api.CreateJobObjectW(None,None)
            if self.job:
                limits=ExtendedLimits();limits.basic.flags=0x2000
                if max_memory_bytes is not None:
                    limits.basic.flags|=0x200;limits.job_memory=max_memory_bytes
                if not self.api.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                    self.api.CloseHandle(self.job);self.job=None
            self._assign(pid,root)
            if max_memory_bytes is not None and (not self.job or pid not in self.assigned):
                raise OSError('Não consegui aplicar o limite de memória ao worker; operação não iniciada.')
            self.capture()
        except BaseException:
            # Construção incompleta não pode deixar handles ou filhos órfãos.
            if self.job:
                self.api.TerminateJobObject(self.job,1);self.api.CloseHandle(self.job);self.job=None
            for handle in self.handles.values():self.api.CloseHandle(handle)
            self.handles.clear();self.closed=True
            raise

    def _created(self,handle):
        fields=[W.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(handle,*[ctypes.byref(value) for value in fields]):raise OSError('Não confirmei a identidade temporal do processo.')
        return fields[0].dwHighDateTime*2**32+fields[0].dwLowDateTime

    def _parents(self):
        snapshot=self.api.CreateToolhelp32Snapshot(2,0)
        if not snapshot or snapshot==ctypes.c_void_p(-1).value:raise OSError('Não consegui verificar os filhos do processo de voz.')
        try:
            row=ProcessEntry();row.size=ctypes.sizeof(row);result={}
            more=self.api.Process32FirstW(snapshot,ctypes.byref(row))
            while more:
                result[row.pid]=row.parent;more=self.api.Process32NextW(snapshot,ctypes.byref(row))
            return result
        finally:self.api.CloseHandle(snapshot)

    def _descendants(self,parents):
        selected={self.root}
        while True:
            expanded=selected|{pid for pid,parent in parents.items() if parent in selected}
            if expanded==selected:return selected
            selected=expanded

    def _assign(self,pid,handle):
        if self.job and pid not in self.assigned and self.api.AssignProcessToJobObject(self.job,handle):self.assigned.add(pid)

    def capture(self):
        if self.closed:return
        # Primeiro associar os pais; novos filhos passam a herdar o job.
        for _ in range(2):
            parents=self._parents();remaining=self._descendants(parents)-set(self.handles)
            while remaining:
                ready={pid for pid in remaining if parents.get(pid) in self.handles}
                if not ready:break
                for pid in ready:
                    handle=self.api.OpenProcess(0x101101,False,pid)
                    if handle:
                        try:
                            valid=self._created(handle)>=self.created and pid in self._descendants(self._parents())
                        except OSError:valid=False
                        if valid:self.handles[pid]=handle;self._assign(pid,handle)
                        else:self.api.CloseHandle(handle)
                remaining-=ready

    @property
    def is_quiescent(self):
        if self.closed:return True
        if any(self.api.WaitForSingleObject(handle,0)!=0 for handle in self.handles.values()):return False
        if self.job:
            count=Accounting()
            if not self.api.QueryInformationJobObject(self.job,1,ctypes.byref(count),ctypes.sizeof(count),None):return False
            if count.active:return False
        return True

    def terminate(self):
        if self.closed:return
        try:self.capture()
        except OSError:self.capture_failed=True
        if self.job:self.api.TerminateJobObject(self.job,1)
        for handle in self.handles.values():
            if self.api.WaitForSingleObject(handle,0)!=0:self.api.TerminateProcess(handle,1)

    def close(self):
        if self.closed:return
        try:self.terminate()
        finally:
            if self.job:self.api.CloseHandle(self.job);self.job=None
            for handle in self.handles.values():self.api.CloseHandle(handle)
            self.handles.clear();self.closed=True
