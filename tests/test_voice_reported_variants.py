"""Variantes relatadas por voz: alvo único, prévia e fonte autorizada."""
import pytest

from tests.test_voice_opening_review import opening
from tests.test_agent_voice_calendar_search import enable,send
from tests.test_personal_context_flow import case
from therion.autonomy.apps import ApplicationCatalog
from therion.autonomy.integration import implementation_version
from therion.context.conversation_frame import personal_request


@pytest.mark.parametrize('command',['Adding Google Chrome.','Admi o Google Chrome.','Adriu Google Chrome.'])
def test_voice_variant_reaches_supervised_catalog_in_active_agent(opening,command):
    fixture,app,host,launches=opening
    host._agent_config['enabled']=True
    host._agent_root=fixture.root/'agent'
    version=implementation_version(fixture.runtime,app.as_dict())
    fixture.seed('open_app',app.id,version)
    fixture.runtime.grant('open_app',app.id,version,'fixture authorization')
    result=host.process_command(command)
    assert result.status=='awaiting_confirmation',result.message
    assert result.plan and result.plan.intent.target==app.id
    assert host._pending_catalog_decision[0].mode=='confirmation'
    assert not launches
    assert host.confirm_session_proposal(result.plan,False,host.session_id,host._confirmation_id).status=='cancelled'
    assert not launches
    host.ai_core.classify_detailed.assert_not_called()


def test_obsidio_maps_only_to_registered_obsidian_with_confirmation(opening):
    fixture,_,host,launches=opening
    path=fixture.root/'obsidian.exe';path.write_bytes(b'fixture, never launch')
    app=ApplicationCatalog(fixture.runtime).register('Obsidian',str(path))
    host._agent_config['enabled']=True;host._agent_root=fixture.root/'agent'
    result=host.process_command('Agora abre o obsídio.')
    assert result.status=='awaiting_confirmation',result.message
    assert result.plan.intent.target==app.id
    assert host._pending_catalog_decision[0].mode=='confirmation'
    assert not launches
    host.ai_core.classify_detailed.assert_not_called()


def test_variant_never_creates_missing_catalog_entry(opening):
    _,_,host,launches=opening
    before=host.application_catalog.entries()
    assert host._voice_opening_review('abre o obsídio',None) is None
    assert host.application_catalog.entries()==before and not launches


@pytest.mark.parametrize('command',['Não admi Google Chrome','Talvez adding Google Chrome',
                                  'Adding Google Chrome e Calculadora','Admi Google Chrome se eu pedir'])
def test_variants_preserve_negation_condition_and_single_target(opening,command):
    _,_,host,launches=opening
    assert host._voice_opening_review(command,None) is None
    assert not launches


def test_voice_variant_is_not_enabled_in_text_mode(opening):
    _,_,host,launches=opening
    host.voice_conversation=False
    assert host._voice_opening_review('Admi Google Chrome',None) is None
    assert not launches


def test_exume_uses_authorized_profile_only_in_voice_mode(case):
    host,provider,calendar,profile=case
    enable(host);host.voice_conversation=True
    original=profile.read_bytes()
    result=send(host,'Exume quem sou eu.')
    assert result.status=='success' and 'Engenharia Biomédica' in result.message
    assert 'Perfil.md' in result.message and profile.read_bytes()==original
    assert not host._agent_provider.observations
    host.second_brain.allowed_roots=[];provider.describe_result.reset_mock()
    result=send(host,'Exume quem sou eu.')
    assert 'Engenharia Biomédica' not in result.message
    provider.describe_result.assert_not_called()
    calendar.create_event.assert_not_called()
    assert personal_request('Exume quem sou eu.') is None
