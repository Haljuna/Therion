"""Contratos de memória externa. Conteúdo nunca representa autorização."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import os
import re
import uuid


RAS_ROOT = '90 - Sistema da IA/Notas de Rascunho da IA/Registros'


class MemoryError(ValueError):
    """Falha controlada, sem registrar conteúdo rejeitado."""


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def safe_path(path, roots):
    """Recusa links/junções em todos os componentes e não amplia raízes."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
                raise MemoryError('Links e junções não são permitidos nesta operação de memória.')
    resolved = path.resolve()
    if not any(resolved == Path(root) or Path(root) in resolved.parents for root in roots):
        raise MemoryError('Fonte ou destino fora das raízes autorizadas.')
    return resolved


def sensitive(text):
    # Defesa parcial. Não equivale a um classificador universal de sensibilidade.
    return bool(re.search(r'(?i)(GOCSPX-|sk-[a-z0-9]{12}|-----BEGIN .*PRIVATE KEY|'
                          r'\b(?:senha|password|token|segredo|api[_ -]?key|cpf|diagn[oó]stico|'
                          r'cart[aã]o de cr[eé]dito|conta banc[aá]ria)\b|'
                          r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b)', text))


@dataclass(frozen=True)
class SourceReference:
    identifier: str
    kind: str
    version: str
    text: str
    path: str = ''
    roots: tuple[str, ...] = ()

    @classmethod
    def user(cls, text, session_id):
        return cls(session_id + ':' + digest(text), 'user', digest(text), text)

    @classmethod
    def file(cls, path, text, roots):
        roots = tuple(str(Path(root).resolve()) for root in roots)
        path = safe_path(path, roots)
        return cls(str(path), 'file', digest(text), text[:4000], str(path), roots)

    def valid(self, current_roots, resolver=None):
        if self.kind in {'user', 'operation', 'verified_operation'}:
            return bool(resolver and resolver(self))
        if self.kind != 'file' or not self.path or not self.roots:
            return False
        try:
            path = safe_path(self.path, self.roots)
            path = safe_path(path, current_roots)
            if path.stat().st_nlink != 1 or path.stat().st_size > 1_000_000:
                return False
            return digest(path.read_text(encoding='utf-8')) == self.version
        except (OSError, UnicodeError, MemoryError):
            return False


@dataclass(frozen=True)
class MemoryPolicy:
    mode: str = 'preview'
    read_roots: tuple[str, ...] = ()
    write_root: str = ''
    authorization: str = ''
    expires_at: datetime | None = None
    revision: int = 0
    per_session: int = 3
    per_day: int = 10
    max_characters: int = 8000
    review_days: int = 30

    def allows_write(self, now):
        return (self.mode == 'authorized' and bool(self.authorization) and bool(self.write_root)
                and isinstance(self.expires_at, datetime) and self.expires_at.tzinfo is not None
                and all(type(v) is int for v in (self.per_session, self.per_day, self.max_characters, self.review_days))
                and now < self.expires_at and 0 < self.per_session <= 3
                and 0 < self.per_day <= 10 and 0 < self.max_characters <= 8000
                and 0 < self.review_days <= 30)


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    session_id: str
    title: str
    summary: str
    kind: str
    reason: str
    evidence: str
    source: SourceReference
    created_at: datetime
    review_at: datetime
    confidence: str = 'Baixa'
    sensitivity: str = 'non_sensitive'
    model: str = 'não informado'
    related: tuple[str, ...] = ()
    authorization_id: str = ''
    policy_revision: int = 0

    @property
    def fingerprint(self):
        return digest(self.kind + ':' + ' '.join(self.summary.casefold().split()))


def validate_candidate(candidate, explicit=False, *, for_review=False):
    source = candidate.source
    if (not isinstance(source, SourceReference) or source.kind not in {'user', 'file', 'operation', 'verified_operation'}
            or not isinstance(source.identifier, str) or not 1 <= len(source.identifier) <= 2048
            or not isinstance(source.text, str) or not source.text or len(source.text) > 1_000_000
            or not isinstance(source.version, str) or not re.fullmatch(r'[a-f0-9]{64}', source.version)
            or not isinstance(source.roots, tuple) or any(not isinstance(root, str) for root in source.roots)
            or (source.kind == 'file' and (not source.path or source.identifier != source.path))):
        raise MemoryError('Referência de origem inválida.')
    fields = (candidate.title, candidate.summary, candidate.reason, candidate.evidence)
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        raise MemoryError('Faltam conteúdo, motivo ou evidência para o candidato.')
    if len(candidate.title) > 100 or len(candidate.summary) > 1500 or len(candidate.evidence) > 600:
        raise MemoryError('Candidato acima do limite de conteúdo.')
    if len(candidate.reason) > 400 or sum(map(len, fields)) > 3000:
        raise MemoryError('Candidato acima do limite de conteúdo.')
    if candidate.kind not in {'declaração', 'preferência', 'procedimento', 'hipótese', 'sugestão', 'limitação'}:
        raise MemoryError('Tipo de conhecimento não reconhecido.')
    if candidate.source.kind == 'user' and candidate.kind not in {'declaração', 'preferência'}:
        raise MemoryError('Uma declaração não comprova um procedimento ou fato.')
    if source.kind == 'operation' and candidate.kind != 'limitação':
        raise MemoryError('Falha observada permite somente candidato de limitação.')
    if source.kind == 'verified_operation' and (candidate.kind != 'procedimento'
            or digest(source.text) != source.version):
        raise MemoryError('Procedimento exige origem operacional verificada e íntegra.')
    if source.kind == 'file' and candidate.summary.strip() == source.text.strip():
        raise MemoryError('Cópia integral da fonte não acrescenta um aprendizado.')
    if candidate.kind == 'preferência' and not explicit:
        raise MemoryError('Preferências exigem pedido explícito.')
    if candidate.evidence not in candidate.source.text:
        raise MemoryError('A evidência não corresponde à fonte.')
    allowed_sensitivity={'non_sensitive','uncertain'} if for_review else {'non_sensitive'}
    if candidate.sensitivity not in allowed_sensitivity or sensitive(' '.join(fields) + ' ' + candidate.source.text):
        raise MemoryError('Conteúdo sensível ou de sensibilidade incerta não será retido.')
    if candidate.confidence not in {'Baixa', 'Média', 'Alta'}:
        raise MemoryError('Confiança inválida.')
    if (not isinstance(candidate.created_at, datetime) or not isinstance(candidate.review_at, datetime)
            or candidate.created_at.tzinfo is None or candidate.review_at.tzinfo is None
            or candidate.review_at <= candidate.created_at):
        raise MemoryError('Datas de memória inválidas.')
    if len(candidate.related) > 5 or any(not isinstance(x, str) or len(x) > 100 for x in candidate.related):
        raise MemoryError('Relações fora do limite.')
    return candidate


def user_candidate(text, session_id, now=None):
    now = now or datetime.now(timezone.utc)
    source = SourceReference.user(text, session_id)
    preference = bool(re.search(r'(?i)\b(?:prefiro|preferência|gosto de)\b', text))
    title = ('Preferência: ' if preference else 'Declaração: ') + ' '.join(text.split())[:75]
    candidate = MemoryCandidate('MEM-' + uuid.uuid4().hex[:12], session_id,
        title, text,
        'preferência' if preference else 'declaração', 'Pedido explícito para lembrar.',
        text[:600], source, now, now + timedelta(days=30))
    return validate_candidate(candidate, explicit=True)


def preview(candidate, supervised=False):
    return (f'{candidate.id} — {candidate.title}\nEstado: candidato não consolidado\n'
            f'Tipo: {candidate.kind}\nConteúdo: {candidate.summary}\n'
            f'Motivo: {candidate.reason}\nOrigem: {candidate.source.identifier}\n'
            f'Evidência: {candidate.evidence}\nAinda não salvei. '
            + ('Peça salve para revisar a proposta de gravação supervisionada.' if supervised
               else 'A gravação real está desativada.'))


def related_candidates(candidate, existing):
    """Indícios são apenas avisos; não fundem registros ou resolvem conflitos."""
    words = set(re.findall(r'\w{4,}', candidate.summary.casefold()))
    matches = []
    for other in existing:
        if candidate.fingerprint == other.fingerprint:
            matches.append((other.id, 'duplicata'))
        elif len(words & set(re.findall(r'\w{4,}', other.summary.casefold()))) >= 2:
            matches.append((other.id, 'possível sobreposição ou conflito; revisar'))
    return matches
