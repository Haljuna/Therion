"""Limpeza dos temporários seguros do disco C, só com pedido ou "sim" do usuário.

Mesma lista da limpeza segura usada fora do Therion: Temp com mais de 24 h, crash dumps, relatórios de erro,
caches do pip, npm e uv, cache do Chrome, Edge e Discord, logs antigos do Ollama. Nunca entra em junção ou link
(pasta movida para o F), nunca toca em Downloads, lixeira, histórico, senhas, logins nem arquivo do usuário.
Arquivo em uso fica onde está.
"""
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

from therion.context.language import control

OFFER_SECONDS = 120
_GB = 1024 ** 3
_POLITE = r'(?:,? por favor)?'
_ASK = re.compile(r'(?:therion,? )?(?:(?:pode |voce pode )?(?:libera|libere|liberar|limpa|limpe|limpar|faz|faca) )'
                  r'(?:um pouco de |uma limpeza n[oa] |o )?(?:espaco|disco|disco c|c|temporarios|os temporarios)'
                  r'(?: (?:do|no|n[oa]) (?:pc|computador|disco c|disco|c))?' + _POLITE)
_YES = {'sim', 'pode', 'pode limpar', 'sim pode', 'pode sim', 'limpa', 'limpe', 'claro', 'manda', 'sim por favor', 'pode ser'}
_NO = {'nao', 'nao precisa', 'agora nao', 'deixa', 'deixa assim', 'nao obrigado', 'nao limpa'}


def _running(*names):
    try:
        listing = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, errors='replace', timeout=10,
                                 stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return True   # sem saber, trata como rodando: o cache do uv fica
    return any(f'"{name}"' in listing.lower() for name in names)


def targets():
    """(nome, pasta, idade mínima em horas) cujo CONTEÚDO pode sair."""
    local, roaming = os.environ.get('LOCALAPPDATA', ''), os.environ.get('APPDATA', '')
    rows = [('Temp do usuário', os.environ.get('TEMP', ''), 24), ('Temp do Windows', r'C:\Windows\Temp', 24),
            ('Crash dumps', local + r'\CrashDumps', 0),
            ('Relatórios de erro', local + r'\Microsoft\Windows\WER\ReportArchive', 0),
            ('Relatórios de erro', local + r'\Microsoft\Windows\WER\ReportQueue', 0),
            ('Cache do pip', local + r'\pip\Cache', 0), ('Cache do npm', local + r'\npm-cache', 0)]
    if not _running('uv.exe', 'uvx.exe'):
        rows.append(('Cache do uv', local + r'\uv\cache', 0))
    for browser, base in (('Chrome', local + r'\Google\Chrome\User Data'), ('Edge', local + r'\Microsoft\Edge\User Data')):
        try:
            profiles = [entry.path for entry in os.scandir(base) if entry.is_dir() and (entry.name == 'Default' or entry.name.startswith('Profile '))]
        except OSError:
            profiles = []
        rows += [('Cache do ' + browser, os.path.join(profile, cache), 0) for profile in profiles for cache in ('Cache', 'Code Cache', 'GPUCache')]
    rows += [('Cache do Discord', os.path.join(roaming, 'discord', cache), 0) for cache in ('Cache', 'Code Cache', 'GPUCache')]
    return [row for row in rows if row[1] and Path(row[1]).is_absolute()]


def _link(entry):
    try:
        return entry.is_symlink() or bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return True


def size(path):
    """Bytes de uma pasta ou arquivo, sem seguir junção; o que não dá para ler conta zero."""
    total, stack = 0, [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if _link(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


def _items(folder, hours):
    """Itens do primeiro nível mais velhos que o limite; pasta que é junção não conta."""
    try:
        root = os.lstat(folder)
        if stat.S_ISLNK(root.st_mode) or root.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return []
        limit = time.time() - hours * 3600
        with os.scandir(folder) as entries:
            return [entry for entry in entries if not _link(entry) and entry.stat(follow_symlinks=False).st_mtime < limit]
    except (OSError, AttributeError):
        return []


def _item_size(entry):
    try:
        return size(entry.path) if entry.is_dir(follow_symlinks=False) else entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0


def _ollama_logs():
    try:
        return [entry for entry in os.scandir(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Ollama'))
                if entry.is_file(follow_symlinks=False) and re.fullmatch(r'.+-.+\.log', entry.name)]   # o log atual fica
    except OSError:
        return []


def _plan(rows=None):
    plan = [(name, item) for name, folder, hours in (targets() if rows is None else rows) for item in _items(folder, hours)]
    return plan + ([('Logs antigos do Ollama', item) for item in _ollama_logs()] if rows is None else [])


def estimate(rows=None):
    return sum(_item_size(item) for _, item in _plan(rows))


def clean(rows=None):
    """{nome: bytes liberados}; arquivo em uso fica e não conta."""
    freed = {}
    for name, item in _plan(rows):
        before = _item_size(item)
        try:
            if item.is_dir(follow_symlinks=False):
                shutil.rmtree(item.path, ignore_errors=True)   # Python ≥ 3.8 não entra em junção no Windows
            else:
                os.remove(item.path)
        except OSError:
            pass
        left = (size(item.path) if os.path.isdir(item.path) else os.path.getsize(item.path)) if os.path.lexists(item.path) else 0
        freed[name] = freed.get(name, 0) + max(0, before - left)
    return freed


def _gb(value):
    return f'{value / _GB:.1f}'.replace('.', ',') + ' GB'


def report(freed, free_c=None, update_cache=None):
    total = sum(freed.values())
    if total < 1024 ** 2:
        message = 'Não havia temporários seguros para apagar.'
    else:
        parts = sorted(((name, value) for name, value in freed.items() if value >= 50 * 1024 ** 2), key=lambda row: -row[1])
        message = f'Limpei {_gb(total)}' + (': ' + ', '.join(f'{name.lower()} {_gb(value)}' for name, value in parts[:4]) if parts else '') + '.'
    if free_c is not None:
        message += f' O disco C está com {_gb(free_c)} livres.'
    if update_cache is not None and update_cache >= _GB:
        message += f' O F:\\WUDownloadCache tem {_gb(update_cache)}; esse só o senhor decide.'
    return message


def run():
    freed = clean()
    try:
        free_c = shutil.disk_usage('C:\\').free
    except OSError:
        free_c = None
    return report(freed, free_c, size(r'F:\WUDownloadCache') if os.path.isdir(r'F:\WUDownloadCache') else None)


def offer(host):
    """Vale por 2 min e só para a próxima frase; um "sim" depois disso não apaga nada."""
    host._pc_cleanup_offer = time.monotonic() + OFFER_SECONDS


def wanted(command, host):
    """Sem consumir a oferta: a frase é para a limpeza? (o agente deixa a rota local responder)."""
    deadline = getattr(host, '_pc_cleanup_offer', None)
    text = control(command).rstrip('?!. ').replace(',', '')
    return bool(_ASK.fullmatch(control(command).rstrip('?!. '))) or (
        deadline is not None and time.monotonic() < deadline and text in _YES | _NO)


def answer(command, host, runner=None):
    """Resposta pronta ou None: "sim"/"não" à oferta do vigia, ou o pedido "libera espaço"."""
    runner = runner or run
    text = control(command).rstrip('?!. ').replace(',', '')
    deadline, host._pc_cleanup_offer = getattr(host, '_pc_cleanup_offer', None), None
    if deadline is not None and time.monotonic() < deadline:
        if text in _YES:
            return runner()
        if text in _NO:
            return 'Tudo bem, não apaguei nada.'
    return runner() if _ASK.fullmatch(control(command).rstrip('?!. ')) else None
