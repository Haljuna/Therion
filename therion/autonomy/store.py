"""Evidências e reservas duráveis. Nenhum conteúdo pessoal é necessário."""
from contextlib import contextmanager
from pathlib import Path
from datetime import timedelta
import sqlite3
import uuid

from .policy import ExecutionEvidence, utcnow
from therion.memory.knowledge import safe_path


class EvidenceStore:
    def __init__(self, path, clock=utcnow):
        self.path, self.clock = Path(path), clock
        self.path = self.path.absolute()
        safe_path(self.path,(str(self.path.parent),))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY, operation TEXT NOT NULL, target TEXT NOT NULL,
                    context_version TEXT NOT NULL, mode TEXT NOT NULL, started_at TEXT NOT NULL,
                    status TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
                    policy_id TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS evidence_scope ON evidence(operation,target,context_version);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS occurrences (
                    id TEXT PRIMARY KEY, state TEXT NOT NULL, started_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        safe_path(self.path,(str(self.path.parent),))
        if self.path.exists() and self.path.stat().st_nlink!=1:
            raise ValueError('Banco de evidências com vínculo não permitido.')
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self, key, default=''):
        with self.connection() as db:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            return row['value'] if row else default

    def set_state(self, key, value):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, value))

    def ready(self, operation, target, version):
        return self.progress(operation,target,version)['ready']

    def verified_openings(self, target):
        """Histórico por aplicativo; separado da elegibilidade da versão atual."""
        with self.connection() as db:
            return db.execute('''SELECT count(*) FROM evidence WHERE operation='open_app'
                AND target=? AND mode IN ('supervised','autonomous')
                AND status='success' AND verified=1''', (target,)).fetchone()[0]

    def progress(self, operation, target, version):
        """Dez sucessos reais supervisionados e sete dias após o primeiro.

        Qualquer falha posterior ao último sucesso inicial reinicia a janela.
        Simulações jamais participam da contagem.
        """
        with self.connection() as db:
            rows = db.execute('''SELECT * FROM evidence WHERE operation=? AND target=?
                AND context_version=? AND mode='supervised' ORDER BY started_at,rowid''',
                (operation, target, version)).fetchall()
        successes = []
        for row in rows:
            if operation == 'open_app' and row['status'] == 'cancelled':
                continue  # Não abrir novamente um processo existente não é falha.
            if row['status'] != 'success' or not row['verified']:
                successes = []
            else:
                successes.append(row)
        from .policy import timestamp
        elapsed=self.clock()-timestamp(successes[0]['started_at']) if successes else timedelta(0)
        return dict(count=len(successes),days=max(0,elapsed.days),
            ready=len(successes)>=10 and elapsed>=timedelta(days=7))

    def begin(self, operation, target, version, mode, policy=None, per_day=10):
        from .policy import OPERATIONS
        if operation not in OPERATIONS or mode not in {'simulation','supervised','autonomous'}:
            raise ValueError('Operação ou modo de evidência inválido.')
        identifier, now = uuid.uuid4().hex, self.clock()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if mode == 'autonomous':
                paused = db.execute('SELECT value FROM state WHERE key=?', ('paused',)).fetchone()
                if paused and paused['value'] == '1':
                    raise ValueError('Toda autonomia está pausada.')
                if db.execute('SELECT value FROM state WHERE key=?', ('incident:'+operation+':'+target,)).fetchone():
                    raise ValueError('Há incidente pendente neste piloto.')
                count = db.execute('''SELECT count(*) FROM evidence WHERE operation=? AND target=?
                    AND mode='autonomous' AND substr(started_at,1,10)=?''',
                    (operation, target, now.date().isoformat())).fetchone()[0]
                if count >= per_day:
                    raise ValueError('Limite diário de autonomia atingido.')
                if db.execute('''SELECT 1 FROM evidence WHERE operation=? AND target=?
                    AND status='running' ''', (operation, target)).fetchone():
                    raise ValueError('Existe execução em andamento ou com resultado incerto.')
            db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?)',
                (identifier, operation, target, version, mode, now.isoformat(), 'running', 0,
                 policy.id if policy else '', policy.revision if policy else 0))
        return identifier

    def finish(self, identifier, status, verified=False):
        if status not in {'success', 'failed', 'uncertain', 'cancelled', 'partial'}:
            raise ValueError('Resultado de execução inválido.')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM evidence WHERE id=? AND status=?', (identifier, 'running')).fetchone()
            if row is None:
                raise ValueError('Tentativa ausente ou já finalizada; não repeti.')
            db.execute('UPDATE evidence SET status=?,verified=? WHERE id=?',
                (status, int(verified and status == 'success'), identifier))
            if status in {'failed', 'uncertain'} and row['mode'] != 'simulation':
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                    ('incident:'+row['operation']+':'+row['target'], identifier))

    def recent(self, limit=50):
        with self.connection() as db:
            return [ExecutionEvidence(**dict(row, verified=bool(row['verified']))) for row in
                db.execute('SELECT * FROM evidence ORDER BY started_at DESC,rowid DESC LIMIT ?', (limit,))]

    def claim_occurrence(self, identifier):
        with self.connection() as db:
            cursor = db.execute('INSERT OR IGNORE INTO occurrences VALUES (?,?,?)',
                (identifier, 'running', self.clock().isoformat()))
            return cursor.rowcount == 1

    def finish_occurrence(self, identifier, state):
        with self.connection() as db:
            db.execute('UPDATE occurrences SET state=? WHERE id=?', (state, identifier))

    def release_unstarted_occurrence(self,identifier):
        """Somente quando o serviço recusou o lock antes de consultar fontes."""
        with self.connection() as db:
            db.execute('DELETE FROM occurrences WHERE id=? AND state=?',(identifier,'running'))

    def review_incident(self, operation, target):
        with self.connection() as db:
            db.execute('DELETE FROM state WHERE key=?', ('incident:'+operation+':'+target,))

