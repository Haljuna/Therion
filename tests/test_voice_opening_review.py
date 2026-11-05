"""Abertura transcrita exige plano real, alvo exato e confirmação consumível."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from tests import test_autonomy_v4 as autonomy_fixtures
from tests.test_voice_conversation import window, activate
from therion.autonomy.apps import ApplicationCatalog, CatalogLauncher
from therion.autonomy.integration import implementation_version
from therion.core.ai_provider import AIResponse
from therion.core.orchestrator import Orchestrator
from therion.governance.confirmation import ConfirmationHandler


@pytest.fixture
def opening():
    fixture = autonomy_fixtures.AutonomyTests(); fixture.setUp()
    path = fixture.root/'chrome.exe'; path.write_bytes(b'fixture - never execute')
    app = ApplicationCatalog(fixture.runtime).register('Google Chrome', str(path), ('chrome',))
    ai = MagicMock()
    ai.classify_detailed.return_value = SimpleNamespace(failure=None,
        response=AIResponse(type='chat', message='Entendi! Posso abrir o Google Chrome para você. Confirma?'))
    orch = Orchestrator(simulate=False, log_dir=str(fixture.root/'logs'),
        autonomy_runtime=fixture.runtime, ai_core=ai)
    orch.voice_conversation = True
    paths, launches = set(), []
    def launch(path): launches.append(path); paths.add(path)
    orch.catalog_launcher = CatalogLauncher(orch.application_catalog, lambda: paths, launch)
    yield fixture, app, orch, launches
    orch.close(); fixture.tearDown()


@pytest.mark.parametrize('answer,value', [
    ('Sim, sim', True), ('sim sim.', True), ('sim, sim, sim!', True),
    ('não, não.', False), ('cancela, cancela', False),
    ('sim, não', None), ('sim, mas não abra', None), ('sim, abra outro', None),
])
def test_repetition_is_accepted_only_when_homogeneous(answer, value):
    assert ConfirmationHandler().evaluate_response(answer) is value


@pytest.mark.parametrize('command', ['abriu google chrome', 'abro o Google Chrome.',
    'abri o Google Chrome', 'Abra e google chrome', 'Therion, abre e Google Chrome!'])
def test_uncertain_voice_always_reviews_even_with_autonomous_policy(opening, command):
    fixture, app, orch, launches = opening
    version = implementation_version(fixture.runtime, app.as_dict())
    fixture.seed('open_app', app.id, version)
    fixture.runtime.grant('open_app', app.id, version, 'Fixture visual')
    result = orch.process_command(command)
    assert result.status == 'awaiting_confirmation', result.message
    assert result.plan is not None and result.confirmation_id
    assert result.intent.target == app.id and result.intent.raw_command == command
    assert not launches
    token = result.confirmation_id
    confirmed = ConfirmationHandler().evaluate_response('Sim, sim')
    assert orch.confirm_session_proposal(result.plan, confirmed, orch.session_id, token).status == 'success'
    assert launches == [app.path]
    assert fixture.store.recent()[0].mode == 'supervised'
    assert orch.confirm_session_proposal(result.plan, True, orch.session_id, token).status == 'cancelled'
    assert launches == [app.path]
    orch.ai_core.classify_detailed.assert_not_called()


def test_uncertain_opening_can_be_cancelled(opening):
    _, _, orch, launches = opening
    result = orch.process_command('abriu Google Chrome')
    assert orch.confirm_and_execute(result.plan, False).status == 'cancelled'
    assert not launches


@pytest.mark.parametrize('command', ['não abriu Google Chrome', 'talvez abri Google Chrome',
    'abriu cromi', 'abriu Google Chrome e Calculadora', 'abriu Google Chrome se der'])
def test_negative_unknown_and_compound_never_create_opening(opening, command):
    _, _, orch, launches = opening
    result = orch.process_command(command)
    assert result.plan is None
    assert not launches


def test_chat_offer_cannot_create_fake_confirmation_or_execute_on_yes(opening):
    _, _, orch, launches = opening
    result = orch.process_command('quero usar o navegador')
    assert result.status == 'clarification' and result.plan is None
    assert 'Ainda não preparei' in result.message
    assert 'Confirma?' not in result.message
    assert orch.process_command('Sim, sim').status == 'cancelled'
    assert not launches
    assert orch.ai_core.classify_detailed.call_count == 1


def test_literal_registered_name_starting_with_e_is_not_changed(opening):
    fixture, _, orch, _ = opening
    path = fixture.root/'other.exe'; path.write_bytes(b'fixture - never execute')
    app = ApplicationCatalog(fixture.runtime).register('e Google Chrome', str(path))
    result = orch.process_command('Abra e Google Chrome')
    assert result.intent.target == app.id


def test_review_is_limited_to_voice_mode(opening):
    _, _, orch, launches = opening
    orch.voice_conversation = False
    assert orch.process_command('abriu Google Chrome').plan is None
    assert not launches


def test_navigador_voice_typo_uses_only_registered_browser_alias(opening):
    fixture,app,orch,launches=opening
    fixture.runtime._update(lambda section:section['applications'][0].update(aliases=['chrome','navegador']))
    result=orch.process_command('Abre navigador.')
    assert result.status=='awaiting_confirmation',result.message
    assert result.intent.target==app.id and result.plan is not None
    assert not launches


@pytest.mark.parametrize('name',['Etério','Eterio','Etérion','Eterion','Thérion','Tério'])
def test_vocative_family_uses_registered_browser_route_without_model(opening,name):
    fixture,app,orch,launches=opening
    fixture.runtime._update(lambda section:section['applications'][0].update(aliases=['chrome','navegador']))
    result=orch.process_command(name+' abre o navegador.')
    assert result.status=='awaiting_confirmation',result.message
    assert result.intent.target==app.id and result.plan is not None
    orch.ai_core.classify_detailed.assert_not_called()
    assert not launches


@pytest.mark.parametrize('answer',['See','Point','But'])
def test_mistranscribed_confirmation_never_authorizes(answer):
    assert ConfirmationHandler().evaluate_response(answer) is None


@pytest.mark.parametrize('command',[
    'Abre uma janela do navegador.', 'Abre mais uma janela do Chrome.',
    'Abre uma nova janela no navegador.', 'Abre uma janela no navegador.',
    'Abre mais uma janela do tronco.', 'Abre mais uma janela do crônico.',
])
def test_new_browser_window_has_specific_confirmation_and_verifies_window(opening,command):
    fixture,app,orch,launches=opening
    fixture.runtime._update(lambda section:section['applications'][0].update(aliases=['chrome','navegador']))
    windows={101};calls=[]
    orch.catalog_launcher.windows=lambda path:set(windows)
    def new_window(path):calls.append(path);windows.add(102)
    orch.catalog_launcher.launch_window=new_window
    version=implementation_version(fixture.runtime,orch.application_catalog.entries()[0].as_dict())
    fixture.runtime.grant('open_app',app.id,version,'Fixture visual')
    result=orch.process_command(command)
    if 'tronco' in command or 'crônico' in command:
        assert result.status=='awaiting_confirmation',result.message
        assert result.plan.intent.entities['new_window'] is True and calls==[]
        final=orch.confirm_session_proposal(result.plan,True,orch.session_id,result.confirmation_id)
    else:
        assert result.status=='success',result.message
        assert orch.confirmation_id is None
        final=result
    assert final.status=='success',final.message
    assert 'nova janela' in final.message and calls==[app.path]
    assert not launches
    assert fixture.store.recent()[0].verified


def test_unverified_new_window_is_uncertain_and_never_retried(opening):
    fixture,app,orch,launches=opening
    calls=[]
    orch.catalog_launcher.windows=lambda path:{101}
    orch.catalog_launcher.launch_window=calls.append
    orch._verify_new_browser_window=lambda *args:False
    result=orch.process_command('Abre uma janela do Chrome')
    final=orch.confirm_session_proposal(result.plan,True,orch.session_id,result.confirmation_id)
    assert final.status=='verification_failed' and 'Não repeti' in final.message
    assert calls==[app.path] and not launches
    assert fixture.store.recent()[0].status=='uncertain'


def test_new_window_cancel_and_mutated_plan_do_not_execute(opening):
    _,_,orch,launches=opening
    result=orch.process_command('Abre uma janela do Chrome')
    assert orch.confirm_session_proposal(result.plan,False,orch.session_id,result.confirmation_id).status=='cancelled'
    result=orch.process_command('Abre uma janela do Chrome')
    result.plan.intent.entities['new_window']=False
    assert orch.confirm_session_proposal(result.plan,True,orch.session_id,result.confirmation_id).status=='cancelled'
    assert not launches


def test_repeated_voice_yes_routes_to_real_current_chrome_plan(window, opening):
    _, app, orch, launches = opening
    window._orchestrator.close()
    window._orchestrator = orch
    activate(window)
    result = orch.process_command('abriu google chrome')
    assert result.status == 'awaiting_confirmation'
    window._apply_command_result(result)
    window._conversation_reply()
    window._conversation_playback_finished()
    QTest.qWait(650)
    window._start_confirmation_worker = MagicMock()
    window._on_voice_transcribed(window._voice_pipeline.generation, 'Sim, sim')
    window._start_confirmation_worker.assert_called_once_with(result.plan, True)
    assert orch.confirm_session_proposal(result.plan, True, orch.session_id, result.confirmation_id).status == 'success'
    assert launches == [app.path]
