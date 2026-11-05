"""Persistência supervisionada injetável; nenhuma configuração pessoal é habilitada.

O comprovante separado valida a integridade e a origem do RAS. Não concede
permissão futura: cada operação depende da política atual fornecida pelo host.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from contextlib import closing
from pathlib import Path
import json
import re
import sqlite3
import time
import uuid

from therion.context.language import control
from therion.memory.knowledge import (MemoryCandidate, MemoryPolicy, MemoryError,
    digest, safe_path, preview, related_candidates)
from therion.memory.repository import deserialize, StorageResult


class MemoryEvidenceStore:
    """Arquivo de evidência explicitamente injetado, separado do conteúdo das notas.

    O host deve proteger este arquivo como dado de auditoria. Não é uma defesa
    contra um processo com acesso de escrita ao próprio armazenamento confiável.
    """
    def __init__(self, root):
        self.root = str(Path(root).absolute())
        self.canonical = str(Path(root).resolve())

    def _path(self):
        safe_path(self.root, (self.canonical,))
        path = safe_path(Path(self.root) / 'evidence.sqlite3', (self.canonical,))
        if path.exists() and (path.stat().st_nlink != 1 or path.stat().st_size > 10_000_000):
            raise MemoryError('Evidência persistente não pode ser validada.')
        return path

    def record(self, result, candidate, policy, proposal_id, check, confirmed_at, transition=None):
        path = self._path()
        Path(self.root).mkdir(parents=True, exist_ok=True)
        text = Path(result.path).read_text(encoding='utf-8')
        identifier, stored = deserialize(text)
        expected = replace(candidate.source, text=candidate.evidence) if candidate.source.kind == 'file' else candidate.source
        if identifier != result.identifier or stored.source != expected:
            raise MemoryError('Origem publicada diverge da proposta confirmada.')
        payload = json.dumps({'source': stored.source.__dict__, 'authorization': policy.authorization,
            'revision': policy.revision, 'proposal': proposal_id, 'session': candidate.session_id,
            'confirmed_at': confirmed_at.isoformat()},
            ensure_ascii=True, sort_keys=True)
        check()
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, hash TEXT, payload TEXT)')
                db.execute('INSERT OR IGNORE INTO receipts VALUES (?, ?, ?)', (identifier, digest(text), payload))
                if transition is not None:
                    self._transition(db, transition, identifier, digest(text), proposal_id, candidate.session_id, confirmed_at)
                check()
        if not self.valid_record(identifier, stored, Path(result.path), policy):
            raise MemoryError('Comprovante não confirmado; não repeti a publicação.')

    def _transition(self, db, target, replacement, replacement_hash, proposal_id, session, now):
        db.execute('CREATE TABLE IF NOT EXISTS transitions (old_id TEXT PRIMARY KEY, old_hash TEXT, '
            'new_id TEXT, new_hash TEXT, proposal TEXT, session TEXT, confirmed_at TEXT)')
        receipt = db.execute('SELECT hash FROM receipts WHERE id=?', (target.identifier,)).fetchone()
        if (receipt != (target.version,) or replacement == target.identifier
                or db.execute('SELECT 1 FROM transitions WHERE old_id=?', (target.identifier,)).fetchone()):
            raise MemoryError('Registro anterior mudou ou já recebeu uma correção/desconsideração.')
        db.execute('INSERT INTO transitions VALUES (?,?,?,?,?,?,?)', (target.identifier, target.version,
            replacement, replacement_hash, proposal_id, session, now.isoformat()))

    def retire(self, target, policy, proposal_id, session, now, check):
        path = self._path()
        if not path.exists():
            raise MemoryError('Comprovante da memória não encontrado.')
        check()
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._transition(db, target, '', '', proposal_id, session, now)
                check()
        if self.valid_record(target.identifier, target.candidate, Path(target.path), policy):
            raise MemoryError('Desconsideração não confirmada; não repeti.')

    def _receipts(self, policy):
        path = self._path()
        if not path.exists():
            return ()
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                rows = db.execute('SELECT id, hash, payload FROM receipts').fetchall()
                has_transitions = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transitions'").fetchone()
                retired = dict(db.execute('SELECT old_id, old_hash FROM transitions').fetchall()) if has_transitions else {}
            result = []
            for identifier, version, payload in rows:
                if retired.get(identifier) == version:
                    continue
                data = json.loads(payload)
                if data['authorization'] == policy.authorization and data['revision'] == policy.revision:
                    result.append((identifier, version, data))
            return result
        except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
            raise MemoryError('Evidência persistente inválida; revisão necessária.') from error

    def valid_source(self, source, policy):
        expected = dict(source.__dict__, roots=list(source.roots))
        return any(data['source'] == expected for _, _, data in self._receipts(policy))

    def valid_record(self, identifier, candidate, path, policy):
        text = path.read_text(encoding='utf-8')
        return any(identifier == key and digest(text) == version
            for key, version, _ in self._receipts(policy))


@dataclass(frozen=True)
class PersistentTarget:
    identifier: str
    version: str
    path: str
    candidate: MemoryCandidate


@dataclass(frozen=True)
class SaveProposal:
    id: str
    candidate: MemoryCandidate | None
    policy: MemoryPolicy
    session: str
    deadline: float
    review_at: datetime
    target: PersistentTarget | None = None
    operation: str = 'save'


class SupervisedMemory:
    def __init__(self, coordinator, repository, evidence, monotonic=None, source_resolver=None, cancelled=None):
        self.coordinator = coordinator
        self.repository = repository
        self.evidence = evidence
        self.monotonic = monotonic or time.monotonic
        self.source_resolver = source_resolver
        self.cancelled = cancelled or (lambda: False)
        self.pending = None
        self.corrections = []
        self.corrections_overflow = False
        self.committed_candidates = set()

    def cancel(self):
        self.pending = None

    def _check(self, proposal=None):
        policy = self.coordinator.policy
        if (self.repository is None or self.evidence is None
                or not policy.allows_write(self.coordinator.clock())):
            raise MemoryError('Gravação supervisionada desativada ou política vencida.')
        if proposal is not None and (proposal.policy != policy
                or self.cancelled()
                or proposal.session != self.coordinator.session_id
                or self.monotonic() >= proposal.deadline
                or (proposal.candidate is not None and proposal.candidate not in self.coordinator.snapshot())):
            raise MemoryError('Proposta vencida, alterada ou revogada. Prepare outra prévia.')
        self.repository._check(policy, self.coordinator.clock(), write=True)
        return policy

    def target(self, identifier):
        policy = self._check()
        if not re.fullmatch(r'RAS-\d{8}-\d{3}', identifier):
            raise MemoryError('Identificador de memória inválido.')
        for key, candidate, path in self.repository._records():
            if key == identifier:
                safe_path(path, policy.read_roots)
                if not self.evidence.valid_record(key, candidate, path, policy):
                    raise MemoryError('Memória não está ativa ou seu comprovante não foi validado.')
                self._check()
                return PersistentTarget(key, digest(path.read_text(encoding='utf-8')), str(path), candidate)
        raise MemoryError('Memória não encontrada neste repositório autorizado.')

    def _validate_target(self, target):
        current = self.target(target.identifier)
        if current != target:
            raise MemoryError('Memória mudou depois da prévia; prepare outra proposta.')

    def prepare_correction(self, identifier, text):
        target = self.target(identifier)
        if ' '.join(text.casefold().split()) == ' '.join(target.candidate.summary.casefold().split()):
            raise MemoryError('O conteúdo é igual ao registro atual; não há correção para salvar.')
        candidate, _ = self.coordinator.explicit(text)
        return self.prepare(candidate, target=target)

    def prepare_retirement(self, identifier):
        target = self.target(identifier)
        self.pending = SaveProposal(uuid.uuid4().hex, None, self.coordinator.policy,
            self.coordinator.session_id, self.monotonic()+300, target.candidate.review_at,
            target=target, operation='retire')
        return self.pending, (f'Desconsiderar memória: {target.identifier}\nConteúdo: {target.candidate.summary}\n'
            f'Origem: {target.candidate.source.identifier}\nArquivo histórico preservado: {target.path}\n'
            f'Destino da mudança de estado: {self.evidence.root}\n'
            'A memória deixará de ser recuperada; nenhuma nota será apagada. Confirme com sim ou não.')

    def prepare(self, candidate, target=None):
        policy = self._check()
        if candidate.session_id != self.coordinator.session_id:
            raise MemoryError('Candidato de outra sessão.')
        resolver = lambda source: source == candidate.source and (source.kind == 'user'
            or bool(self.source_resolver and self.source_resolver(source)))
        if not candidate.source.valid(policy.read_roots, resolver):
            raise MemoryError('Origem não revalidada para salvamento supervisionado.')
        self.pending = SaveProposal(uuid.uuid4().hex, candidate, policy,
            self.coordinator.session_id, self.monotonic() + 300,
            min(candidate.review_at, self.coordinator.clock() + timedelta(days=policy.review_days)),
            target=target, operation='correct' if target else 'save')
        return self.pending, (preview(candidate).split('Ainda não salvei.')[0]
            + f'Destino: {self.repository.root}\n'
            f'Comprovante de origem/consentimento em: {self.evidence.root}\n'
            f'Versão da origem: {candidate.source.version}\n'
            + (f'Correção de {target.identifier}\nConteúdo anterior: {target.candidate.summary}\n'
               'O registro anterior será preservado e deixará de ser recuperado.\n' if target else '')
            +
            'Será criado um RAS não consolidado e um comprovante de origem/consentimento.\n'
            f'Revisão até: {self.pending.review_at.isoformat()}\n'
            'Confirme esta proposta com sim ou não. Ainda não salvei.')

    def confirm(self, proposal_id, session_id, confirmed):
        proposal = self.pending
        self.pending = None  # Uso único inclusive em falha ou resultado incerto.
        if proposal is None or proposal.id != proposal_id or proposal.session != session_id:
            raise MemoryError('Confirmação não corresponde à proposta e à sessão.')
        if type(confirmed) is not bool:
            raise MemoryError('Confirmação ambígua; prepare novamente a proposta.')
        if not confirmed:
            return None
        policy = self._check(proposal)
        if proposal.operation == 'retire':
            def check_retirement():
                self._check(proposal)
                self._validate_target(proposal.target)
            check_retirement()
            self.evidence.retire(proposal.target, policy, proposal.id, proposal.session,
                self.coordinator.clock(), check_retirement)
            self.coordinator._record('retire_memory', proposal.target.identifier, 'retired')
            self.committed_candidates.add(proposal.target.candidate.id)
            return StorageResult('retired', proposal.target.identifier, proposal.target.path)
        candidate = proposal.candidate
        def resolver(source):
            self._check(proposal)
            return source == candidate.source and (source.kind == 'user'
                or bool(self.source_resolver and self.source_resolver(source)))
        def guard():
            self._check(proposal)
            if proposal.target is not None:
                self._validate_target(proposal.target)
            if not candidate.source.valid(policy.read_roots, resolver):
                raise MemoryError('Origem alterada ou revogada durante a gravação.')
        result = self.repository.store(replace(candidate, review_at=proposal.review_at), policy,
            self.coordinator.clock(), resolver, write_guard=guard)
        try:
            self.evidence.record(result, candidate, policy, proposal.id, guard, self.coordinator.clock(),
                transition=proposal.target)
        except (MemoryError, OSError, ValueError, sqlite3.Error) as error:
            raise MemoryError('RAS publicado, mas evidência não confirmada. Resultado incerto; não repeti.') from error
        self.coordinator._record('supervised_save', result.identifier, result.state)
        self.committed_candidates.add(candidate.id)
        return replace(result, state='corrected') if proposal.target else result

    def retrieve(self, query, roots):
        policy = self._check()
        if self.corrections_overflow:
            return ()
        # A política continua independente dos comprovantes históricos.
        narrowed = replace(policy, read_roots=tuple(roots))
        resolver = lambda source: self.evidence.valid_source(source, policy)
        def valid(identifier, candidate, path):
            current = [c for c in self.coordinator.snapshot() if c.source.kind == 'user'
                and c.id != candidate.id and c.id not in self.committed_candidates]
            if any(related_candidates(c, [candidate]) for c in current):
                return False
            words = set(re.findall(r'\w{4,}', control(candidate.summary)))
            for correction in self.corrections:
                if (candidate.kind == 'preferência' and 'prefiro' in control(correction)
                        or len(words & set(re.findall(r'\w{4,}', control(correction)))) >= 2):
                    return False
            return self.evidence.valid_record(identifier, candidate, path, policy)
        result = self.repository.retrieve(query, narrowed, self.coordinator.clock(), resolver,
            record_validator=valid)
        self._check()  # Revalida vigência após leitura dos comprovantes.
        return result


class MemorySupport:
    """Confirmação reutiliza o painel e os tokens de sessão já existentes."""
    def _cancel_memory_save(self):
        self._supervised_memory.cancel()
        if self._pending_memory_plan is not None:
            self._confirmation_id = None
        self._pending_memory_plan = None
        self._memory_plan_fingerprint = None

    def _prepare_memory_save(self):
        if self._confirmation_id is not None:
            raise MemoryError('Há outra proposta aguardando resposta. Conclua ou cancele essa proposta antes de salvar memória.')
        if (self._selected_memory_time is None or time.monotonic() - self._selected_memory_time >= 300):
            raise MemoryError('Selecione um candidato recente antes de salvar.')
        candidate = next((c for c in self.knowledge.snapshot() if c.id == self._selected_memory_id), None)
        if candidate is None:
            raise MemoryError('Qual candidato? Mostre o candidato antes de salvar.')
        proposal, message = self._supervised_memory.prepare(candidate)
        return self._present_memory_proposal(proposal, message, candidate.id, 'salvar memória')

    def _prepare_memory_lifecycle(self, request):
        if self._confirmation_id is not None:
            raise MemoryError('Há outra proposta aguardando resposta. Resolva-a antes de alterar uma memória.')
        if request['operation'] == 'correct':
            proposal, message = self._supervised_memory.prepare_correction(request['identifier'], request['text'])
            self._selected_memory_id = proposal.candidate.id
            self._selected_memory_time = time.monotonic()
        else:
            proposal, message = self._supervised_memory.prepare_retirement(request['identifier'])
        return self._present_memory_proposal(proposal, message, request['identifier'],
            'corrigir memória' if request['operation'] == 'correct' else 'desconsiderar memória')

    def _present_memory_proposal(self, proposal, message, target, action):
        from therion.core.orchestrator import OrchestrationResult
        from therion.core.planner import Plan
        from therion.core.intent import Intent
        plan = Plan(Intent(action=action, target=target, raw_command=action,
            requires_confirmation=True), [message])
        self._pending_memory_plan = plan
        self._memory_plan_fingerprint = self._plan_fingerprint(plan)
        self._confirmation_id = proposal.id
        return OrchestrationResult(status='awaiting_confirmation', plan=plan, message=message,
            speech_message='Preparei a mudança de memória apresentada. Confirma?', confirmation_id=proposal.id)

    def _confirm_memory_save(self, plan, confirmed):
        from therion.core.orchestrator import OrchestrationResult
        if (plan is not self._pending_memory_plan
                or self._plan_fingerprint(plan) != self._memory_plan_fingerprint):
            self._cancel_memory_save()
            return self._stale_confirmation()
        proposal_id = self._confirmation_id
        self._pending_memory_plan = None
        self._memory_plan_fingerprint = None
        self._confirmation_id = None
        try:
            result = self._supervised_memory.confirm(proposal_id, self.session_id, confirmed)
            if result is None:
                message = 'Mudança de memória cancelada. Nenhuma nota foi criada ou alterada.'
            elif result.state == 'retired':
                message = f'Memória {result.identifier} desconsiderada. O arquivo histórico foi preservado e não será recuperado como memória ativa.'
            elif result.state == 'corrected':
                message = f'Correção registrada em {result.identifier}. O registro anterior foi preservado como histórico e deixou de ser recuperado.'
            else:
                message = (f'Rascunho {result.identifier} confirmado em {result.path}. '
                    'Origem registrada para recuperação supervisionada; não é conhecimento consolidado.')
                if getattr(result, 'recovered', False):
                    message += ' A gravação anterior tinha sido interrompida; conferi, liberei a trava e não dupliquei nada.'
            return OrchestrationResult(status='cancelled' if result is None else 'success', message=message)
        except (MemoryError, OSError, ValueError, sqlite3.Error):
            return OrchestrationResult(status='execution_failed', message=(
                'Não confirmei a gravação supervisionada. A proposta foi consumida e não repeti a operação. '
                'Confira os registros antes de preparar outra proposta.'))

    def _memory_save_control(self, command):
        from therion.core.orchestrator import OrchestrationResult
        if self._pending_memory_plan is None:
            return None
        response = self.confirmation_handler.evaluate_response(command.strip().rstrip('.!?'))
        if control(command) in {'cancela', 'cancelar', 'cancele', 'cancele a gravação', 'cancele a gravacao'}:
            response = False
        if response is not None:
            return self._confirm_memory_save(self._pending_memory_plan, response)
        if control(command) in {'talvez', 'acho que sim', 'pode ser'}:
            return OrchestrationResult(status='clarification', message='Confirme a proposta com sim ou não.',
                confirmation_id=self._confirmation_id)
        self._cancel_memory_save()
        return None
