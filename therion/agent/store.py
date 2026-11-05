"""Histórico opt-in e recibos sem payload, com retenção também na leitura."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from therion.memory.knowledge import safe_path


class SessionStore:
    def __init__(self, path, *, enabled=False, clock=None):
        self.path = Path(path).absolute()
        self.enabled = enabled is True
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self.source_validator = lambda references: not references
        self._root = str(self.path.parent.resolve())
        safe_path(self.path, (self._root,))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .security import restrict_directory
        restrict_directory(self.path.parent)
        with self.connection() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError('Versão de histórico não suportada; banco preservado.')
            if version == 1:
                backups = self.path.parent / 'migration-backups'
                safe_path(backups,(self._root,))
                backups.mkdir(exist_ok=True)
                restrict_directory(backups)
                target = backups / ('v1-' + uuid.uuid4().hex + '.sqlite3')
                with closing(sqlite3.connect(target)) as snapshot:
                    db.backup(snapshot)
            db.execute('BEGIN IMMEDIATE')
            schema = '''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(content, tokenize='unicode61 remove_diacritics 2');
                CREATE TABLE IF NOT EXISTS receipts(call_id TEXT PRIMARY KEY, session TEXT NOT NULL,
                    turn_id TEXT NOT NULL, tool TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    effect TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS resources(id TEXT NOT NULL,operation TEXT NOT NULL,
                    session TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(id,operation));
            '''
            for statement in schema.split(';'):
                if statement.strip(): db.execute(statement)
            if 'sources' not in {row[1] for row in db.execute('PRAGMA table_info(messages)')}:
                db.execute("ALTER TABLE messages ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")
            if version==1:
                db.execute("UPDATE messages SET sources=? WHERE role='assistant' AND sources='[]'",(json.dumps([{'id':'legacy:unverified','source':'origem indisponível antes da migração'}]),))
            if 'verified' not in {row[1] for row in db.execute('PRAGMA table_info(receipts)')}:
                db.execute('ALTER TABLE receipts ADD COLUMN verified INTEGER NOT NULL DEFAULT 0')
            db.execute('PRAGMA user_version=2')

    @contextmanager
    def connection(self):
        safe_path(self.path, (self._root,))
        if self.path.exists() and self.path.stat().st_nlink != 1:
            raise ValueError('Histórico com vínculo não permitido.')
        try:db = sqlite3.connect(self.path, timeout=5)
        except sqlite3.DatabaseError as error:raise OSError('Histórico indisponível; o banco foi preservado. Não criei uma conversa vazia para substituir os dados.') from error
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        except sqlite3.DatabaseError as error:
            raise OSError('Não consegui acessar o histórico ou os recibos. Preservei o banco; não repita ações sem consultar seu resultado.') from error
        finally:
            db.close()

    def append(self, session, role, content, *, temporary=False, sources=()):
        if not self.enabled or temporary:
            return None
        if role not in {'user', 'assistant'} or not isinstance(content, str) or len(content) > 16000:
            raise ValueError('Mensagem inválida para histórico.')
        now = self.clock()
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO sessions VALUES (?,?)', (session, now))
            cursor = db.execute('INSERT INTO messages(session,role,content,created,expires,sources) VALUES (?,?,?,?,?,?)',
                                (session, role, content, now, now + 30 * 86400,json.dumps(list(sources),ensure_ascii=False)))
            db.execute('INSERT INTO message_search(rowid,content) VALUES (?,?)', (cursor.lastrowid, content))
            return cursor.lastrowid

    def search(self, query, *, session=None, limit=10, offset=0):
        import re
        terms = re.findall(r'\w+', query, re.UNICODE)[:12]
        if not self.enabled or not terms:
            return []
        expression = ' OR '.join('"' + term.replace('"', '""') + '"' for term in terms)
        with self.connection() as db:
            return [dict(row) for row in db.execute('''SELECT m.* FROM message_search f
                JOIN messages m ON m.id=f.rowid WHERE message_search MATCH ? AND m.expires>?
                AND (? IS NULL OR m.session=?) ORDER BY bm25(message_search),m.created DESC LIMIT ? OFFSET ?''',
                (expression, self.clock(), session, session, min(max(limit, 1), 50), max(offset, 0))) if self._allowed(row)]

    def messages(self, session, *, offset=0, limit=50):
        if not self.enabled:
            return []
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM messages WHERE session=? AND expires>? ORDER BY id LIMIT ? OFFSET ?',
                (session, self.clock(), min(max(limit, 1), 100), max(offset, 0))) if self._allowed(row)]

    def _allowed(self,row):
        try:return self.source_validator(json.loads(row['sources'])) is True
        except (ValueError,TypeError,OSError):return False

    def iter_messages(self, session):
        if not self.enabled:return
        with self.connection() as db:
            for row in db.execute('SELECT * FROM messages WHERE session=? AND expires>? ORDER BY id', (session,self.clock())):
                if self._allowed(row):yield dict(row)

    def sessions(self):
        if not self.enabled:
            return []
        with self.connection() as db:
            sessions={}
            for row in db.execute('SELECT * FROM messages WHERE expires>? ORDER BY created DESC', (self.clock(),)):
                if self._allowed(row):
                    summary=sessions.setdefault(row['session'],dict(session=row['session'],messages=0,updated=row['created']))
                    summary['messages']+=1
            return list(sessions.values())

    def delete(self, session=None):
        with self.connection() as db:
            if session is None:
                db.execute('DELETE FROM message_search')
                db.execute('DELETE FROM messages')
                db.execute('DELETE FROM sessions')
            else:
                db.execute('DELETE FROM message_search WHERE rowid IN (SELECT id FROM messages WHERE session=?)', (session,))
                db.execute('DELETE FROM messages WHERE session=?', (session,))
                db.execute('DELETE FROM sessions WHERE id=?', (session,))
        self._clean_backups(session=session, deleting=True)

    def purge(self):
        with self.connection() as db:
            db.execute('DELETE FROM message_search WHERE rowid IN (SELECT id FROM messages WHERE expires<=?)', (self.clock(),))
            db.execute('DELETE FROM messages WHERE expires<=?', (self.clock(),))
            db.execute('DELETE FROM sessions WHERE id NOT IN (SELECT session FROM messages)')
        self._clean_backups()

    def _clean_backups(self, *, session=None, deleting=False):
        """Backups de migração não restauram conteúdo excluído ou expirado."""
        folder=self.path.parent/'migration-backups'
        if not folder.exists():return
        for candidate in folder.glob('v1-*.sqlite3'):
            path=safe_path(candidate,(str(folder.resolve()),))
            if path.stat().st_nlink!=1:raise ValueError('Backup de migração com vínculo inválido.')
            if (deleting and session is None) or path.stat().st_mtime<=self.clock()-30*86400:
                path.unlink();continue
            with closing(sqlite3.connect(path)) as db, db:
                if deleting:
                    db.execute('DELETE FROM message_search WHERE rowid IN (SELECT id FROM messages WHERE session=?)',(session,))
                    db.execute('DELETE FROM messages WHERE session=?',(session,))
                    db.execute('DELETE FROM sessions WHERE id=?',(session,))
                else:
                    db.execute('DELETE FROM message_search WHERE rowid IN (SELECT id FROM messages WHERE expires<=?)',(self.clock(),))
                    db.execute('DELETE FROM messages WHERE expires<=?',(self.clock(),))
                    db.execute('DELETE FROM sessions WHERE id NOT IN (SELECT session FROM messages)')

    def export(self, session):
        return json.dumps(list(self.iter_messages(session)), ensure_ascii=False, indent=2)

    def begin(self, call, session, turn, effect):
        import hashlib
        operation_key=call.fingerprint
        normalized=False
        # IDs de criação e de confirmação são gerados pelo controlador. Não
        # podem transformar outra tentativa do mesmo efeito incerto em inédita.
        if call.name=='gmail.send_draft' and call.arguments.get('content_identity'):
            operation_key=json.dumps([call.name,call.arguments.get('_account'),call.arguments['content_identity']],sort_keys=True);normalized=True
        elif call.name=='calendar.create' and call.arguments.get('expected_version'):
            operation_key=json.dumps([call.name,call.arguments.get('_account'),call.arguments['expected_version']],sort_keys=True);normalized=True
        elif call.name=='tasks.create' and call.arguments.get('expected_result'):
            operation_key=json.dumps([call.name,call.arguments.get('dedup_key',call.arguments['expected_result'])],sort_keys=True);normalized=True
        elif call.name=='apps.open' and call.arguments.get('command'):
            operation_key=json.dumps([call.name,call.arguments['command']],sort_keys=True);normalized=True
        fingerprint = ('v2:' if normalized else '')+hashlib.sha256(operation_key.encode()).hexdigest()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if normalized and effect not in {'read','prepare'} and db.execute("SELECT 1 FROM receipts WHERE tool=? AND state IN ('running','uncertain') AND fingerprint NOT LIKE 'v2:%'",(call.name,)).fetchone():
                raise ValueError('Há recibo antigo incerto desta operação; reconcilie antes de preparar nova tentativa.')
            if effect not in {'read','prepare'} and db.execute('SELECT 1 FROM receipts WHERE fingerprint=? AND state IN (\'running\',\'uncertain\')', (fingerprint,)).fetchone():
                raise ValueError('Operação anterior incerta; não repeti o efeito.')
            db.execute('INSERT INTO receipts(call_id,session,turn_id,tool,fingerprint,effect,state,created) VALUES (?,?,?,?,?,?,?,?)',
                       (call.id, session, turn, call.name, fingerprint, effect, 'running', self.clock()))

    def finish(self, call_id, state, *, verified=False):
        with self.connection() as db:
            db.execute('UPDATE receipts SET state=?,verified=? WHERE call_id=?', (state,int(state=='success' and verified is True),call_id))

    def interrupted(self):
        with self.connection() as db:
            db.execute("UPDATE receipts SET state='expired_confirmation',verified=0 WHERE state='awaiting_confirmation'")
            db.execute("UPDATE receipts SET state=CASE WHEN effect IN ('read','prepare') THEN 'interrupted' ELSE 'uncertain' END WHERE state='running'")
            return [dict(row) for row in db.execute("SELECT * FROM receipts WHERE state IN ('interrupted','uncertain')")]

    def resource(self,identifier,operation,session):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO resources VALUES (?,?,?,?)',(identifier,operation,session,self.clock()))

    def resources(self,operation):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM resources WHERE operation=? ORDER BY created DESC LIMIT 100',(operation,))]

    def operations(self, call_id=None):
        with self.connection() as db:
            rows=[dict(row) for row in db.execute('SELECT call_id,session,turn_id,tool,state,created,verified FROM receipts WHERE (? IS NULL OR call_id=?) ORDER BY created DESC LIMIT 50',(call_id,call_id))]
        for row in rows:
            # SQLite armazena 0/1; a API operacional entrega booleano tipado.
            row['verified']=row['verified']==1 and row['state']=='success'
            row['result_refs']=[]
            for resource in self.resources('receipt:'+row['call_id']):
                try:reference=json.loads(resource['id'])
                except ValueError:reference={'id':resource['id']}
                if isinstance(reference,dict):row['result_refs'].append(reference)
        return rows
