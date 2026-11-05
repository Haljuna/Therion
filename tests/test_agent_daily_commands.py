"""Pedidos cotidianos não dependem de uma nova interpretação do modelo."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from therion.agent.direct import ExplicitAppProvider
from therion.autonomy.apps import ApplicationCatalog
from therion.autonomy.runtime import AutonomyRuntime
from therion.autonomy.store import EvidenceStore
from therion.core.orchestrator import Orchestrator
from tests.test_personal_context_flow import case


@pytest.fixture
def daily(tmp_path):
    config = {}
    def write(value):
        config.clear(); config.update(deepcopy(value))
    runtime = AutonomyRuntime(EvidenceStore(tmp_path/'autonomy.sqlite3'), lambda:deepcopy(config), write)
    executable=tmp_path/'chrome.exe'
    executable.write_bytes(b'Executable fixture; must never be launched')
    ApplicationCatalog(runtime).register('Chrome',str(executable),aliases=('Google Chrome','navegador','gmail'))
    host=Orchestrator(simulate=True, vault_root=str(tmp_path/'vault'), log_dir=str(tmp_path/'logs'),
        autonomy_runtime=runtime, agent_config={'enabled':True}, agent_state_root=tmp_path/'agent')
    host.executor.execute_real=Mock(side_effect=AssertionError('Sem efeito real'))
    yield host
    host.executor.execute_real.assert_not_called()
    host.close()


@pytest.mark.parametrize('command',['abre o chrome','abre o obsidian','abrir o obsidian','Abra o Google Chrome!',
    'abre o navegador','abra o gmail'])
def test_explicit_app_uses_runtime_and_confirmation_even_without_model(daily,command):
    result=daily.process_command(command)
    assert result.status=='awaiting_confirmation', result.message
    assert result.plan is not None
    assert isinstance(daily._agent_runtime.provider,ExplicitAppProvider)
    assert 'buscar notas' not in result.message.casefold()
    assert 'simular' in result.message.casefold() or 'confirm' in result.message.casefold()
    receipts=daily._agent_store.operations()
    assert receipts[0]['state']=='awaiting_confirmation' and not receipts[0]['verified']
    identifier=daily._confirmation_id
    final=daily.confirm_session_proposal(result.plan,False,daily.session_id,identifier)
    assert final.status=='cancelled'
    assert daily._agent_store.operations(receipts[0]['call_id'])[0]['state']=='cancelled'
    assert daily.confirm_session_proposal(result.plan,True,daily.session_id,identifier).status=='cancelled'


def test_unregistered_app_is_explained_without_claiming_all_opening_is_impossible(daily):
    result=daily.process_command('abre o AplicativoDesconhecido')
    assert 'catálogo aprovado' in result.message
    assert 'Autonomia' in result.message
    assert not any(row['verified'] for row in daily._agent_store.operations())
    assert daily._confirmation_id is None


@pytest.mark.parametrize('command',['O que você pode fazer?','Quais são suas capacidades?',
    'O que você faz?','Como você pode me ajudar?'])
def test_capabilities_uses_installation_instead_of_first_catalog_page(daily,command):
    result=daily.process_command(command)
    assert result.status=='success'
    assert 'Segundo Cérebro' in result.message and 'Chrome' in result.message
    assert 'núcleo de ferramentas está ativo' in result.message
    assert 'Gmail' in result.message and 'desativados nesta configuração' in result.message
    assert 'Histórico persistente de conversa: desativado' in result.message
    assert daily._agent_runtime is None
    assert daily._confirmation_id is None


def test_capabilities_does_not_confuse_enabled_with_healthy_service(daily):
    daily._agent_config.update(gmail_enabled=True,documents_enabled=True)
    result=daily.process_command('O que você pode fazer?')
    assert 'Recursos opcionais habilitados: Gmail e rascunhos, documentos locais.' in result.message
    assert 'não testou as conexões' in result.message
    assert daily._agent_runtime is None


@pytest.mark.parametrize('general_simulation,catalog_mode,expected,spoken',[
    (True,'real','confirmação antes da execução','depois da sua confirmação'),
    (False,'simulation','não abro o aplicativo de verdade','não os abro de verdade'),
    (True,'invalid','Não confirmei o modo de abertura','precisa ser revisto'),
])
def test_capabilities_report_effective_catalog_mode_without_changing_it(daily,general_simulation,catalog_mode,expected,spoken):
    daily.simulate=general_simulation
    daily.autonomy._update(lambda section:section.update(app_opening_mode=catalog_mode))
    result=daily.process_command('O que você pode fazer?')
    assert expected in result.message
    assert spoken in result.speech_message
    assert daily.autonomy.section()['app_opening_mode']==catalog_mode
    assert daily._agent_runtime is None


def test_capabilities_then_personal_question_remains_grounded_and_respects_revocation(case):
    host,provider,_,profile=case
    host._agent_config['enabled']=True
    host._agent_root=profile.parent.parent/'agent-state'
    original=profile.read_bytes()
    result=host.process_command('O que você pode fazer?')
    assert 'Segundo Cérebro' in result.message
    result=host.process_command('Quem sou eu?')
    assert result.status=='success' and 'Engenharia Biomédica' in result.message
    assert '01 - Pessoal/Perfil.md' in result.message
    provider.generate.assert_not_called()
    assert profile.read_bytes()==original
    host.second_brain.allowed_roots=[]
    provider.describe_result.reset_mock()
    denied=host.process_command('Quem sou eu?')
    assert 'escopo' in denied.message and 'Engenharia Biomédica' not in denied.message
    provider.describe_result.assert_not_called()
