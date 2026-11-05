"""Catálogo aprovado e lançamento sem shell ou argumentos do modelo."""
from dataclasses import dataclass, replace
from pathlib import Path
import ctypes
import hashlib
import os
import subprocess
import uuid

from therion.memory.knowledge import safe_path
from .policy import fingerprint


_TERMINALS = {'cmd.exe', 'powershell.exe', 'pwsh.exe', 'wscript.exe', 'cscript.exe',
    'mshta.exe', 'rundll32.exe', 'regsvr32.exe', 'python.exe', 'pythonw.exe',
    'node.exe', 'bash.exe', 'wsl.exe', 'wt.exe', 'windowsterminal.exe', 'conhost.exe'}


def executable_identity(path):
    path = Path(path)
    if (not path.is_absolute() or str(path).startswith(('\\\\', '//'))
            or path.suffix.casefold() != '.exe' or path.name.casefold() in _TERMINALS):
        raise ValueError('Selecione um aplicativo .exe local; terminais e scripts não são aceitos.')
    safe_path(path, (str(path.parent),))
    if not path.is_file():
        raise ValueError('Executável ausente.')
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    after = path.stat()
    if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
        raise ValueError('O executável mudou durante a validação.')
    return dict(path=os.path.normcase(str(path.resolve())), sha256=digest.hexdigest(),
        size=after.st_size)


@dataclass(frozen=True)
class Application:
    id: str
    name: str
    aliases: tuple[str, ...]
    path: str
    identity: dict
    source: str = 'manual'

    def as_dict(self):
        return dict(self.__dict__, aliases=list(self.aliases))

    @classmethod
    def parse(cls, row):
        if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip()
                for k in ('id','name','path','source')) or not isinstance(row.get('identity'),dict)
                or not isinstance(row.get('aliases'),list)
                or any(not isinstance(a,str) or not a.strip() for a in row['aliases'])):
            raise ValueError('Cadastro de aplicativo inválido.')
        return cls(row['id'],row['name'],tuple(row['aliases']),row['path'],row['identity'],row['source'])


@dataclass(frozen=True)
class ApplicationBatch:
    applications: tuple[Application, ...]
    catalog_version: str


class ApplicationCatalog:
    def __init__(self, runtime):
        self.runtime = runtime

    def entries(self):
        rows = self.runtime.section().get('applications', [])
        if not isinstance(rows,list):
            raise ValueError('Catálogo inválido.')
        entries = [Application.parse(row) for row in rows]
        if len({a.id for a in entries}) != len(entries):
            raise ValueError('Identificadores duplicados no catálogo.')
        return entries

    def resolve(self, name):
        name = name.strip().casefold()
        return [a for a in self.entries() if name in {a.id.casefold(), a.name.casefold(),
            *(alias.casefold() for alias in a.aliases)}]

    def register(self, name, path, aliases=(), source='manual'):
        if not isinstance(name,str) or not name.strip() or len(name)>100:
            raise ValueError('Informe um nome de aplicativo com até cem caracteres.')
        identity = executable_identity(path)
        aliases = tuple(a.strip() for a in aliases if a.strip())
        current = self.entries()
        existing = next((a for a in current if a.identity.get('path') == identity['path']),None)
        app = Application(existing.id if existing else uuid.uuid4().hex,name.strip(),aliases,
            identity['path'],identity,source)
        def update(section):
            rows = section.setdefault('applications', [])
            rows[:] = [a for a in rows if a['id'] != app.id] + [app.as_dict()]
        self.runtime._update(update)
        if existing:
            self.runtime.revoke('open_app',app.id)
        return app

    def remove(self, identifier):
        # Revogar primeiro: uma falha de persistência nunca deixa um grant utilizável.
        self.runtime.revoke('open_app',identifier)
        self.runtime._update(lambda s: s.update(applications=[a for a in s.get('applications',[])
            if a['id'] != identifier]))

    def valid(self, app):
        return any(a == app for a in self.entries()) and executable_identity(app.path) == app.identity

    @staticmethod
    def _aliases(aliases):
        if not isinstance(aliases,(list,tuple)) or any(not isinstance(a,str) for a in aliases):
            raise ValueError('Apelidos inválidos.')
        cleaned={a.strip().casefold():a.strip() for a in aliases if a.strip()}
        if any(len(a)>100 for a in cleaned.values()):
            raise ValueError('Cada apelido deve ter até cem caracteres.')
        return tuple(cleaned.values())

    @staticmethod
    def _check_aliases(entries,changed_ids=None):
        for app in entries:
            for alias in app.aliases:
                if any(other.id!=app.id and (changed_ids is None or app.id in changed_ids or other.id in changed_ids) and alias.casefold() in
                        {other.name.casefold(),*(a.casefold() for a in other.aliases)} for other in entries):
                    raise ValueError(f'O apelido “{alias}” já identifica outro aplicativo.')

    def preview_many(self,rows):
        if not rows:raise ValueError('Selecione pelo menos um aplicativo.')
        current=self.entries();before=fingerprint([app.as_dict() for app in current])
        paths={app.identity['path'] for app in current};added=[]
        for row in rows:
            name=row.get('name','').strip()
            if not name or len(name)>100:raise ValueError('Informe nomes com até cem caracteres.')
            identity=executable_identity(row.get('path',''))
            if identity['path'] in paths:continue
            app=Application(uuid.uuid4().hex,name,self._aliases(row.get('aliases',())),
                identity['path'],identity,row.get('source','manual'))
            Application.parse(app.as_dict())
            paths.add(identity['path']);added.append(app)
        if not added:raise ValueError('Os aplicativos selecionados já estão cadastrados.')
        self._check_aliases(current+added,{app.id for app in added})
        return ApplicationBatch(tuple(added),before)

    def commit_many(self,proposal):
        if not isinstance(proposal,ApplicationBatch) or not proposal.applications:
            raise ValueError('Prévia de cadastro inválida.')
        def update(section):
            current=self.entries()
            if fingerprint([app.as_dict() for app in current])!=proposal.catalog_version:
                raise ValueError('O catálogo mudou. Revise a seleção novamente.')
            additions=list(proposal.applications)
            for app in additions:
                Application.parse(app.as_dict())
                if executable_identity(app.path)!=app.identity:
                    raise ValueError(f'{app.name} mudou desde a prévia. Nenhum aplicativo foi adicionado.')
            if len({a.identity['path'] for a in current+additions})!=len(current+additions):
                raise ValueError('A prévia contém caminhos duplicados.')
            if len({a.id for a in current+additions})!=len(current+additions):
                raise ValueError('A prévia contém identificadores duplicados.')
            self._check_aliases(current+additions,{app.id for app in additions})
            section['applications']=[a.as_dict() for a in current+additions]
        self.runtime._update(update)
        return proposal.applications

    def update_aliases(self,app,aliases):
        updated=replace(app,aliases=self._aliases(aliases))
        def update(section):
            current=self.entries()
            if app not in current:raise ValueError('O cadastro mudou. Abra os detalhes novamente.')
            entries=[updated if a.id==app.id else a for a in current]
            self._check_aliases(entries,{app.id})
            section['applications']=[a.as_dict() for a in entries]
            if updated!=app:
                for policy in section.get('policies',[]):
                    if (policy.get('operation'),policy.get('target'))==('open_app',app.id):
                        policy['enabled']=False;policy['revision']+=1
        self.runtime._update(update)
        return updated


def process_paths():
    """Consulta caminhos completos via Win32; nome de processo isolado não comprova alvo."""
    if os.name != 'nt':
        raise OSError('Verificação de aplicativos disponível somente no Windows.')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD))
    psapi.EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,ctypes.POINTER(wintypes.DWORD))
    processes = (wintypes.DWORD*32768)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(processes,ctypes.sizeof(processes),ctypes.byref(needed)):
        raise OSError('Não consegui consultar os processos do Windows.')
    if needed.value >= ctypes.sizeof(processes):
        raise OSError('Lista de processos excedeu o limite de verificação.')
    paths = set()
    for pid in processes[:needed.value//ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
                paths.add(os.path.normcase(os.path.realpath(buffer.value)))
        finally:
            kernel.CloseHandle(handle)
    return paths


class CatalogLauncher:
    def __init__(self, catalog, paths=process_paths, launch=None, *, windows=None, launch_window=None):
        self.catalog, self.paths = catalog, paths
        self.launch = launch or (lambda path: subprocess.Popen([path],shell=False,cwd=str(Path(path).parent)))
        from .browser_windows import browser_windows
        self.windows=windows or browser_windows
        from .browser_windows import close_windows
        self.close_windows=close_windows
        from .browser_windows import closeable_windows
        self.closeable_windows=lambda app:closeable_windows(app.path) if Path(app.path).name.casefold()=='discord.exe' else self.windows(app.path)
        self.launch_window=launch_window or (lambda path:subprocess.Popen([path,'--new-window','about:blank'],shell=False,cwd=str(Path(path).parent)))

    def open_new_window(self,app,guard):
        if Path(app.path).name.casefold()!='chrome.exe':
            raise ValueError('Nova janela disponível somente para o Chrome aprovado.')
        if not self.catalog.valid(app):raise ValueError('Cadastro ou executável mudou.')
        before=self.windows(app.path)
        if not self.catalog.valid(app):raise ValueError('O executável mudou antes da abertura.')
        guard();self.launch_window(app.path)
        return before

    def is_running(self, app):
        from .browser_windows import same_app
        expected=os.path.normcase(os.path.realpath(app.path))
        return any(same_app(expected,path) for path in self.paths())

    def open(self, app, guard):
        if not self.catalog.valid(app):
            raise ValueError('O cadastro ou executável mudou. Revise o aplicativo antes de abrir.')
        if self.is_running(app):
            return False
        # Checagem final da identidade, após eventuais consultas demoradas.
        if not self.catalog.valid(app):
            raise ValueError('O executável mudou antes da abertura.')
        guard()
        self.launch(app.path)
        return True


def discover_applications():
    """Somente candidatos. Não cadastra nem executa atalhos encontrados."""
    if os.name != 'nt':
        return []
    import winreg
    candidates = []
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive,r'Software\Microsoft\Windows\CurrentVersion\App Paths',0,
                        winreg.KEY_READ|view) as key:
                    for index in range(min(winreg.QueryInfoKey(key)[0],2000)):
                        name=winreg.EnumKey(key,index)
                        try:
                            with winreg.OpenKey(key,name) as child:
                                path=winreg.QueryValueEx(child,None)[0]
                            if isinstance(path,str):
                                candidates.append(dict(name=Path(name).stem,path=os.path.expandvars(path).strip('"'),source='App Paths'))
                        except OSError:
                            continue
            except OSError:
                continue
    # Consulta nativa no próprio worker; não cria console ou processo auxiliar.
    from .shortcuts import discover_shortcuts
    candidates.extend(discover_shortcuts())
    found={}
    for row in candidates:
        path=Path(row.get('path',''))
        if (path.is_absolute() and path.suffix.casefold()=='.exe' and path.is_file()
                and path.name.casefold() not in _TERMINALS):
            found.setdefault(os.path.normcase(str(path)),row)
    return sorted(found.values(),key=lambda r:r['name'].casefold())
