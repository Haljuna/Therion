"""Memória técnica extrativa de recibos, sem seleção livre pelo modelo."""
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

from therion.memory.knowledge import MemoryCandidate,SourceReference,digest,safe_path,validate_candidate
from .integration import implementation_version
from .policy import fingerprint,AutonomyDecision


TEMPLATES={
    'open_app': ('Abertura controlada de aplicativo',
        'Para abrir um aplicativo aprovado, validar cadastro e identidade do executável, '
        'consultar se o caminho já está em execução e verificar o processo após a abertura.'),
    'daily_summary': ('Consulta verificada da agenda',
        'Para apresentar o dia, consultar a agenda autorizada e separar compromissos '
        'em andamento dos próximos compromissos; indisponibilidade produz resultado parcial.'),
    'review_notes': ('Revisão delimitada de notas',
        'Para revisar conhecimento, selecionar de uma a cinco notas autorizadas, respeitar '
        'os limites de contexto e revalidar fontes antes de apresentar indícios sem alterar arquivos.'),
}


class ProcedureMemory:
    def __init__(self,orchestrator,runtime):
        self.orchestrator,self.runtime=orchestrator,runtime

    def configure(self,root):
        self.orchestrator._sync_knowledge_access()
        policy=self.orchestrator.knowledge.policy
        if not policy.allows_write(self.runtime.clock()):
            raise ValueError('A política atual não autoriza escrita de memória. Ative o acesso supervisionado separadamente.')
        selected=str(Path(root).resolve())
        if selected!=str(Path(policy.write_root).resolve()):
            raise ValueError('Escolha o destino temporário já autorizado pela política de memória.')
        safe_path(root,policy.read_roots)
        previous=self.runtime.section().get('procedure_memory',{})
        if previous.get('root'):self.runtime.revoke('remember_procedure',previous['root'])
        self.runtime._update(lambda s:s.update(procedure_memory=dict(root=selected,
            authorization='Destino temporário selecionado visualmente pelo usuário.')))

    def scope(self):
        section=self.runtime.section().get('procedure_memory',{})
        if not isinstance(section,dict) or not section.get('authorization') or not isinstance(section.get('root'),str):
            raise ValueError('Selecione o destino temporário no painel Autonomia.')
        self.orchestrator._sync_knowledge_access()
        policy=self.orchestrator.knowledge.policy
        root=section['root']
        if (not policy.allows_write(self.runtime.clock()) or root!=policy.write_root
                or self.orchestrator._knowledge_repository is None
                or self.orchestrator._supervised_memory.evidence is None):
            raise ValueError('O acesso de escrita de memória não está vigente.')
        safe_path(root,policy.read_roots)
        version=implementation_version(self.runtime,dict(memory=section,
            access=self.runtime.loader().get('knowledge_access',{}),policy=repr(policy)))
        return root,version,policy

    def candidates(self):
        now=self.runtime.clock()
        with self.runtime.store.connection() as db:
            rows=db.execute('''SELECT * FROM evidence WHERE status='success' AND verified=1
                AND mode IN ('supervised','autonomous') ORDER BY started_at DESC,id''').fetchall()
        grouped={}
        for row in rows:
            if row['operation'] in TEMPLATES:
                grouped.setdefault((row['operation'],row['target'],row['context_version']),[]).append(row)
        result=[]
        for key,rows in grouped.items():
            if len(rows)<2:continue
            operation,target,version=key
            # IDs de recibos e texto fixo, sem nomes/caminhos ou conteúdo de fontes.
            evidence='Duas execuções distintas verificadas: '+', '.join(sorted(r['id'] for r in rows[:2]))+'.'
            payload=json.dumps(dict(operation=operation,target=target,version=version,
                receipts=sorted(r['id'] for r in rows[:2]),evidence=evidence),sort_keys=True,ensure_ascii=False)
            source=SourceReference('V4-PROCEDURE:'+fingerprint(key),'verified_operation',digest(payload),payload)
            title,summary=TEMPLATES[operation]
            candidate=MemoryCandidate('V4-MEM-'+digest(payload)[:12],self.orchestrator._session_id,
                title,summary,'procedimento','Procedimento técnico recorrente comprovado por recibos locais.',
                evidence,source,now,now+timedelta(days=30),model='Código determinístico V4')
            if self.valid_source(source):result.append(validate_candidate(candidate))
            if len(result)==3:break
        return result

    def valid_source(self,source):
        try:
            if source.kind!='verified_operation' or digest(source.text)!=source.version:return False
            data=json.loads(source.text)
            if data['operation'] not in TEMPLATES or len(set(data['receipts']))!=2:return False
            with self.runtime.store.connection() as db:
                rows=[db.execute('SELECT * FROM evidence WHERE id=?',(identifier,)).fetchone()
                    for identifier in data['receipts']]
            return all(row and row['status']=='success' and row['verified']
                and row['mode'] in {'supervised','autonomous'}
                and (row['operation'],row['target'],row['context_version'])==
                    (data['operation'],data['target'],data['version']) for row in rows)
        except (ValueError,KeyError,TypeError):return False

    def save(self,candidate,*,supervised=False,simulation=False):
        with self.orchestrator._operation_lock:
            return self._save(candidate,supervised=supervised,simulation=simulation)

    def _save(self,candidate,*,supervised=False,simulation=False):
        """Recebe apenas um candidato reconstruível a partir dos recibos confiáveis."""
        root,version,policy=self.scope()
        expected=next((c for c in self.candidates() if c.source==candidate.source),None)
        if expected is None or (candidate.summary,candidate.kind,candidate.title,candidate.evidence)!=\
                (expected.summary,expected.kind,expected.title,expected.evidence):
            raise ValueError('Candidato não corresponde ao procedimento técnico verificado.')
        decision=self.runtime.decide('remember_procedure',root,version,permitted=True)
        if not supervised and decision.mode!='autonomous':
            raise ValueError('Memória técnica permanece supervisionada.')
        if supervised:decision=AutonomyDecision('confirmation','Gravação específica confirmada no painel.')
        attempt=self.runtime.begin('remember_procedure',root,version,decision,permitted=True,simulation=simulation)
        def guard():
            current_root,current_version,current_policy=self.scope()
            if (current_root,current_version,current_policy)!=(root,version,policy) or not self.valid_source(candidate.source):
                raise ValueError('Fonte ou política mudou antes da publicação.')
            if not supervised and self.runtime.decide('remember_procedure',root,version,permitted=True)!=decision:
                raise ValueError('Autorização de memória revogada ou pausada.')
        try:
            guard()
            if simulation:
                self.runtime.store.finish(attempt,'success',False)
                return 'Simulei a gravação do procedimento; nenhum rascunho foi publicado.'
            repository=self.orchestrator._knowledge_repository
            result=repository.store(candidate,policy,self.runtime.clock(),self.valid_source,guard)
            stored_candidate=candidate
            if result.state=='existing':
                from therion.memory.repository import deserialize
                _,stored_candidate=deserialize(Path(result.path).read_text(encoding='utf-8'))
                if stored_candidate.summary!=candidate.summary or not self.valid_source(stored_candidate.source):
                    raise ValueError('O rascunho existente não tem a mesma origem técnica verificada.')
            self.orchestrator._supervised_memory.evidence.record(result,stored_candidate,policy,
                'V4:'+attempt,guard,self.runtime.clock())
            self.runtime.store.finish(attempt,'success',True)
            self.runtime.store.set_state('procedure:'+root+':'+candidate.source.version,result.identifier)
            return f'{result.identifier}: '+('rascunho técnico guardado.' if result.state=='stored' else 'rascunho já existente; não dupliquei.')
        except Exception:
            try:self.runtime.store.finish(attempt,'uncertain')
            except Exception:pass
            raise ValueError('Não confirmei a publicação do rascunho. Não repeti a operação.')

    def poll(self):
        if not self.orchestrator._operation_lock.acquire(False):return []
        try:
            root,version,_=self.scope()
            if self.runtime.decide('remember_procedure',root,version,permitted=True).mode!='autonomous':return []
            messages=[]
            for candidate in self.candidates():
                if not self.runtime.store.state('procedure:'+root+':'+candidate.source.version):
                    messages.append(self.save(candidate))
            return messages
        finally:
            self.orchestrator._operation_lock.release()
