"""Procedimentos declarativos versionados; nunca importam ou executam código."""
from .proposals import fingerprint
import json
import uuid

STATES={'proposed','testing','active','review','retired'}


class ProcedureLibrary:
    def __init__(self,store):
        self.store=store
        with store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS procedures(id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,state TEXT NOT NULL,source TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(id,revision))')
            db.execute('CREATE TABLE IF NOT EXISTS procedure_tests(id TEXT NOT NULL,revision INTEGER NOT NULL,receipt TEXT NOT NULL,PRIMARY KEY(id,revision,receipt))')

    def index(self):
        with self.store.connection() as db:
            rows=db.execute('SELECT * FROM procedures p WHERE revision=(SELECT max(revision) FROM procedures WHERE id=p.id) AND state!=\'retired\' ORDER BY rowid DESC LIMIT 100').fetchall()
        return [{'id':row['id'],'revision':row['revision'],'title':json.loads(row['body'])['title'],'state':row['state']} for row in rows]

    def get(self,identifier):
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM procedures WHERE id=? ORDER BY revision DESC LIMIT 1',(identifier,)).fetchone()
        if row is None:raise ValueError('Procedimento não encontrado.')
        return dict(row,body=json.loads(row['body']))

    def propose(self,body,source,identifier=None,expected_digest=None,*,token=None):
        required={'title','goal','preconditions','tools','steps','verification','limitations'}
        if not isinstance(body,dict) or set(body)!=required or not all(isinstance(body[key],str) and 0<len(body[key])<=2000 for key in required):
            raise ValueError('Procedimento precisa de campos declarativos completos.')
        from therion.memory.knowledge import sensitive
        if sensitive(json.dumps(body,ensure_ascii=False)):
            raise ValueError('Conteúdo sensível ou incerto não entra em procedimento técnico.')
        source=json.dumps(source,ensure_ascii=False)
        digest=fingerprint(body)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if token:token.check()
            revision=1
            if identifier:
                previous=db.execute('SELECT * FROM procedures WHERE id=? ORDER BY revision DESC LIMIT 1',(identifier,)).fetchone()
                if previous is None or previous['digest']!=expected_digest:raise ValueError('Leia a revisão atual antes de propor alteração.')
                if previous['digest']==digest:return identifier
                revision=previous['revision']+1
            else:
                existing=db.execute('SELECT id FROM procedures WHERE digest=?',(digest,)).fetchone()
                if existing:return existing['id']
                identifier=uuid.uuid4().hex
            db.execute('INSERT INTO procedures VALUES (?,?,?,?,?,?)',(identifier,revision,json.dumps(body,ensure_ascii=False),'proposed',source,digest))
            if token:token.check()
        return identifier

    def transition(self,identifier,state,expected_digest):
        if state not in STATES:raise ValueError('Estado de procedimento inválido.')
        row=self.get(identifier)
        if row['digest']!=expected_digest:raise ValueError('Procedimento mudou desde a prévia.')
        allowed={'proposed':{'testing','retired'},'testing':{'active','review','retired'},
                 'active':{'review','retired'},'review':{'testing','retired'},'retired':set()}
        if state not in allowed[row['state']]:raise ValueError('Transição de revisão não permitida.')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT revision,digest,state FROM procedures WHERE id=? ORDER BY revision DESC LIMIT 1',(identifier,)).fetchone()
            if current['digest']!=expected_digest or current['state']!=row['state']:raise ValueError('Procedimento mudou desde a prévia.')
            if state=='active':
                import re
                tools=set(re.findall(r'[A-Za-z][A-Za-z0-9_.]{0,63}',row['body']['tools']))
                receipts=db.execute("SELECT r.call_id,r.tool FROM procedure_tests t JOIN receipts r ON r.call_id=t.receipt WHERE t.id=? AND t.revision=? AND r.state='success' AND r.verified=1",(identifier,row['revision']))
                if len({receipt['call_id'] for receipt in receipts if receipt['tool'] in tools})<2:raise ValueError('Ativação exige dois recibos de teste distintos e verificados.')
                provenance=json.loads(row['source'])
                if provenance.get('kind')=='revision_candidate':
                    parent=db.execute('SELECT * FROM procedures WHERE id=? ORDER BY revision DESC LIMIT 1',(provenance['parent_id'],)).fetchone()
                    if parent is None or parent['digest']!=provenance['parent_digest'] or parent['state'] not in {'active','review'}:
                        raise ValueError('O procedimento original mudou; revise a proposta de substituição.')
                    db.execute("UPDATE procedures SET state='retired' WHERE id=? AND revision=?",(parent['id'],parent['revision']))
            db.execute('UPDATE procedures SET state=? WHERE id=? AND revision=? AND digest=?',(state,identifier,row['revision'],expected_digest))
        return state

    def propose_revision(self,identifier,expected_digest,body,source,*,token=None):
        """Candidata separada: mantém a versão ativa até a revisão e os testes."""
        import difflib
        parent=self.get(identifier)
        if parent['digest']!=expected_digest:raise ValueError('Leia a revisão atual antes de propor alteração.')
        if parent['state'] not in {'active','review'}:raise ValueError('Use a revisão direta para procedimentos ainda não ativados.')
        before=json.dumps(parent['body'],ensure_ascii=False,indent=2).splitlines()
        after=json.dumps(body,ensure_ascii=False,indent=2).splitlines()
        diff='\n'.join(difflib.unified_diff(before,after,fromfile='Atual',tofile='Proposta',lineterm=''))
        if not diff:return identifier
        return self.propose(body,{'kind':'revision_candidate','parent_id':identifier,'parent_digest':expected_digest,'diff':diff,'origin':source},token=token)

    def record_test(self,identifier,receipt):
        row=self.get(identifier)
        if row['state']!='testing':raise ValueError('Procedimento não está em teste.')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT revision,digest,state FROM procedures WHERE id=? ORDER BY revision DESC LIMIT 1',(identifier,)).fetchone()
            if current['revision']!=row['revision'] or current['digest']!=row['digest'] or current['state']!='testing':raise ValueError('Procedimento mudou desde a revisão.')
            evidence=db.execute('SELECT * FROM receipts WHERE call_id=? AND state=\'success\' AND verified=1',(receipt,)).fetchone()
            if evidence is None:raise ValueError('Recibo de teste não verificado.')
            import re
            tools=set(re.findall(r'[A-Za-z][A-Za-z0-9_.]{0,63}',row['body']['tools']))
            if evidence['tool'] not in tools:raise ValueError('O recibo não pertence às ferramentas deste procedimento.')
            db.execute('INSERT OR IGNORE INTO procedure_tests VALUES (?,?,?)',(identifier,row['revision'],receipt))
