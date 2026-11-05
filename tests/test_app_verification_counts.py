"""Contagem automática exige abertura real e processo do executável cadastrado."""
from unittest.mock import patch
import pytest

from tests import test_autonomy_v4 as fixtures
from tests import test_autonomy_panel_v4 as panel_fixtures
from therion.autonomy.apps import ApplicationCatalog, CatalogLauncher
from therion.autonomy.integration import implementation_version
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def system():
    fixture=fixtures.AutonomyTests();fixture.setUp()
    catalog=ApplicationCatalog(fixture.runtime)
    apps=[]
    for name in ('Chrome','Steam'):
        path=fixture.root/(name+'.exe');path.write_bytes(b'fixture - never execute')
        apps.append(catalog.register(name,str(path)))
    orch=Orchestrator(simulate=False,log_dir=str(fixture.root/'logs'),autonomy_runtime=fixture.runtime)
    yield fixture,apps,orch
    orch.close();fixture.tearDown()


@pytest.mark.parametrize('delay', [0,2.5,9.75])
def test_success_is_verified_automatically_after_process_appears(system,delay):
    fixture,apps,orch=system
    clock=[0.0];launched=[]
    def paths():return {apps[0].path} if launched and clock[0]>=delay else set()
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,paths,launched.append)
    result=orch.process_command('abra Chrome')
    with patch('therion.autonomy.integration.time.monotonic',side_effect=lambda:clock[0]), \
         patch('therion.autonomy.integration.time.sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
        result=orch.confirm_and_execute(result.plan,True)
    assert result.status=='success' and launched==[apps[0].path]
    assert fixture.store.verified_openings(apps[0].id)==1
    assert fixture.store.verified_openings(apps[1].id)==0
    assert fixture.store.recent()[0].verified
    version=implementation_version(fixture.runtime,apps[0].as_dict())
    assert fixture.store.progress('open_app',apps[0].id,version)['count']==1


@pytest.mark.parametrize('failure', ['missing_process','wrong_executable','launch_error'])
def test_failed_or_unconfirmed_opening_does_not_count(system,failure):
    fixture,apps,orch=system;clock=[0.0];launched=[]
    def launch(path):
        if failure=='launch_error':raise OSError('não abriu')
        launched.append(path)
    paths=lambda:{apps[1].path} if failure=='wrong_executable' else set()
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,paths,launch)
    result=orch.process_command('abra Chrome')
    with patch('therion.autonomy.integration.time.monotonic',side_effect=lambda:clock[0]), \
         patch('therion.autonomy.integration.time.sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
        result=orch.confirm_and_execute(result.plan,True)
    assert result.status in {'execution_failed','verification_failed'}
    assert fixture.store.verified_openings(apps[0].id)==0
    assert not fixture.store.recent()[0].verified
    assert len(launched)<=1


def test_existing_process_and_repeated_requests_do_not_inflate_counter(system):
    fixture,apps,orch=system;launched=[]
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,lambda:{apps[0].path},launched.append)
    for _ in range(3):
        result=orch.process_command('abra Chrome')
        result=orch.confirm_and_execute(result.plan,True)
        assert 'Não contei uma nova abertura' in result.message
    assert not launched and not fixture.store.recent()
    assert fixture.store.verified_openings(apps[0].id)==0


def test_simulation_cannot_count_even_if_program_is_running(system):
    fixture,apps,orch=system;launched=[]
    fixture.runtime._update(lambda section:section.update(app_opening_mode='simulation'))
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,lambda:{apps[0].path},launched.append)
    result=orch.process_command('abra Chrome')
    assert orch.confirm_and_execute(result.plan,True).status=='executed_simulated'
    assert fixture.store.verified_openings(apps[0].id)==0 and not launched


def test_history_survives_version_change_but_does_not_grant_new_version(system):
    fixture,apps,_=system
    attempt=fixture.store.begin('open_app',apps[0].id,'old-version','supervised')
    fixture.store.finish(attempt,'success',True)
    failed=fixture.store.begin('open_app',apps[0].id,'new-version','supervised')
    fixture.store.finish(failed,'failed')
    assert fixture.store.verified_openings(apps[0].id)==1
    assert fixture.store.progress('open_app',apps[0].id,'new-version')['count']==0
    with pytest.raises(ValueError):fixture.runtime.grant('open_app',apps[0].id,'new-version','fixture')


def test_existing_process_race_does_not_count_or_erase_supervised_progress(system):
    fixture,apps,orch=system
    version=implementation_version(fixture.runtime,apps[0].as_dict())
    prior=fixture.store.begin('open_app',apps[0].id,version,'supervised')
    fixture.store.finish(prior,'success',True)
    queries=[False,True];launched=[]
    def paths():return {apps[0].path} if queries.pop(0) else set()
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,paths,launched.append)
    proposal=orch.process_command('abra Chrome')
    assert orch.confirm_and_execute(proposal.plan,True).status=='success'
    assert not launched and fixture.store.verified_openings(apps[0].id)==1
    assert fixture.store.progress('open_app',apps[0].id,version)['count']==1


def test_panel_shows_count_and_refreshes_after_verified_opening(system):
    fixture,apps,orch=system
    panel_fixtures.PanelTests.setUpClass();fixture.app=panel_fixtures.PanelTests.app
    fixture.window=panel_fixtures.PanelTests.window.__get__(fixture)
    fixture.wait=panel_fixtures.PanelTests.wait.__get__(fixture)
    window=fixture.window();window._orchestrator.close();window._orchestrator=orch
    window._show_autonomy();fixture.wait(window);panel=window._autonomy_panel
    paths=set()
    orch.catalog_launcher=CatalogLauncher(orch.application_catalog,lambda:paths,paths.add)
    assert '0 aberturas verificadas' in panel.app_cards[apps[0].id].subtitle.text()
    with patch.object(panel,'confirm',return_value=True):
        panel.open_app(apps[0].id);fixture.wait(window)
    assert '1 abertura verificada' in panel.app_cards[apps[0].id].subtitle.text()
    assert '0 aberturas verificadas' in panel.app_cards[apps[1].id].subtitle.text()
    assert not panel.app_cards[apps[0].id].check.isChecked()
    panel.close();fixture.doCleanups()
