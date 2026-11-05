"""Verificação de nova janela visível pelo executável aprovado, sem automação UI."""
import ctypes
import os
from pathlib import Path


def same_app(expected,actual):
    """Caminhos já normalizados. Instaladores Squirrel (Gemini, Discord) rodam o app real em app-<versão>\\ ao lado do executável cadastrado."""
    if actual==expected:return True
    actual,expected=Path(actual),Path(expected)
    return actual.name==expected.name and actual.parent.parent==expected.parent and actual.parent.name.startswith('app-')


def browser_windows(path, *,visible_only=True):
    if os.name!='nt':raise OSError('Consulta de janelas disponível somente no Windows.')
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=(callback_type,wintypes.LPARAM);user.EnumWindows.restype=wintypes.BOOL
    user.IsWindowVisible.argtypes=(wintypes.HWND,);user.IsWindowVisible.restype=wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.DWORD))
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD);kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=(wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    expected=os.path.normcase(os.path.realpath(path));found=set()
    @callback_type
    def visit(window,_):
        if visible_only and not user.IsWindowVisible(window):return True
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(window,ctypes.byref(pid))
        handle=kernel.OpenProcess(0x1000,False,pid.value)
        if handle:
            try:
                size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)) and same_app(expected,os.path.normcase(os.path.realpath(buffer.value))):
                    found.add(int(window))
            finally:kernel.CloseHandle(handle)
        return True
    if not user.EnumWindows(visit,0):raise OSError('Não foi possível enumerar as janelas.')
    return found


def close_windows(path,windows):
    """Solicita fechamento normal; nunca termina processos ou responde diálogos."""
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.PostMessageW.argtypes=(wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM)
    user.PostMessageW.restype=wintypes.BOOL
    current=browser_windows(path,visible_only=False)
    for window in windows & current:
        if not user.PostMessageW(window,0x0010,0,0):raise OSError('Não confirmei a solicitação de fechamento.')


def closeable_windows(path):
    visible=browser_windows(path)
    if Path(path).name.casefold()!='discord.exe':return visible
    # A janela principal pode estar oculta na bandeja. Não atingir janelas de
    # mensagens internas do Electron; só widgets de aplicativo com título.
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetClassNameW.argtypes=(wintypes.HWND,wintypes.LPWSTR,ctypes.c_int)
    user.GetWindowTextLengthW.argtypes=(wintypes.HWND,);user.GetWindowTextLengthW.restype=ctypes.c_int
    for window in browser_windows(path,visible_only=False)-visible:
        name=ctypes.create_unicode_buffer(128)
        if user.GetClassNameW(window,name,len(name)) and name.value=='Chrome_WidgetWin_1' and user.GetWindowTextLengthW(window)>0:
            visible.add(window)
    return visible
