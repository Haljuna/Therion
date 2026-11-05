"""Repositório RAS injetável. Não é conectado ao cofre real nesta entrega."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import re
import tempfile
import threading

from therion.memory.knowledge import (MemoryCandidate, MemoryError, MemoryPolicy,
    SourceReference, safe_path, validate_candidate, related_candidates)


@dataclass(frozen=True)
class StorageResult:
    state: str
    identifier: str
    path: str
    recovered: bool = False


def _running_since(pid):
    """Hora de criação de um processo vivo; None se ele não existe; 'unknown' se não deu para saber.

    Não usa os.kill(pid, 0): no Windows isso encerra o processo.
    """
    if os.name != 'nt':
        return 'unknown'
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None if ctypes.get_last_error() == 87 else 'unknown'  # 87: PID inexistente
    try:
        code = wintypes.DWORD()
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return 'unknown'
        if code.value != 259:  # STILL_ACTIVE
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not kernel.GetProcessTimes(handle, *map(ctypes.byref, times)):
            return 'unknown'
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)


def plain(text):
    # Não produzir links Obsidian/Markdown, HTML, headings ou tarefas a partir dos dados.
    return str(text).replace('[', '［').replace(']', '］').replace('<', '‹').replace('>', '›').replace('\n', ' ')


def serialize(candidate, identifier):
    data = asdict(candidate)
    if candidate.source.kind == 'file':
        data['source']['text'] = candidate.evidence
    data['created_at'] = candidate.created_at.isoformat()
    data['review_at'] = candidate.review_at.isoformat()
    data['ras_id'] = identifier
    # JSON em linha própria, não interpretado como frontmatter ou instrução.
    header = json.dumps(data, ensure_ascii=True, separators=(',', ':')).replace('[[', r'\u005b\u005b').replace(']]', r'\u005d\u005d').replace('](', r'\u005d(')
    return (f'# {identifier} — {plain(candidate.title)}\n\n'
            f'ID: {identifier}\nEstado: Rascunho da IA\nData: {candidate.created_at.date()}\n'
            f'Agente: Thérion\nModelo: {plain(candidate.model)}\n'
            f'Origem: {plain(candidate.source.identifier)}\nTipo: {plain(candidate.kind)}\n'
            f'Assunto: {plain(candidate.title)}\nConfiança: {candidate.confidence}\n'
            f'Revisar em: {candidate.review_at.date()}\n'
            f'Autorização histórica: {plain(candidate.authorization_id)} (revisão {candidate.policy_revision})\n'
            f'Possíveis relações: {plain("; ".join(candidate.related))}\n\n'
            f'## Contexto\n{plain(candidate.reason)}\n\n'
            f'## Aprendizado\n{plain(candidate.summary)}\n\n'
            f'## Evidência\n{plain(candidate.evidence)}\n\n'
            f'## Possível uso futuro\n{plain(candidate.reason)}\n\n'
            '## Destino sugerido\nManter como rascunho para revisão.\n\n'
            '## Observações\nConteúdo não consolidado; não representa permissão ou decisão.\n\n'
            f'<!-- THERION_MEMORY_V1\n{header}\n-->\n')


def deserialize(text):
    match = re.search(r'\n<!-- THERION_MEMORY_V1\n([^\n]+)\n-->\s*$', text)
    if not match:
        raise MemoryError('Registro sem metadados de memória reconhecidos.')
    try:
        data = json.loads(match[1])
        identifier = data.pop('ras_id')
        if not re.fullmatch(r'RAS-\d{8}-\d{3,}', identifier):
            raise ValueError()
        source = data.pop('source')
        source['roots'] = tuple(source['roots'])
        data['source'] = SourceReference(**source)
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['review_at'] = datetime.fromisoformat(data['review_at'])
        data['related'] = tuple(data['related'])
        candidate = validate_candidate(MemoryCandidate(**data), explicit=True)
        if serialize(candidate, identifier) != text:
            raise ValueError()
        return identifier, candidate
    except (KeyError, ValueError, TypeError) as error:
        raise MemoryError('Registro alterado ou metadados inválidos; revisão necessária.') from error


class MarkdownMemoryRepository:
    """A raiz só é aceita por injeção explícita e política válida por operação."""

    def __init__(self, root, policy_provider=None):
        self.policy_provider = policy_provider
        self.root = str(Path(root).absolute())
        self._canonical_root = str(Path(root).resolve())
        self._lock = threading.RLock()

    def _check(self, policy, now, write=False):
        if self.policy_provider is not None:
            current = self.policy_provider()
            if not write:
                for root in policy.read_roots:
                    safe_path(root, current.read_roots)
                current = replace(current, read_roots=policy.read_roots)
            if current != policy:
                raise MemoryError('Política foi alterada ou revogada durante a operação.')
        if policy.mode not in {'preview', 'authorized'}:
            raise MemoryError('Memória desativada.')
        if write and (not policy.allows_write(now) or policy.write_root != self._canonical_root):
            raise MemoryError('Gravação não autorizada pela política atual.')
        safe_path(self.root, (self._canonical_root,))
        if write:
            safe_path(self.root, policy.read_roots)
        if write and not self.root.replace('\\', '/').endswith('/Notas de Rascunho da IA/Registros'):
            raise MemoryError('Destino diferente da área de RAS.')
        if not write:
            safe_path(self.root, policy.read_roots)

    def _records(self):
        records = []
        if not Path(self.root).exists():
            return records
        for path in sorted(Path(self.root).glob('RAS-*.md')):
            safe_path(path, (self._canonical_root,))
            if path.stat().st_nlink != 1 or path.stat().st_size > 32000:
                raise MemoryError('Registro não pode ser validado com segurança.')
            text = path.read_text(encoding='utf-8')
            if ' - Therion - ' not in path.name:
                continue  # RAS de outros agentes são somente leitura, sem migração.
            identifier, candidate = deserialize(text)
            if not path.name.startswith(identifier + ' - '):
                raise MemoryError('Identificador inconsistente.')
            records.append((identifier, candidate, path))
        return records

    def store(self, candidate, policy, now, source_resolver=None, write_guard=None):
        with self._lock:
            self._check(policy, now, write=True)
            validate_candidate(candidate, explicit=True)
            if candidate.review_at <= now or candidate.created_at > now:
                raise MemoryError('Candidato vencido ou com data futura.')
            if not candidate.source.valid(policy.read_roots, source_resolver):
                raise MemoryError('Fonte ausente, alterada ou revogada.')
            Path(self.root).mkdir(parents=True, exist_ok=True)
            self._check(policy, now, write=True)
            lock_path = Path(self.root) / '.therion-memory.lock'
            blocked = ('Outra gravação está em andamento ou deixou estado incerto. Não repeti. '
                       f'Se o Therion foi fechado à força, confira a pasta e apague {lock_path.name}.')
            recovered = False
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as error:
                if not self._clear_dead_lock(lock_path):
                    raise MemoryError(blocked) from error
                recovered = True
                try:
                    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as again:
                    raise MemoryError(blocked) from again
            temporary = None
            published = False
            try:
                # Dono da trava: permite liberar com segurança se este processo morrer no meio.
                os.write(lock_fd, json.dumps({'pid': os.getpid(), 'created': _running_since(os.getpid())}).encode())
                records = self._records()
                for identifier, existing, path in records:
                    if existing.id == candidate.id or existing.fingerprint == candidate.fingerprint:
                        if existing.source.valid(policy.read_roots, source_resolver) and existing.review_at > now:
                            return StorageResult('existing', identifier, str(path), recovered)
                session_count = sum(c.session_id == candidate.session_id for _, c, _ in records)
                # A franquia é de publicação, não da data em que surgiu o candidato.
                # Candidatos antigos não podem contornar o limite do dia atual.
                day_prefix = 'RAS-' + now.strftime('%Y%m%d') + '-'
                day_count = sum(identifier.startswith(day_prefix) for identifier, _, _ in records)
                if session_count >= policy.per_session or day_count >= policy.per_day:
                    raise MemoryError('Limite de rascunhos atingido.')
                prefix = 'RAS-' + now.strftime('%Y%m%d') + '-'
                used = [int(m[1]) for path in Path(self.root).glob(prefix + '*')
                        if (m := re.match(re.escape(prefix) + r'(\d+)', path.name))]
                sequence = max(used, default=0)+1
                if sequence > 999:
                    raise MemoryError('Sequência de RAS do dia esgotada.')
                identifier = prefix + f'{sequence:03d}'
                overlaps = related_candidates(candidate, [replace(c, id=identifier) for identifier, c, _ in records])
                candidate = replace(candidate, authorization_id=policy.authorization, policy_revision=policy.revision,
                    related=tuple((identifier + ': ' + state) for identifier, state in overlaps)[:5],
                    review_at=min(candidate.review_at,
                    now + timedelta(days=policy.review_days)))
                text = serialize(candidate, identifier)
                if len(text) > policy.max_characters:
                    raise MemoryError('Registro acima do limite de caracteres.')
                destination = Path(self.root) / (identifier + ' - Therion - Rascunho.md')
                safe_path(destination, (self._canonical_root,))
                fd, temporary = tempfile.mkstemp(prefix='.therion-', suffix='.tmp', dir=self.root)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(text.encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
                self._check(policy, now, write=True)
                if not candidate.source.valid(policy.read_roots, source_resolver):
                    raise MemoryError('Fonte mudou antes da publicação.')
                if write_guard is not None:
                    write_guard()
                # Publicação atômica sem substituição; colisão externa não é repetida.
                os.link(temporary, destination)
                published = True
                os.unlink(temporary)
                temporary = None
                deserialize(destination.read_text(encoding='utf-8'))
                return StorageResult('stored', identifier, str(destination), recovered)
            except MemoryError as error:
                if published:
                    raise MemoryError('Resultado da gravação incerto; não repeti a operação.') from error
                raise
            except (OSError, UnicodeError) as error:
                raise MemoryError('Resultado da gravação incerto; não repeti a operação.' if published
                                  else 'Não consegui publicar o rascunho; não repeti.') from error
            finally:
                os.close(lock_fd)
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                lock_path.unlink(missing_ok=True)

    def _clear_dead_lock(self, lock_path):
        """Libera só a trava cujo dono comprovadamente morreu.

        Trava antiga, de outro dono ou de processo vivo fica como está. A checagem de
        impressão digital no store() impede gravar de novo uma nota que já tinha saído.
        """
        try:
            owner = json.loads(lock_path.read_text(encoding='utf-8'))
            pid, created = owner['pid'], owner['created']
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if type(pid) is not int or type(created) is not int or _running_since(pid) in (created, 'unknown'):
            return False
        try:
            # Sobras da gravação interrompida; uma delas pode ser um segundo nome da nota publicada.
            for leftover in Path(self.root).glob('.therion-*.tmp'):
                leftover.unlink()
            lock_path.unlink()
        except OSError:
            return False
        return True

    def retrieve(self, query, policy, now, source_resolver=None, record_validator=None):
        self._check(policy, now)
        terms = set(re.findall(r'\w{3,}', query.casefold()))
        ranked = []
        for identifier, candidate, path in self._records():
            if record_validator is not None and not record_validator(identifier, candidate, path):
                continue
            if candidate.review_at <= now or not candidate.source.valid(policy.read_roots, source_resolver):
                continue
            score = (len(terms & set(re.findall(r'\w{3,}', (candidate.title+' '+candidate.summary).casefold())))
                     if query else 1)
            if score:
                ranked.append((-score, identifier, candidate, path))
        result, length = [], 0
        for _, identifier, candidate, path in sorted(ranked, key=lambda row: (row[0], row[1])):
            text = f'{identifier} — Rascunho da IA ({candidate.kind})\n{candidate.summary}\nFonte: {candidate.source.identifier}'
            if len(result) == 3 or length + len(text) > 4000:
                break
            result.append({'id': identifier, 'content': text, 'path': str(path), 'state': 'Rascunho da IA'})
            length += len(text)
        self._check(policy, now)
        return tuple(result)
