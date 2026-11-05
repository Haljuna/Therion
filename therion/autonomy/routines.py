"""Rotinas fixas, seleção explícita e ocorrências idempotentes."""
from dataclasses import dataclass
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import threading
import uuid

from therion.context.second_brain import SecondBrainReader
from therion.context.knowledge_review import KnowledgeReview
from therion.skills.plan_day import PlanDaySkill
from .integration import implementation_version


@dataclass(frozen=True)
class RoutineSpec:
    id: str
    operation: str
    hour: int
    minute: int
    weekday: int | None = None
    sources: tuple[str,...] = ()
    enabled: bool = False
    timezone: str = 'America/Sao_Paulo'

    @classmethod
    def parse(cls,row):
        if (not isinstance(row,dict) or row.get('operation') not in {'daily_summary','review_notes'}
                or not isinstance(row.get('id'),str) or not row['id']
                or type(row.get('enabled')) is not bool
                or type(row.get('hour')) is not int or not 0<=row['hour']<24
                or type(row.get('minute')) is not int or not 0<=row['minute']<60
                or row.get('timezone')!='America/Sao_Paulo'
                or not isinstance(row.get('sources'),list)
                or any(not isinstance(s,str) or not s for s in row['sources'])):
            raise ValueError('Rotina inválida.')
        weekly=row['operation']=='review_notes'
        weekday=row.get('weekday')
        if ((weekly and (type(weekday) is not int or not 0<=weekday<=6 or not 1<=len(row['sources'])<=5))
                or (not weekly and (weekday is not None or row['sources']))):
            raise ValueError('Escolha até cinco notas na revisão semanal; resumo diário usa somente agenda.')
        if len(set(row['sources']))!=len(row['sources']):
            raise ValueError('Notas repetidas na rotina.')
        return cls(row['id'],row['operation'],row['hour'],row['minute'],weekday,
            tuple(row['sources']),row['enabled'],row['timezone'])

    def as_dict(self):
        return dict(self.__dict__,sources=list(self.sources))

    def latest(self,now):
        local=now.astimezone(ZoneInfo(self.timezone))
        occurrence=local.replace(hour=self.hour,minute=self.minute,second=0,microsecond=0)
        if self.weekday is not None:
            occurrence-=timedelta(days=(occurrence.weekday()-self.weekday)%7)
        if occurrence>local:
            occurrence-=timedelta(days=7 if self.weekday is not None else 1)
        return occurrence


@dataclass(frozen=True)
class RoutineResult:
    status: str
    message: str
    attempt: str = ''


class RoutineService:
    def __init__(self, orchestrator, runtime):
        self.orchestrator,self.runtime=orchestrator,runtime
        self.lock=threading.Lock()

    def entries(self):
        rows=self.runtime.section().get('routines',[])
        if not isinstance(rows,list):raise ValueError('Lista de rotinas inválida.')
        entries=[RoutineSpec.parse(row) for row in rows]
        if len({r.id for r in entries})!=len(entries):raise ValueError('Rotinas duplicadas.')
        return entries

    def configure(self,operation,hour,minute,sources=(),weekday=None):
        sources=tuple(sources)
        if operation=='review_notes':
            self.orchestrator._sync_knowledge_access()
            reader=self.orchestrator.second_brain
            reader._check_access()
            sources=tuple(reader.resolve_and_validate(s) for s in sources)
            # Confere também limites e origem antes de persistir a seleção.
            KnowledgeReview().prepare('review',sources,reader,uuid.uuid4().hex)
        existing=next((r for r in self.entries() if r.operation==operation),None)
        spec=RoutineSpec(existing.id if existing else uuid.uuid4().hex,operation,
            hour,minute,weekday,sources,False)
        RoutineSpec.parse(spec.as_dict())
        def update(section):
            rows=section.setdefault('routines',[])
            rows[:]=[r for r in rows if r['id']!=spec.id]+[spec.as_dict()]
        if existing:self.runtime.revoke(operation,existing.id)
        self.runtime._update(update)
        return spec

    def enable(self,spec,enabled):
        if spec not in self.entries():raise ValueError('A rotina mudou.')
        def update(section):
            for row in section.get('routines',[]):
                if row['id']==spec.id:row['enabled']=bool(enabled)
        self.runtime._update(update)

    def version(self,spec):
        config=self.runtime.loader()
        scope=spec.as_dict();scope.pop('enabled')
        scope.update(calendar=config.get('calendar',{}),
            knowledge=config.get('knowledge_access',{}),vault=self.orchestrator.second_brain.vault_root)
        from therion.calendar.google_adapter import GoogleCalendarAdapter
        if isinstance(self.orchestrator.calendar_adapter,GoogleCalendarAdapter):
            from therion.integrations.calendar import account_key
            scope['calendar_account']=account_key(self.orchestrator)
        return implementation_version(self.runtime,scope)

    def _reader(self,spec):
        self.orchestrator._sync_knowledge_access()
        original=self.orchestrator.second_brain
        original._check_access()
        def guard():
            original._check_access()
            for path in spec.sources:original.resolve_and_validate(path)
        guard()
        selected=SecondBrainReader(original.vault_root,list(spec.sources))
        selected.access_guard=guard
        return selected

    def run(self,spec,*,supervised=False,simulation=False,cancelled=None):
        attempt=None
        if not self.lock.acquire(False):return RoutineResult('busy','Outra rotina está em andamento.')
        if not self.orchestrator._operation_lock.acquire(False):
            self.lock.release()
            return RoutineResult('busy','A conversa tem prioridade; a rotina aguarda.')
        try:
            if cancelled is not None and cancelled.is_set():return RoutineResult('cancelled','Rotina cancelada antes da leitura.')
            if spec not in self.entries():raise ValueError('Rotina alterada ou removida.')
            version=self.version(spec)
            permitted=(self.orchestrator.calendar_adapter is not None if spec.operation=='daily_summary'
                else bool(self._reader(spec)))
            decision=self.runtime.decide(spec.operation,spec.id,version,permitted=permitted)
            if decision.mode=='blocked':return RoutineResult('blocked',decision.reason)
            if not supervised and (not spec.enabled or decision.mode!='autonomous'):
                return RoutineResult('blocked','A rotina não tem autonomia vigente.')
            if supervised:
                from .policy import AutonomyDecision
                decision=AutonomyDecision('confirmation','Teste supervisionado solicitado pelo painel.')
            attempt=self.runtime.begin(spec.operation,spec.id,version,decision,permitted=permitted,simulation=simulation)
            def guard():
                if cancelled is not None and cancelled.is_set():raise ValueError('Rotina cancelada durante a consulta.')
                if spec not in self.entries() or self.version(spec)!=version:
                    raise ValueError('A configuração da rotina mudou durante a execução.')
                if not supervised and self.runtime.decide(spec.operation,spec.id,version,permitted=True)!=decision:
                    raise ValueError('A autorização da rotina mudou durante a execução.')
            guard()
            if simulation:
                self.runtime.store.finish(attempt,'success',False)
                return RoutineResult('simulation','Simulei a rotina; nenhuma fonte foi consultada.',attempt)
            if spec.operation=='daily_summary':
                result=PlanDaySkill(self.orchestrator.calendar_adapter).execute(now=self.runtime.clock())
                status='success' if result.status=='success' else 'partial'
                message=result.message
            else:
                reader=self._reader(spec)
                reviewer=KnowledgeReview()
                session=uuid.uuid4().hex
                message=reviewer.prepare('review',spec.sources,reader,session)
                reviewer.valid(reader,session)
                # Este resultado é um relatório da rotina, não uma proposta
                # conversacional recuperável na sessão do usuário.
                message=message.split('\n\nSomente proposta;')[0]+(
                    '\n\nRelatório de revisão; nenhuma fonte foi alterada. '
                    'Para preparar uma consolidação, selecione as notas novamente na conversa.')
                status='success'
            guard()
            self.runtime.store.finish(attempt,status,status=='success')
            return RoutineResult(status,message,attempt)
        except Exception:
            if attempt:
                try:self.runtime.store.finish(attempt,'failed')
                except Exception:pass
            return RoutineResult('failed','Não concluí a rotina com segurança. Revise fontes, políticas e evidências.',attempt or '')
        finally:
            self.orchestrator._operation_lock.release()
            self.lock.release()


class RoutineScheduler:
    """Chamado pelo host somente quando livre e desbloqueado; nunca inicia processos."""
    def __init__(self,service,unlocked):
        self.service,self.unlocked=service,unlocked

    def next_due(self):
        runtime=self.service.runtime
        if not self.unlocked() or runtime.store.state('paused')=='1':return None
        now=runtime.clock()
        for spec in self.service.entries():
            if not spec.enabled:continue
            version=self.service.version(spec)
            decision=runtime.decide(spec.operation,spec.id,version,permitted=True)
            if decision.mode!='autonomous':continue
            occurrence=spec.latest(now)
            identifier=spec.id+':'+occurrence.isoformat()
            if runtime.store.claim_occurrence(identifier):
                if now-occurrence>timedelta(hours=2):
                    runtime.store.finish_occurrence(identifier,'missed')
                    continue
                return identifier,spec
        return None

    def run(self,identifier,spec):
        if not self.unlocked():
            self.service.runtime.store.finish_occurrence(identifier,'blocked')
            return RoutineResult('blocked','Sessão bloqueada; não consultei fontes.')
        result=self.service.run(spec)
        if result.status=='busy':
            self.service.runtime.store.release_unstarted_occurrence(identifier)
            return result
        self.service.runtime.store.finish_occurrence(identifier,result.status)
        return result
