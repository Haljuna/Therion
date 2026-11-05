"""Execução síncrona cooperativa limitada; threads tardias não publicam resultados."""
import asyncio
import queue
import threading

_slot=threading.BoundedSemaphore(1)


async def cooperative_call(function,*args,token=None,**kwargs):
    if token:token.check()
    if not _slot.acquire(blocking=False):
        raise RuntimeError('Uma operação síncrona anterior ainda está encerrando.')
    result=queue.SimpleQueue()
    def execute():
        try:result.put((True,function(*args,**kwargs)))
        except BaseException as error:result.put((False,error))
        finally:_slot.release()
    threading.Thread(target=execute,daemon=True,name='therion-controlled-tool').start()
    while True:
        if token:token.check()
        try:ok,value=result.get_nowait()
        except queue.Empty:
            await asyncio.sleep(.02);continue
        if token:token.check()
        if not ok:raise value
        return value
