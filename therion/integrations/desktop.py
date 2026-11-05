"""UI Automation em worker; identidade de processo e janela obrigatórias."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import time
from .verification import expectation,matches,protected_action

# wt.exe só lança o Windows Terminal; a janela é do WindowsTerminal.exe/OpenConsole.exe.
FORBIDDEN_EXECUTABLES={'cmd.exe','powershell.exe','pwsh.exe','wt.exe','windowsterminal.exe','openconsole.exe','conhost.exe',
    'powershell_ise.exe','taskmgr.exe','mmc.exe','regedit.exe','consent.exe','credentialuibroker.exe','logonui.exe','winlogon.exe'}
BROWSER_EXECUTABLES={'chrome.exe','msedge.exe','firefox.exe','brave.exe','opera.exe','vivaldi.exe'}


def process_identity(pid):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:raise ValueError('Processo não acessível; não atravesso elevação.')
    try:
        buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
        kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):raise ValueError('Identidade do processo não confirmada.')
        created,exited,kernel_time,user_time=wintypes.FILETIME(),wintypes.FILETIME(),wintypes.FILETIME(),wintypes.FILETIME()
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kernel_time),ctypes.byref(user_time)):
            raise ValueError('Criação do processo não confirmada.')
        return os.path.normcase(os.path.realpath(buffer.value)), (created.dwHighDateTime<<32)|created.dwLowDateTime
    finally:
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle(handle)


class DesktopSession:
    def __init__(self,config):self.config=config

    def window(self,args):
        target=self.config.get('targets',{}).get(args['target_id'])
        if target and os.path.basename(target['path']).casefold() in BROWSER_EXECUTABLES:
            raise ValueError('Navegadores usam somente a capacidade Navegador com perfil próprio; não controlo o perfil principal por UIA.')
        if target and (target['pid'] in self.config.get('blocked_pids',[]) or os.path.basename(target['path']).casefold() in FORBIDDEN_EXECUTABLES):
            raise ValueError('Não controlo a própria aplicação, terminais ou diálogos de credenciais/elevação.')
        if not target or process_identity(target['pid'])!=(os.path.normcase(os.path.realpath(target['path'])),target.get('created')):
            raise ValueError('Aplicativo mudou ou não está aprovado.')
        from pathlib import Path
        if hashlib.sha256(Path(target['path']).read_bytes()).hexdigest()!=target.get('sha256'):
            raise ValueError('Executável mudou desde a seleção.')
        from pywinauto.application import Application
        return Application(backend='uia').connect(process=target['pid'],timeout=5).window(handle=target['handle']).wrapper_object()

    def snapshot(self,args):
        window=self.window(args)
        rows=[]
        for index,item in enumerate(window.descendants()[:100]):
            if item.element_info.control_type not in {'Button','Edit','Text','CheckBox','ComboBox'}:continue
            if item.element_info.element.CurrentIsPassword:continue
            rows.append({'id':str(index),'text':item.window_text()[:300],'type':item.element_info.control_type,
                'value':item.get_value()[:4000] if item.element_info.control_type=='Edit' else '',
                'runtime_id':list(item.element_info.runtime_id)})
        return {'title':window.window_text(),'controls':rows,'version':hashlib.sha256(json.dumps([window.handle,window.window_text(),rows],sort_keys=True).encode()).hexdigest()}

    def dispatch(self,operation,args):
        if operation=='inventory':return self.inventory()
        if operation=='read':return self.snapshot(args)
        before=self.snapshot(args)
        if args['version']!=before['version']:raise ValueError('Janela mudou desde a prévia.')
        row=next((item for item in before['controls'] if item['id']==args['control_id']),None)
        if row is None:raise ValueError('Controle inacessível ou não selecionado.')
        if protected_action(row['text']):raise ValueError('Credenciais, segurança, compras, pagamentos e exclusão permanente exigem execução manual fora desta capacidade.')
        target=self.config['targets'][args['target_id']]
        if operation not in target.get('actions',[]):raise ValueError('Ação não aprovada para este aplicativo.')
        item=next((item for item in self.window(args).descendants()
                   if list(item.element_info.runtime_id)==row['runtime_id']),None)
        if item is None:raise ValueError('Controle original não está mais disponível.')
        expected=expectation(args) if operation=='click' else None
        if expected and matches(before,expected):return dict(before,action_observed=False,already_satisfied=True)
        if operation=='fill' and row['type']=='Edit':item.set_edit_text(args['text'])
        elif operation=='click' and row['type']=='Button':item.invoke()
        else:raise ValueError('Combinação de controle e ação não suportada.')
        deadline=time.monotonic()+3
        while True:
            after=self.snapshot(args)
            after['action_observed']=matches(after,expected) if expected else any(
                control['runtime_id']==row['runtime_id'] and control['value']==args['text'] for control in after['controls'])
            if after['action_observed'] or time.monotonic()>=deadline:return after
            time.sleep(.05)

    def close(self):pass

    def inventory(self):
        from pywinauto import Desktop
        from pathlib import Path
        rows=[]
        for window in Desktop(backend='uia').windows():
            try:
                if not window.is_visible() or not window.window_text():continue
                pid=window.process_id();path,created=process_identity(pid)
                if pid in self.config.get('blocked_pids',[]) or Path(path).name.casefold() in FORBIDDEN_EXECUTABLES|BROWSER_EXECUTABLES:continue
                rows.append({'pid':pid,'path':path,'created':created,'handle':window.handle,'title':window.window_text(),
                    'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'actions':['read','click','fill']})
            except (OSError,ValueError,RuntimeError):continue
        return rows[:100]
