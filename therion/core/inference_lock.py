"""Exclusão de inferência entre threads e processos Therion da sessão Windows."""
import ctypes
import hashlib
import os
import threading
import time


class ProcessRLock:
    def __init__(self,name='local-model'):
        self.local=threading.RLock();self.owner=threading.local();self.handle=None
        if os.name=='nt':
            from ctypes import wintypes
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR)
            self.kernel.CreateMutexW.restype=wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
            self.kernel.WaitForSingleObject.restype=wintypes.DWORD
            self.kernel.ReleaseMutex.argtypes=(wintypes.HANDLE,)
            self.kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
            key=hashlib.sha256(name.encode()).hexdigest()
            self.handle=self.kernel.CreateMutexW(None,False,'Local\\TherionInference-'+key)
            if not self.handle:raise OSError('Não consegui criar a exclusão local de inferência.')

    def acquire(self,blocking=True,timeout=-1):
        start=time.monotonic()
        acquired=self.local.acquire(blocking,timeout) if timeout!=-1 else self.local.acquire(blocking)
        if not acquired:return False
        depth=getattr(self.owner,'depth',0)
        if depth:
            self.owner.depth=depth+1;return True
        try:
            if self.handle:
                milliseconds=0 if not blocking else 0xffffffff if timeout==-1 else max(0,int((timeout-(time.monotonic()-start))*1000))
                result=self.kernel.WaitForSingleObject(self.handle,milliseconds)
                if result==258:self.local.release();return False
                if result not in (0,128):raise OSError('Não consegui obter a exclusão local de inferência.')
            self.owner.depth=1;return True
        except BaseException:
            self.local.release();raise

    def release(self):
        depth=getattr(self.owner,'depth',0)
        if not depth:raise RuntimeError('Inferência não pertence a esta thread.')
        self.owner.depth=depth-1
        try:
            if depth==1 and self.handle and not self.kernel.ReleaseMutex(self.handle):raise OSError('Falha ao liberar a exclusão de inferência.')
        finally:self.local.release()

    def __enter__(self):self.acquire();return self
    def __exit__(self,*args):self.release()
    def __del__(self):
        try:
            if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
        except Exception:pass
