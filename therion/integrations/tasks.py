"""Caixa local persistente de tarefas aprovadas, com referência à origem."""
import json
import uuid
from datetime import datetime,timezone


class TaskInbox:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,title TEXT NOT NULL,state TEXT NOT NULL,source TEXT NOT NULL,due TEXT)')

    @staticmethod
    def validate_due(due):
        if due is not None:
            if not isinstance(due,str):raise ValueError('Prazo precisa de data e fuso explícitos.')
            parsed=datetime.fromisoformat(due)
            if parsed.tzinfo is None:raise ValueError('Prazo precisa de data e fuso explícitos.')

    def create(self, title, source, due=None,*,identifier=None):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 500:
            raise ValueError('Título de tarefa inválido.')
        if not isinstance(source, dict):
            raise ValueError('Origem da tarefa obrigatória.')
        self.validate_due(due)
        identifier = identifier or uuid.uuid4().hex
        import re
        if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f]{32}',identifier):raise ValueError('Identificador de tarefa inválido.')
        origin=json.dumps(source,ensure_ascii=False)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM inbox WHERE id=?',(identifier,)).fetchone()
            if current:
                if self.content_version(dict(current))==self.content_version({'title':title,'state':'pending','source':source,'due':due}):return identifier
                raise ValueError('Este identificador já pertence a outra versão da tarefa.')
            db.execute('INSERT INTO inbox VALUES (?,?,?,?,?)', (identifier,title.strip(),'pending',origin,due))
        return identifier

    @staticmethod
    def content_version(row):
        from therion.agent.proposals import fingerprint
        source=json.loads(row['source']) if isinstance(row['source'],str) else row['source']
        due=datetime.fromisoformat(row['due']).astimezone(timezone.utc).isoformat() if row['due'] else None
        return fingerprint([row['title'].strip(),row['state'],source,due])

    def list(self,*,state=None,limit=100,offset=0):
        if state not in {None,'pending','completed'} or type(limit) is not int or not 1<=limit<=101 or type(offset) is not int or offset<0:raise ValueError('Filtro de tarefas inválido.')
        with self.store.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM inbox WHERE (? IS NULL OR state=?) ORDER BY rowid DESC LIMIT ? OFFSET ?',(state,state,limit,offset))]

    def get(self,identifier):
        with self.store.connection() as db:row=db.execute('SELECT * FROM inbox WHERE id=?',(identifier,)).fetchone()
        if row is None:raise ValueError('Tarefa não encontrada.')
        return dict(row)

    def set_state(self, identifier, state, expected_version=None):
        if state not in {'pending','completed'}:
            raise ValueError('Estado de tarefa inválido.')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if expected_version is not None:
                from therion.agent.proposals import fingerprint
                original=db.execute('SELECT * FROM inbox WHERE id=?',(identifier,)).fetchone()
                if original is None or fingerprint(dict(original))!=expected_version:raise ValueError('Tarefa mudou desde a prévia.')
            if db.execute('UPDATE inbox SET state=? WHERE id=?',(state,identifier)).rowcount != 1:
                raise ValueError('Tarefa não encontrada.')
        return state
