"""Contratos V4 com estado, relógio e aplicativos fictícios; zero efeitos pessoais."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
import uuid
import shutil

from therion.autonomy.policy import AutonomyPolicy
from therion.autonomy.runtime import AutonomyRuntime
from therion.autonomy.store import EvidenceStore
from therion.autonomy.apps import ApplicationCatalog,CatalogLauncher
from therion.autonomy.integration import implementation_version
from therion.core.orchestrator import Orchestrator


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        # Python 3.14 cria mkdtemp com ACL 0700 que exclui a identidade do
        # sandbox Windows. Pasta de fixture herda a ACL do workspace.
        base=Path(__file__).resolve().parents[1]/'tmp'/'v4-tests'
        self.root=base/uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.now=datetime(2026,10,1,tzinfo=timezone.utc)
        self.config={}
        self.store=EvidenceStore(self.root/'state.sqlite3',lambda:self.now)
        self.runtime=AutonomyRuntime(self.store,lambda:deepcopy(self.config),self.write,lambda:self.now)

    def tearDown(self):
        base=Path(__file__).resolve().parents[1]/'tmp'/'v4-tests'
        if self.root.resolve().parent != base.resolve():
            raise ValueError('Fixture fora da raiz de testes.')
        shutil.rmtree(self.root)

    def write(self,value):
        self.config=deepcopy(value)

    def seed(self,operation='open_app',target='app',version='v',mode='supervised'):
        for i in range(10):
            self.now=datetime(2026,10,1,tzinfo=timezone.utc)+timedelta(days=i)
            attempt=self.store.begin(operation,target,version,mode)
            self.store.finish(attempt,'success',True)

    def test_no_default_grant(self):
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=True).mode,'confirmation')
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=False).mode,'blocked')
        self.assertFalse(self.store.ready('open_app','app','v'))
        self.runtime.grant('open_app','app','v','visual')
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=True).mode,'autonomous')
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=False).mode,'blocked')

    def test_other_pilots_still_require_observation(self):
        for operation in ('daily_summary','review_notes','remember_procedure'):
            with self.subTest(operation=operation),self.assertRaises(ValueError):
                self.runtime.grant(operation,'target','v','visual')
        self.assertEqual(self.runtime.policies(),[])

    def test_manual_app_grant_can_be_reselected_after_version_change_without_waiting(self):
        self.runtime.grant('open_app','app','old','visual')
        self.assertEqual(self.runtime.decide('open_app','app','new',permitted=True).mode,'confirmation')
        self.runtime.grant('open_app','app','new','nova revisão visual')
        self.assertEqual(self.runtime.decide('open_app','app','new',permitted=True).mode,'autonomous')
        self.assertEqual(self.store.recent(),[])

    def test_evidence_and_seven_day_expiry(self):
        policy=self.runtime.grant('open_app','app','v','visual')
        self.assertEqual(policy.expires_at-self.now,timedelta(days=7))
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=True).mode,'autonomous')
        self.now+=timedelta(days=7)
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=True).mode,'confirmation')

    def test_simulation_never_counts(self):
        self.seed(mode='simulation')
        self.assertFalse(self.store.ready('open_app','app','v'))

    def test_incident_resets_observation_and_requires_review(self):
        self.seed()
        attempt=self.store.begin('open_app','app','v','supervised')
        self.store.finish(attempt,'uncertain')
        self.assertFalse(self.store.ready('open_app','app','v'))
        with self.assertRaises(ValueError):self.runtime.grant('open_app','app','v','visual')

    def test_revocation_pause_and_scope_changes(self):
        self.seed();self.runtime.grant('open_app','app','v','visual')
        decision=self.runtime.decide('open_app','app','v',permitted=True)
        self.runtime.pause()
        with self.assertRaises(ValueError):self.runtime.begin('open_app','app','v',decision,permitted=True)
        self.runtime.pause(False)
        self.assertEqual(self.runtime.decide('open_app','other','v',permitted=True).mode,'confirmation')
        self.assertEqual(self.runtime.decide('open_app','app','changed',permitted=True).mode,'confirmation')
        self.runtime.revoke('open_app','app')
        with self.assertRaises(ValueError):self.runtime.begin('open_app','app','v',decision,permitted=True)

    def test_limits_and_unknown_running_operation(self):
        self.seed();self.runtime.grant('open_app','app','v','visual',per_day=1)
        decision=self.runtime.decide('open_app','app','v',permitted=True)
        attempt=self.runtime.begin('open_app','app','v',decision,permitted=True)
        with self.assertRaises(ValueError):self.runtime.begin('open_app','app','v',decision,permitted=True)
        self.store.finish(attempt,'success',True)
        with self.assertRaises(ValueError):self.runtime.begin('open_app','app','v',decision,permitted=True)

    def test_occurrence_claim_is_persistent(self):
        self.assertTrue(self.store.claim_occurrence('routine:time'))
        other=EvidenceStore(self.root/'state.sqlite3')
        self.assertFalse(other.claim_occurrence('routine:time'))

    def test_invalid_and_duplicate_policies_fail_closed(self):
        self.seed();policy=self.runtime.grant('open_app','app','v','visual')
        self.config['autonomy']['policies'].append(policy.as_dict())
        self.assertEqual(self.runtime.decide('open_app','app','v',permitted=True).mode,'confirmation')
        row=policy.as_dict();row['expires_at']=(self.now+timedelta(days=8)).isoformat()
        with self.assertRaises(ValueError):AutonomyPolicy.parse(row)

    def app(self,name='Editor'):
        path=self.root/(name+'.exe');path.write_bytes(b'ficticio')
        return ApplicationCatalog(self.runtime).register(name,str(path),('editar',))

    def test_catalog_alias_and_executable_change(self):
        app=self.app();catalog=ApplicationCatalog(self.runtime)
        self.assertEqual(catalog.resolve('EDITAR'),[app])
        self.assertTrue(catalog.valid(app))
        Path(app.path).write_bytes(b'alterado')
        self.assertFalse(catalog.valid(app))
        called=[]
        with self.assertRaises(ValueError):CatalogLauncher(catalog,lambda:set(),called.append).open(app,lambda:None)
        self.assertFalse(called)

    def test_launcher_does_not_duplicate_running_process(self):
        app=self.app();called=[]
        launcher=CatalogLauncher(ApplicationCatalog(self.runtime),lambda:{app.path},called.append)
        self.assertFalse(launcher.open(app,lambda:None));self.assertFalse(called)

    def test_terminal_and_relative_path_not_accepted(self):
        catalog=ApplicationCatalog(self.runtime)
        for path in ('cmd.exe',str(self.root/'powershell.exe')):
            with self.assertRaises(ValueError):catalog.register('Terminal',path)

    def test_catalog_manual_confirmation_and_simulation(self):
        app=self.app()
        orch=Orchestrator(simulate=True,log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        result=orch.process_command('abra Editor')
        self.assertEqual(result.status,'awaiting_confirmation',result.message)
        result=orch.confirm_and_execute(result.plan,True)
        self.assertEqual(result.status,'executed_simulated',result.message)
        self.assertEqual(self.store.recent()[0].mode,'simulation')
        self.assertFalse(self.store.ready('open_app',app.id,implementation_version(self.runtime,app.as_dict())))

    def test_ambiguous_name_never_launches(self):
        self.app('Editor');app=self.app('Outro')
        catalog=ApplicationCatalog(self.runtime)
        catalog.register('Editor',app.path)
        orch=Orchestrator(simulate=True,log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        result=orch.process_command('abra Editor')
        self.assertEqual(result.status,'unknown_intent',result.message)
        self.assertEqual(self.store.recent(),[])

    def test_permission_manager_can_block_registered_application(self):
        self.app()
        orch=Orchestrator(simulate=True,log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        orch.permission_manager.is_allowed=lambda intent:False
        result=orch.process_command('abra Editor')
        self.assertEqual(result.status,'forbidden')
        self.assertEqual(self.store.recent(),[])

    def test_granted_app_uses_policy_and_does_not_duplicate_conversation(self):
        app=self.app();version=implementation_version(self.runtime,app.as_dict())
        self.seed('open_app',app.id,version);self.runtime.grant('open_app',app.id,version,'visual')
        orch=Orchestrator(log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        # Backend fictício verifica estado sem criar processo real.
        paths=set();launched=[]
        def launch(path):launched.append(path);paths.add(path)
        orch.catalog_launcher=CatalogLauncher(orch.application_catalog,lambda:paths,launch)
        result=orch.process_command('abra Editor')
        self.assertEqual(result.status,'success',result.message)
        self.assertEqual(launched,[app.path])
        self.assertEqual(self.store.recent()[0].mode,'autonomous')
        replies=[turn for turn in orch.memory.turns if turn.role=='therion']
        self.assertEqual(len(replies),1)
        self.assertTrue(orch.memory.history[-1].confirmation_status.startswith('dispensada_por_politica:'))

    def test_revoke_during_process_query_prevents_launch(self):
        app=self.app();version=implementation_version(self.runtime,app.as_dict())
        self.seed('open_app',app.id,version);self.runtime.grant('open_app',app.id,version,'visual')
        orch=Orchestrator(log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        launched=[]
        def paths():self.runtime.revoke('open_app',app.id);return set()
        orch.catalog_launcher=CatalogLauncher(orch.application_catalog,paths,launched.append)
        result=orch.process_command('abra Editor')
        self.assertEqual(result.status,'execution_failed',result.message)
        self.assertEqual(launched,[])

    def test_audit_failure_prevents_launch(self):
        app=self.app();orch=Orchestrator(log_dir=str(self.root/'logs'),autonomy_runtime=self.runtime)
        launched=[]
        orch.catalog_launcher=CatalogLauncher(orch.application_catalog,lambda:set(),launched.append)
        result=orch.process_command('abra Editor')
        self.store.begin=lambda *args,**kwargs:(_ for _ in ()).throw(OSError('Disk full'))
        result=orch.confirm_and_execute(result.plan,True)
        self.assertEqual(result.status,'execution_failed');self.assertEqual(launched,[])


if __name__=='__main__':unittest.main()
