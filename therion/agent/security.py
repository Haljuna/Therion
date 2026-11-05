"""Diretório privado da conta Windows; não equivale a criptografia."""
from pathlib import Path
import os


def restrict_directory(path):
    path=Path(path)
    if os.name!='nt':
        path.chmod(0o700);return
    import ctypes
    from ctypes import wintypes
    from ctypes.wintypes import DWORD,HANDLE
    advapi=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    token=HANDLE()
    kernel.GetCurrentProcess.restype=HANDLE
    advapi.OpenProcessToken.argtypes=[HANDLE,DWORD,ctypes.POINTER(HANDLE)]
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):raise OSError('Não confirmei a conta Windows do histórico.')
    sid_string=wintypes.LPWSTR();descriptor=ctypes.c_void_p()
    try:
        size=DWORD();advapi.GetTokenInformation.argtypes=[HANDLE,ctypes.c_int,ctypes.c_void_p,DWORD,ctypes.POINTER(DWORD)]
        advapi.GetTokenInformation(token,1,None,0,ctypes.byref(size))
        buffer=ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token,1,buffer,size,ctypes.byref(size)):raise OSError('Conta Windows indisponível.')
        sid=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0]
        advapi.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
        if not advapi.ConvertSidToStringSidW(sid,ctypes.byref(sid_string)):raise OSError('SID indisponível.')
        sddl='D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;'+sid_string.value+')'
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[wintypes.LPCWSTR,DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(DWORD)]
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(descriptor),None):raise OSError('Permissões do histórico inválidas.')
        advapi.SetFileSecurityW.argtypes=[wintypes.LPCWSTR,DWORD,ctypes.c_void_p]
        if not advapi.SetFileSecurityW(str(path),0x80000004,descriptor):raise OSError('Não consegui restringir o diretório à conta Windows.')
    finally:
        kernel.LocalFree.argtypes=[ctypes.c_void_p]
        if sid_string:kernel.LocalFree(ctypes.cast(sid_string,ctypes.c_void_p))
        if descriptor:kernel.LocalFree(descriptor)
        kernel.CloseHandle.argtypes=[HANDLE];kernel.CloseHandle(token)
