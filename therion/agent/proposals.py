"""Prévia visual de uso único; o modelo só prepara, o usuário decide."""
from copy import deepcopy
import asyncio
from dataclasses import dataclass,replace
import hashlib
import json
import threading
import time
import uuid

from .contracts import ToolCall, ToolResult,Cancelled

_EFFECT_GATE=threading.Lock()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Proposal:
    id: str
    session: str
    operation: str
    preview: str
    digest: str
    expires: float
    dependencies:tuple=()


class ActionProposals:
    def __init__(self, store, session, clock=time.monotonic,*,dependencies=None,verify_dependencies=None):
        self.store, self.session, self.clock = store, session, clock
        self._pending = {}
        self._lock = threading.Lock()
        self._running={}
        self._completed={}
        self.dependencies=dependencies or (lambda:())
        self.verify_dependencies=verify_dependencies or (lambda sources,token:not sources)

    def prepare(self, operation, arguments, preview, execute, verify, revalidate, *, token_aware=False,preparation_token=None):
        if preparation_token:preparation_token.check()
        frozen = deepcopy(arguments)
        dependencies=tuple(deepcopy(self.dependencies()))
        digest=fingerprint([operation,frozen,dependencies] if dependencies else [operation,frozen])
        if dependencies:
            preview+='\n\nFontes vinculadas à prévia:\n'+'\n'.join(str(source.get('id',''))+' — '+str(source.get('source',''))+' — '+str(source.get('version','')) for source in dependencies)
        row = Proposal(uuid.uuid4().hex, self.session(), operation, preview,
                       digest, self.clock()+300,dependencies)
        with self._lock:
            if preparation_token:preparation_token.check()
            self._pending[row.id] = (row, frozen, execute, verify, revalidate, token_aware)
        return row

    def list(self):
        with self._lock:
            self._pending = {key:item for key,item in self._pending.items()
                             if item[0].session == self.session() and item[0].expires > self.clock()}
            return [item[0] for item in self._pending.values()]

    def discard(self, identifier):
        with self._lock:
            self._pending.pop(identifier, None)
            if identifier in self._running:self._running[identifier].cancel()

    def clear(self):
        with self._lock:
            self._pending.clear()
            for token in self._running.values():token.cancel()

    def approve_visual(self, identifier, expected_digest, token):
        with self._lock:
            if identifier in self._running:return ToolResult('blocked',message='Esta operação já está em andamento.')
            self._running[identifier]=token
        try:
            result=self._approve_visual(identifier,expected_digest,token)
            with self._lock:
                self._completed[identifier]=result
                while len(self._completed)>128:self._completed.pop(next(iter(self._completed)))
            return result
        finally:
            with self._lock:self._running.pop(identifier,None)

    async def wait_for_result(self, identifier, token, seconds):
        """Somente approve_visual resolve a espera; texto do modelo não confirma."""
        deadline=time.monotonic()+seconds
        interrupted=None
        while True:
            with self._lock:
                result=self._completed.pop(identifier,None)
                item=self._pending.get(identifier)
                running=self._running.get(identifier)
            if result is not None:
                if result.status=='success':
                    receipts=[self.store.operations(source['id'][8:]) for source in result.evidence if source.get('id','').startswith('receipt:')]
                    simulated=result.side_effect_state=='none' and isinstance(result.data,dict) and result.data.get('simulated') is True
                    if not any(row['session']==self.session() and row['turn_id']==identifier and ((row['state']=='success' and row['verified']) or (simulated and row['state']=='simulated')) for group in receipts for row in group):
                        return ToolResult('uncertain',message='Não confirmei o recibo desta aprovação.',side_effect_state='uncertain')
                return result
            expired=time.monotonic()>=deadline or (item is not None and (item[0].session!=self.session() or item[0].expires<=self.clock()))
            if token.cancelled or expired or (item is None and running is None):
                self.discard(identifier)
                if running is None:return ToolResult('cancelled',message='Confirmação cancelada ou vencida; não iniciei o efeito.')
                if interrupted is None:interrupted=time.monotonic()
                if time.monotonic()-interrupted>=2:
                    return ToolResult('uncertain',message='A operação ainda não confirmou o término. Consulte o recibo antes de repetir.',side_effect_state='uncertain')
            await asyncio.sleep(.025)

    def _approve_visual(self, identifier, expected_digest, token):
        with self._lock:
            item = self._pending.pop(identifier, None)
        if item is None:
            return ToolResult('blocked', message='Proposta ausente ou já consumida.')
        row, arguments, execute, verify, revalidate, token_aware = item
        def validate_current():
            if row.session!=self.session() or row.expires<=self.clock():return False
            if row.dependencies and self.verify_dependencies(row.dependencies,token) is not True:return False
            valid=revalidate(arguments,token) if token_aware else revalidate(arguments)
            token.check()
            return valid is True and row.session==self.session() and row.expires>self.clock() and (not row.dependencies or self.verify_dependencies(row.dependencies,token) is True)
        if (row.session != self.session() or row.expires <= self.clock()
                or row.digest != expected_digest or row.digest != fingerprint([row.operation, arguments,row.dependencies] if row.dependencies else [row.operation,arguments])):
            return ToolResult('blocked', message='Proposta mudou ou venceu; prepare outra prévia.')
        try:
            token.check()
            if validate_current() is not True:return ToolResult('blocked', message='Fonte, destino ou autorização mudou desde a prévia.')
            token.check()
        except Cancelled:return ToolResult('cancelled',message='Operação cancelada antes do efeito.')
        except Exception:return ToolResult('unavailable',message='Não consegui revalidar a origem ou a autorização. Não executei a operação.')
        call = ToolCall(row.operation, arguments)
        try:self.store.begin(call, row.session, row.id, 'external')
        except ValueError as error:return ToolResult('blocked',message=str(error))
        value=None;effect_started=False;gate_acquired=False
        def identifiers():
            return {key:value[key] for key in ('id','path','version','original_path','original_version') if isinstance(value,dict) and key in value}
        try:
            wait_deadline=time.monotonic()+300
            while not gate_acquired:
                token.check()
                if row.expires<=self.clock() or time.monotonic()>=wait_deadline:raise TimeoutError('Confirmação venceu aguardando outra operação.')
                gate_acquired=_EFFECT_GATE.acquire(timeout=.025)
            token.check()
            if validate_current() is not True:
                result = ToolResult('blocked', message='Autorização revogada antes do efeito.')
            else:
                token.check()
                targets={key:arguments[key] for key in ('id','path','draft_id','message_id','_account','expected_version','expected_result','add','remove') if key in arguments}
                if targets:self.store.resource(json.dumps(targets,ensure_ascii=False),'receipt:'+call.id,row.session)
                token.check()
                effect_started=True
                value = execute(arguments,token) if token_aware else execute(arguments)
                if isinstance(value,ToolResult):
                    outcome=value;value=outcome.data
                    verified=outcome.status!='success' or (not token.cancelled and (verify(arguments,outcome,token) if token_aware else verify(arguments,outcome)) is True)
                    result=outcome if verified else ToolResult('uncertain',message='Não consegui verificar o resultado do executor. Não repeti.',side_effect_state='uncertain')
                else:
                    result = (ToolResult('success', data=value, message='Operação executada e verificada.', side_effect_state='verified')
                        if not token.cancelled and (verify(arguments,value,token) if token_aware else verify(arguments,value)) is True else ToolResult('uncertain', message='Não consegui verificar o efeito. Não repeti.', side_effect_state='uncertain'))
                if result.status=='success' and isinstance(value,dict) and value.get('already_satisfied') is True:
                    result=ToolResult('success',data=value,message='A condição já estava atendida; não repeti a ação.',side_effect_state='none')
        except Cancelled:
            result=ToolResult('uncertain' if effect_started else 'cancelled',data=identifiers(),message='Operação interrompida. Não repeti o efeito.',side_effect_state='uncertain' if effect_started else 'none')
        except Exception:
            result = ToolResult('uncertain' if effect_started else 'unavailable',data=identifiers(), message='Resultado externo incerto. Não repeti a operação.' if effect_started else 'A revalidação falhou; não executei o efeito.', side_effect_state='uncertain' if effect_started else 'none')
        finally:
            if gate_acquired:_EFFECT_GATE.release()
        simulated=result.status=='success' and result.side_effect_state=='none' and isinstance(result.data,dict) and result.data.get('simulated') is True
        self.store.finish(call.id, 'simulated' if simulated else result.status, verified=result.side_effect_state=='verified' or (result.status=='success' and isinstance(result.data,dict) and result.data.get('already_satisfied') is True))
        if result.status=='success' and isinstance(result.data,dict) and isinstance(result.data.get('id'),str):
            self.store.resource(result.data['id'],row.operation,row.session)
        if result.status in {'success','uncertain'}:
            references=identifiers()
            if references:self.store.resource(json.dumps(references,ensure_ascii=False),'receipt:'+call.id,row.session)
        evidence=result.evidence+({'id':'receipt:'+call.id,'source':'recibo operacional local','operation':row.operation},)
        if result.status=='success' and result.side_effect_state=='verified' and isinstance(result.data,dict) and result.data.get('path') and result.data.get('version'):
            import os
            path=result.data['path']
            previous=next((source for source in row.dependencies if isinstance(source.get('source'),str) and
                os.path.normcase(os.path.abspath(source['source']))==os.path.normcase(os.path.abspath(path))),None)
            if previous:evidence+=({'id':path,'source':previous['source'],'version':result.data['version']},)
        return replace(result,evidence=evidence)
