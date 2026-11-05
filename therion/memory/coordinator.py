"""Fila limitada de prévias, vinculada à sessão; não possui escrita em produção."""
from collections import deque
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import re
import threading
import time
import uuid
from therion.core.inference_lock import ProcessRLock
from therion.memory.selection import useful_selection
from therion.memory.review import LearningReviews

from therion.memory.knowledge import (MemoryCandidate, MemoryError, MemoryPolicy, SourceReference, digest,
    related_candidates, sensitive, user_candidate, validate_candidate)


class InferenceGate:
    """Chamadas normais precedem novos trabalhos automáticos; chamada ativa é limitada por timeout."""
    def __init__(self):
        self.lock = ProcessRLock()
        self.state = threading.Lock()
        self.waiters = 0

    @contextmanager
    def foreground(self):
        with self.state:
            self.waiters += 1
        self.lock.acquire()
        with self.state:
            self.waiters -= 1
        try:
            yield
        finally:
            self.lock.release()

    @contextmanager
    def background(self):
        with self.state:
            acquired = not self.waiters and self.lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                self.lock.release()


INFERENCE_GATE = InferenceGate()


class MemoryCoordinator:
    def __init__(self, session_id, policy=None, clock=None):
        self.session_id = session_id
        self.policy = policy or MemoryPolicy()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.candidates = []
        self.audit = deque(maxlen=100)
        self._queue = deque()
        self._notifications = deque(maxlen=5)
        self._condition = threading.Condition(threading.RLock())
        self._generation = 0
        self._active = False
        self._thread = None
        self._closed = False
        self._seen = set()
        self._observations = {}
        self._operation_sources = {}
        self.reviews = LearningReviews()

    def _record(self, operation, identifier='', state=''):
        self.audit.append({'time': self.clock().isoformat(), 'operation': operation,
                           'id': identifier, 'state': state, 'revision': self.policy.revision})

    def reset(self, session_id):
        with self._condition:
            self.reviews.clear()
            self.session_id = session_id
            self._generation += 1
            self._queue.clear()
            self._notifications.clear()
            self.candidates.clear()
            self._seen.clear()
            self._observations.clear()
            self._operation_sources.clear()
            self.audit.clear()
            self._condition.notify_all()

    def cancel_pending(self, discard_candidates=False):
        with self._condition:
            self.reviews.clear()
            self._generation += 1
            self._queue.clear()
            self._notifications.clear()
            self._operation_sources.clear()
            self._observations.clear()
            self._condition.notify_all()
            if discard_candidates:
                self.candidates.clear()
            self._record('cancel_pending', state='cancelled')

    def pause(self):
        with self._condition:
            self.policy = replace(self.policy, mode='off', revision=self.policy.revision+1)
            self.reset(self.session_id)
            self._record('pause', state='off')

    def close(self):
        with self._condition:
            self._closed = True
            self.reset(self.session_id)

    def _add(self, candidate):
        validate_candidate(candidate, explicit=candidate.source.kind == 'user')
        matches = related_candidates(candidate, self.candidates)
        duplicate = next((identifier for identifier, kind in matches if kind == 'duplicata'), None)
        if duplicate:
            return next(c for c in self.candidates if c.id == duplicate), 'existing'
        if len(self.candidates) >= 3:
            raise MemoryError('Limite de três candidatos da sessão atingido. Revise os existentes.')
        if matches:
            candidate = replace(candidate, related=tuple(identifier + ': ' + kind for identifier, kind in matches))
        self.candidates.append(candidate)
        self._record('preview', candidate.id, 'pending')
        return candidate, 'new'

    def explicit(self, text):
        with self._condition:
            if self._closed or self.policy.mode == 'off':
                raise MemoryError('Captura de memória pausada ou desativada.')
            return self._add(user_candidate(text, self.session_id, self.clock()))

    def discard(self, identifier=None):
        with self._condition:
            if identifier is None:
                if len(self.candidates) != 1:
                    raise MemoryError('Qual candidato? Indique o identificador ou número da lista.')
                identifier = self.candidates[0].id
            item = next((item for item in self.candidates if item.id == identifier), None)
            if item is None:
                raise MemoryError('Candidato não encontrado nesta sessão.')
            self.candidates.remove(item)
            self._record('discard_candidate', identifier, 'discarded')
            return item

    def snapshot(self):
        with self._condition:
            return tuple(self.candidates)

    def notifications(self):
        with self._condition:
            current = {c.id for c in self.candidates}
            values = tuple(identifier for identifier in self._notifications if identifier in current)
            self._notifications.clear()
            return values

    def review_notifications(self):
        with self._condition:
            self.reviews.items[:]=[r for r in self.reviews.items if self.reviews.clock()<r.deadline and r.policy==self.policy]
            ids={r.id for r in self.reviews.items}
            values=tuple(value for value in self.reviews.notifications if value in ids)
            self.reviews.notifications.clear()
            return values

    def learning_reviews(self,roots):
        with self._condition:
            return self.reviews.current(self.session_id,self.policy,roots,self._operation_source_valid)

    def resolve_review(self,identifier,roots,classify=False):
        with self._condition:
            row=self.reviews.select(identifier,self.session_id,self.policy,roots,self._operation_source_valid)
            if classify:
                candidate=self.reviews.reviewed_candidate(row)
                item,state=self._add(candidate)
                self.reviews.remove(row)
                self._record('human_sensitivity_review',identifier,'classified_non_sensitive')
                return item
            self.reviews.remove(row)
            self._record('human_sensitivity_review',identifier,'discarded')

    def observe_result(self, code, provider):
        """Eventos internos emitidos após verificar resultado; nunca recebe mensagem do modelo.

        Retém apenas contagem e descrição fixa sem dados de agenda, caminho ou erro bruto.
        Uma falha isolada não comprova um padrão; duas observações permitem uma prévia.
        """
        descriptions = {
            'calendar_query_failed': 'Limitação observada: duas consultas ao calendário falharam nesta sessão. A falha de consulta não comprova que a agenda esteja vazia; o estado dos compromissos permanece desconhecido.',
            'action_verification_failed': 'Limitação observada: em duas operações desta sessão o executor informou sucesso, mas o verificador não confirmou o resultado. Não anunciar conclusão verificada nem repetir automaticamente uma escrita incerta.',
        }
        with self._condition:
            if code not in descriptions or self._closed or self.policy.mode == 'off':
                return False
            self._observations[code] = min(2, self._observations.get(code, 0) + 1)
            if self._observations[code] < 2:
                return False
            if provider is None:
                self._fixed_limitation(code, descriptions[code])
                return False
            text = descriptions[code]
            source = SourceReference(self.session_id + ':operation:' + code, 'operation', digest(text), text)
            self._operation_sources[source.identifier] = source
            self._record('verified_result', code, 'repeated_failure')
            return self.offer_verified(source, provider, (), reusable=True,
                source_resolver=self._operation_source_valid)

    def verified_patterns(self):
        with self._condition:
            if self._closed or self.policy.mode == 'off':
                return ()
            return tuple((code, count) for code, count in self._observations.items() if count >= 2)

    def _fixed_limitation(self, code, text):
        """Somente eventos internos conhecidos; nunca sintetizar fallback de texto de nota."""
        source = SourceReference(self.session_id + ':operation:' + code, 'operation', digest(text), text)
        if any(c.source.identifier == source.identifier for c in self.candidates):
            return
        self._operation_sources[source.identifier] = source
        now = self.clock()
        candidate = MemoryCandidate('MEM-' + uuid.uuid4().hex[:12], self.session_id,
            'Limitação verificada: ' + code, text, 'limitação',
            'Dois resultados internos verificados; preservar incerteza e evitar repetição.', text,
            source, now, now + timedelta(days=30), model='verificador interno; sem inferência')
        try:
            item, state = self._add(candidate)
            if state == 'new':
                self._notifications.append(item.id)
        except MemoryError:
            self._record('verified_result', code, 'preview_limit')

    def _operation_source_valid(self, source):
        with self._condition:
            return self._operation_sources.get(source.identifier) == source and not self._closed and self.policy.mode != 'off'

    def offer_verified(self, source, provider, roots, reusable=False, source_resolver=None):
        with self._condition:
            if (self._closed or self.policy.mode == 'off' or not reusable or provider is None
                    or source.kind not in {'file', 'operation'} or len(source.text) < 80 or sensitive(source.text)
                    or len(self._queue) + int(self._active) >= 5):
                return False
            key = source.identifier + ':' + source.version
            if key in self._seen or not source.valid(roots, source_resolver):
                return False
            self._seen.add(key)
            self._queue.append((self._generation, source, provider, tuple(roots), source_resolver, self.policy))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name='Therion-memory-preview', daemon=True)
                self._thread.start()
            self._condition.notify_all()
            return True

    def _run(self):
        while True:
            with self._condition:
                if self._closed or not self._queue:
                    self._thread = None
                    return
                generation, source, provider, roots, resolver, policy = self._queue.popleft()
                self._active = True
            started = time.monotonic()
            try:
                raw = provider.extract_memory_candidates(
                    {'content': source.text[:4000], 'kind': source.kind}, timeout_seconds=20)
                if time.monotonic() - started > 20:
                    raise MemoryError('Seleção excedeu o prazo.')
                with self._condition:
                    if generation != self._generation or self._closed or self.policy.mode == 'off' or self.policy != policy:
                        continue
                    if not source.valid(roots, resolver) or not isinstance(raw, list) or len(raw) > 3:
                        raise MemoryError('Fonte ou resposta de seleção inválida.')
                    for row in raw:
                        keys = {'title', 'summary', 'kind', 'reason', 'evidence', 'sensitivity'}
                        if not isinstance(row, dict) or set(row) != keys or any(not isinstance(v, str) for v in row.values()):
                            raise MemoryError('Resposta fora do esquema fechado.')
                        if row['kind'] not in {'procedimento', 'hipótese', 'sugestão', 'limitação'}:
                            raise MemoryError('Captura automática não retém dados pessoais ou fatos inferidos.')
                        if re.search(r'(?i)\b(?:Marcus|Marcos|meu|minha|prefiro|gosto de)\b', row['summary']):
                            raise MemoryError('Informação pessoal exige pedido explícito.')
                        if not useful_selection(row):
                            self._record('selection', state='no_reusable_signal')
                            continue
                        now = self.clock()
                        candidate = MemoryCandidate('MEM-' + uuid.uuid4().hex[:12], self.session_id,
                            row['title'], row['summary'], row['kind'], row['reason'], row['evidence'], source,
                            now, now + timedelta(days=30), sensitivity=row['sensitivity'],
                            model=getattr(provider, 'model', 'não informado'))
                        if candidate.sensitivity=='uncertain':
                            self.reviews.offer(candidate,self.policy)
                            self._record('selection',state='sensitivity_review_required')
                            continue
                        candidate, state = self._add(candidate)
                        if state == 'new':
                            self._notifications.append(candidate.id)
            except Exception:
                with self._condition:
                    if generation == self._generation and not self._closed:
                        self._record('selection', state='failed_or_rejected')
            finally:
                with self._condition:
                    if (source.kind == 'operation' and generation == self._generation
                            and not self._closed and self.policy == policy and self.policy.mode != 'off'
                            and self._operation_source_valid(source)):
                        self._fixed_limitation(source.identifier.rsplit(':', 1)[-1], source.text)
                    self._active = False
                    self._condition.notify_all()

    def wait_idle(self, timeout=2):
        with self._condition:
            return self._condition.wait_for(lambda: not self._active and not self._queue, timeout)
