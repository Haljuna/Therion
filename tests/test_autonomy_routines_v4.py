"""Pilotos de rotina/memória em cofre fictício e integrações injetadas."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_autonomy_v4 as fixtures
from therion.autonomy.routines import RoutineService,RoutineSpec,RoutineScheduler
from therion.autonomy.procedures import ProcedureMemory
from therion.autonomy.windows import SingleInstance,StartupShortcut
from therion.core.orchestrator import Orchestrator
from therion.memory.knowledge import MemoryPolicy,MemoryCandidate,SourceReference,digest
from therion.memory.repository import MarkdownMemoryRepository
from therion.memory.supervised import MemoryEvidenceStore


class RoutineTests(unittest.TestCase):
    setUp=fixtures.AutonomyTests.setUp
    tearDown=fixtures.AutonomyTests.tearDown
    write=fixtures.AutonomyTests.write
    seed=fixtures.AutonomyTests.seed

    def orch(self,calendar=None,policy=None,repository=None,evidence=None):
        self.vault=self.root/'vault';self.vault.mkdir(exist_ok=True)
        orch=Orchestrator(vault_root=str(self.vault),log_dir=str(self.root/'logs'),
            calendar_adapter=calendar,autonomy_runtime=self.runtime,memory_policy=policy,
            memory_repository=repository,memory_evidence_store=evidence)
        orch.knowledge.clock=lambda:self.now
        return orch

    def calendar(self):
        class Calendar:
            def list_events_for_day(self,day):return []
        return Calendar()

    def test_summary_supervised_and_unavailable(self):
        orch=self.orch(self.calendar());service=RoutineService(orch,self.runtime)
        spec=service.configure('daily_summary',8,0)
        result=service.run(spec,supervised=True)
        self.assertEqual(result.status,'success',result.message)
        self.assertEqual(self.store.recent()[0].mode,'supervised')
        self.assertEqual(service.run(spec).status,'blocked')
        orch.calendar_adapter=None
        self.assertEqual(service.run(spec,supervised=True).status,'blocked')

    def test_summary_partial_not_success(self):
        from therion.calendar.adapter import CalendarError
        calendar=self.calendar()
        calendar.list_events_for_day=lambda day:(_ for _ in ()).throw(CalendarError('offline'))
        service=RoutineService(self.orch(calendar),self.runtime)
        spec=service.configure('daily_summary',8,0)
        self.assertEqual(service.run(spec,supervised=True).status,'partial')
        self.assertFalse(self.store.recent()[0].verified)

    def test_review_selected_notes_only(self):
        orch=self.orch();folder=self.vault/'10 - Projetos'/'Therion';folder.mkdir(parents=True)
        note=folder/'A.md';note.write_text('Procedimento de teste.\n',encoding='utf-8')
        outside=self.vault/'pessoal.md';outside.write_text('Área não autorizada.',encoding='utf-8')
        service=RoutineService(orch,self.runtime)
        with self.assertRaises(PermissionError):service.configure('review_notes',18,0,[str(outside)],6)
        spec=service.configure('review_notes',18,0,[str(note)],6)
        before=note.read_bytes();result=service.run(spec,supervised=True)
        self.assertEqual(result.status,'success',result.message)
        self.assertEqual(note.read_bytes(),before)
        self.assertIn('Relatório de revisão',result.message)
        orch.second_brain.allowed_roots=[]
        self.assertEqual(service.run(spec,supervised=True).status,'failed')

    def test_scheduler_claims_once_and_locked_session_does_not_read(self):
        service=RoutineService(self.orch(self.calendar()),self.runtime)
        spec=service.configure('daily_summary',8,0)
        version=service.version(spec);self.seed('daily_summary',spec.id,version)
        self.runtime.grant('daily_summary',spec.id,version,'visual')
        service.enable(spec,True);spec=service.entries()[0]
        self.now=self.now.replace(hour=11,minute=30)  # 08:30 em São Paulo
        scheduler=RoutineScheduler(service,lambda:False)
        self.assertIsNone(scheduler.next_due())
        scheduler.unlocked=lambda:True
        due=scheduler.next_due();self.assertIsNotNone(due)
        self.assertIsNone(scheduler.next_due())
        result=scheduler.run(*due);self.assertEqual(result.status,'success',result.message)
        self.assertEqual(self.store.recent()[0].mode,'autonomous')

    def test_expired_occurrence_is_missed(self):
        service=RoutineService(self.orch(self.calendar()),self.runtime)
        spec=service.configure('daily_summary',8,0);version=service.version(spec)
        self.seed('daily_summary',spec.id,version);self.runtime.grant('daily_summary',spec.id,version,'visual')
        service.enable(spec,True);self.now=self.now.replace(hour=16)
        scheduler=RoutineScheduler(service,lambda:True)
        self.assertIsNone(scheduler.next_due())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT state FROM occurrences').fetchone()[0],'missed')

    def test_revocation_between_claim_and_run(self):
        service=RoutineService(self.orch(self.calendar()),self.runtime)
        spec=service.configure('daily_summary',8,0);version=service.version(spec)
        self.seed('daily_summary',spec.id,version);self.runtime.grant('daily_summary',spec.id,version,'visual')
        service.enable(spec,True);self.now=self.now.replace(hour=11,minute=30)
        scheduler=RoutineScheduler(service,lambda:True);due=scheduler.next_due()
        self.runtime.revoke('daily_summary',spec.id)
        self.assertEqual(scheduler.run(*due).status,'blocked')

    def test_schedule_validation_and_weekly_latest(self):
        row=dict(id='review',operation='review_notes',hour=18,minute=0,weekday=6,
            sources=['a.md'],enabled=False,timezone='America/Sao_Paulo')
        spec=RoutineSpec.parse(row)
        self.assertEqual(spec.latest(datetime(2026,10,14,12,tzinfo=timezone.utc)).weekday(),6)
        for changes in ({'hour':24},{'sources':[]},{'weekday':True},{'sources':['a.md']*6}):
            with self.assertRaises(ValueError):RoutineSpec.parse(dict(row,**changes))

    def memory(self):
        vault=self.root/'vault';root=vault/'90 - Sistema da IA'/'Notas de Rascunho da IA'/'Registros'
        root.mkdir(parents=True,exist_ok=True)
        policy=MemoryPolicy(mode='authorized',read_roots=(str(vault),),write_root=str(root),
            authorization='Fixture supervisionada',expires_at=self.now+timedelta(days=7),revision=1)
        repository=MarkdownMemoryRepository(root,lambda:policy)
        evidence=MemoryEvidenceStore(self.root/'memory-evidence')
        orch=self.orch(policy=policy,repository=repository,evidence=evidence)
        service=ProcedureMemory(orch,self.runtime);service.configure(str(root))
        return service,root

    def test_memory_requires_two_distinct_verified_operations(self):
        memory,root=self.memory()
        for mode in ('simulation','supervised'):
            attempt=self.store.begin('review_notes','routine','v',mode);self.store.finish(attempt,'success',True)
        self.assertEqual(memory.candidates(),[])
        attempt=self.store.begin('review_notes','routine','v','supervised');self.store.finish(attempt,'success',True)
        self.assertEqual(len(memory.candidates()),1)
        self.assertEqual(list(root.glob('*.md')),[])

    def test_memory_supervised_idempotent_and_recoverable(self):
        memory,root=self.memory()
        for _ in range(2):
            attempt=self.store.begin('review_notes','routine','v','supervised');self.store.finish(attempt,'success',True)
        candidate=memory.candidates()[0]
        with self.assertRaises(ValueError):memory.save(candidate)
        memory.save(candidate,supervised=True)
        memory.save(candidate,supervised=True)
        self.assertEqual(len(list(root.glob('*.md'))),1)
        stored=memory.orchestrator._supervised_memory.retrieve('revisar conhecimento',memory.orchestrator.knowledge.policy.read_roots)
        self.assertEqual(len(stored),1)
        with self.assertRaises(ValueError):memory.save(replace(candidate,summary='conteúdo inventado'),supervised=True)

    def test_memory_does_not_accept_user_declaration_or_another_destination(self):
        memory,root=self.memory()
        with self.assertRaises(ValueError):memory.configure(str(root.parent))
        source=SourceReference.user('Prefiro café','session')
        self.assertFalse(memory.valid_source(source))

    def test_memory_revocation_at_publish_guard(self):
        memory,root=self.memory()
        for _ in range(2):
            attempt=self.store.begin('review_notes','routine','v','supervised');self.store.finish(attempt,'success',True)
        candidate=memory.candidates()[0]
        original=memory.orchestrator._knowledge_repository.store
        def revoked(*args,**kwargs):
            memory.orchestrator.knowledge.policy=replace(memory.orchestrator.knowledge.policy,mode='off')
            return original(*args,**kwargs)
        with patch.object(memory.orchestrator._knowledge_repository,'store',revoked):
            with self.assertRaises(ValueError):memory.save(candidate,supervised=True)
        self.assertEqual(list(root.glob('*.md')),[])

    def test_single_instance_mutex_is_per_name(self):
        import os,uuid
        if os.name!='nt':self.skipTest('Windows')
        name='test-'+uuid.uuid4().hex
        one=SingleInstance(name);two=SingleInstance(name)
        try:self.assertTrue(one.acquired);self.assertFalse(two.acquired)
        finally:one.close();two.close()

    def test_managed_startup_shortcut_in_isolated_folder(self):
        import os
        if os.name!='nt':self.skipTest('Windows')
        startup=self.root/'startup-fixture';startup.mkdir()
        shortcut=StartupShortcut(startup=startup)
        shortcut.set_enabled(True)
        self.assertTrue(shortcut.path.is_file())
        shortcut.set_enabled(False)
        self.assertFalse(shortcut.path.exists())


if __name__=='__main__':unittest.main()
