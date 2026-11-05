"""Habilitação explícita de inicialização; importação sem efeitos no Windows."""
from pathlib import Path
import ctypes
import os
import subprocess
import sys


def session_unlocked():
    if os.name!='nt':return False
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.OpenInputDesktop.argtypes=(ctypes.c_uint32,ctypes.c_bool,ctypes.c_uint32)
    user.OpenInputDesktop.restype=ctypes.c_void_p
    user.CloseDesktop.argtypes=(ctypes.c_void_p,)
    desktop=user.OpenInputDesktop(0,False,0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desktop:return False
    try:
        # O desktop de entrada Winlogon não é a sessão interativa desbloqueada.
        needed=ctypes.c_uint32()
        buffer=ctypes.create_unicode_buffer(256)
        user.GetUserObjectInformationW.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,
            ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32))
        if not user.GetUserObjectInformationW(desktop,2,buffer,ctypes.sizeof(buffer),ctypes.byref(needed)):
            return False
        return buffer.value.casefold()=='default'
    finally:user.CloseDesktop(desktop)


class StartupShortcut:
    MARKER='Therion V4 managed startup'

    def __init__(self,startup=None,pythonw=None,workspace=None):
        self.startup=Path(startup) if startup else Path(os.environ['APPDATA'])/'Microsoft'/'Windows'/'Start Menu'/'Programs'/'Startup'
        self.path=self.startup/'Therion V4.lnk'
        self.pythonw=Path(pythonw) if pythonw else Path(sys.executable).with_name('pythonw.exe')
        self.workspace=Path(workspace) if workspace else Path(__file__).resolve().parents[2]

    def set_enabled(self,enabled):
        if os.name!='nt':raise ValueError('Inicialização disponível somente no Windows.')
        if not self.pythonw.is_file() or not self.workspace.is_dir():
            raise ValueError('Ambiente instalado não foi localizado.')
        if self.startup.resolve()!=self.path.resolve().parent:
            raise ValueError('Atalho fora da pasta de inicialização escolhida.')
        # Valores vão pelo ambiente, nunca são interpolados em código PowerShell.
        script=r'''$ErrorActionPreference='Stop';
        $w=New-Object -ComObject WScript.Shell;
        $path=$env:THERION_V4_SHORTCUT;
        if (Test-Path -LiteralPath $path) {
          $old=$w.CreateShortcut($path);
          if ($old.Description -ne 'Therion V4 managed startup') { throw 'Atalho não pertence ao Therion V4.' }
        }
        if ($env:THERION_V4_ENABLED -eq '1') {
          $s=$w.CreateShortcut($path);$s.TargetPath=$env:THERION_V4_PYTHON;
          $s.Arguments='-m therion.interface.desktop --start-minimized';
          $s.WorkingDirectory=$env:THERION_V4_WORKSPACE;
          $s.Description='Therion V4 managed startup';$s.WindowStyle=7;$s.Save();
          $check=$w.CreateShortcut($path);
          if ($check.TargetPath -ne $env:THERION_V4_PYTHON -or $check.Arguments -ne $s.Arguments) { throw 'Atalho não confirmado.' }
        } elseif (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
        '''
        env=dict(os.environ,THERION_V4_SHORTCUT=str(self.path),THERION_V4_ENABLED='1' if enabled else '0',
            THERION_V4_PYTHON=str(self.pythonw),THERION_V4_WORKSPACE=str(self.workspace))
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
            env=env,shell=False,capture_output=True,timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode!=0 or self.path.exists()!=bool(enabled):
            raise ValueError('Não confirmei a alteração do atalho de inicialização.')


class SingleInstance:
    """Mutex por usuário, compartilhado pela interface e pela CLI."""
    def __init__(self,name=None):
        self.handle=None
        if os.name!='nt':
            self.acquired=True
            return
        from .policy import fingerprint
        key=name or fingerprint(os.environ.get('APPDATA',''))[:24]
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=(ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p)
        self.kernel.CreateMutexW.restype=ctypes.c_void_p
        self.kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
        ctypes.set_last_error(0)
        self.handle=self.kernel.CreateMutexW(None,False,'Local\\TherionV4-'+key)
        if not self.handle:raise OSError('Não consegui verificar a instância única do Therion.')
        self.acquired=ctypes.get_last_error()!=183

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def build_runtime(loader,writer):
    from .store import EvidenceStore
    from .runtime import AutonomyRuntime
    from therion.config.local import _get_config_path
    import json
    import sqlite3
    def strict_loader():
        path=_get_config_path()
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value,dict):raise ValueError('Configuração local não é um objeto válido.')
        return loader()
    root=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'Therion'/'autonomy'
    try:
        return AutonomyRuntime(EvidenceStore(root/'state.sqlite3'),strict_loader,writer)
    except (OSError,ValueError,sqlite3.Error):
        print('Autonomia V4 indisponível; mantive os fluxos supervisionados.',file=sys.stderr)
        return None
