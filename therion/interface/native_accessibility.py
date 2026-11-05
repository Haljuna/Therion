"""Prepara o core UIA do próprio HWND fora de WM_GETOBJECT síncrono.

Windows pode inicializar BlockingCoreDispatcher em UiaReturnRawElementProvider.
Se a primeira chamada ocorrer dentro de SendMessage, a ativação COM gera
RPC_E_CANTCALLOUT_ININPUTSYNCCALL. Consultar somente o próprio HWND antes de
exibi-lo inicia esse caminho fora da chamada síncrona. A ponte permanece Qt;
nenhuma mensagem/exceção é interceptada e a acessibilidade não é desativada.
"""
import ctypes
import os
import sys
import uuid
import weakref
from ctypes import wintypes

_prepared_app = None


class GUID(ctypes.Structure):
    _fields_=[('Data1',wintypes.DWORD),('Data2',wintypes.WORD),('Data3',wintypes.WORD),('Data4',ctypes.c_ubyte*8)]


def _release(pointer):
    if pointer.value:
        vtable=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG,ctypes.c_void_p)(vtable[2])(pointer)


def _prime_own_element(window):
    user=ctypes.WinDLL('user32',use_last_error=True,winmode=0x800)
    user.InSendMessageEx.argtypes=(ctypes.c_void_p,)
    user.InSendMessageEx.restype=wintypes.DWORD
    if user.InSendMessageEx(None)&1:
        return {'state':'input_sync','hresult':None}
    hwnd=int(window.winId())
    user.GetWindowThreadProcessId.argtypes=(ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype=wintypes.DWORD
    pid=wintypes.DWORD();owner=user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    kernel=ctypes.WinDLL('kernel32',use_last_error=True,winmode=0x800)
    kernel.GetCurrentThreadId.restype=wintypes.DWORD
    if pid.value!=os.getpid() or owner!=kernel.GetCurrentThreadId():
        return {'state':'wrong_owner','hresult':None}
    clsid=GUID.from_buffer_copy(uuid.UUID('ff48dba4-60ef-4201-aa87-54103eef594e').bytes_le)
    iid=GUID.from_buffer_copy(uuid.UUID('30cbe57d-d9d0-452a-ab13-7ac5ac4825ee').bytes_le)
    ole=ctypes.WinDLL('ole32',use_last_error=True,winmode=0x800)
    ole.CoCreateInstance.argtypes=(ctypes.POINTER(GUID),ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p))
    ole.CoCreateInstance.restype=ctypes.c_long
    client=ctypes.c_void_p();element=ctypes.c_void_p()
    try:
        # Qt já inicializou o apartment; não trocar modo COM nem sua segurança.
        result=ole.CoCreateInstance(ctypes.byref(clsid),None,1,ctypes.byref(iid),ctypes.byref(client))
        if result<0 or not client.value:
            return {'state':'unavailable','hresult':result}
        vtable=ctypes.cast(client,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        # IUIAutomation::ElementFromHandle, slot 6 no contrato do Windows SDK.
        get_element=ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p))(vtable[6])
        result=get_element(client,hwnd,ctypes.byref(element))
        return {'state':'prepared' if result>=0 and element.value else 'unavailable','hresult':result}
    finally:
        _release(element)
        _release(client)


def prepare_native_accessibility(window):
    global _prepared_app
    if sys.platform!='win32':
        return {'state':'not_native','hresult':None}
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QThread
    app=QGuiApplication.instance()
    if app is None or app.platformName()!='windows':
        return {'state':'not_native','hresult':None}
    if QThread.currentThread()!=app.thread() or window.thread()!=app.thread():
        return {'state':'wrong_thread','hresult':None}
    if _prepared_app is not None and _prepared_app() is app:
        return {'state':'already_prepared','hresult':0}
    try:
        status=_prime_own_element(window)
    except (OSError,AttributeError) as error:
        return {'state':'unavailable','hresult':None,'error':type(error).__name__}
    if status['state']=='prepared':
        _prepared_app=weakref.ref(app)
    return status
