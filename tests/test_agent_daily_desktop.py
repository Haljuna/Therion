"""Reprodução dos pedidos relatados no painel Qt, com perfil fictício."""
from unittest.mock import Mock

from tests.test_personal_context_desktop import panel,send,wait_until
from tests.test_agent_daily_commands import daily


def test_daily_capabilities_profile_and_app_reach_main_confirmation_panel(panel):
    window,provider,_=panel
    host=window._orchestrator
    host._agent_config['enabled']=True
    host.executor.execute_real=Mock(side_effect=AssertionError('Nenhum aplicativo real'))
    send(window,'O que você pode fazer?')
    assert 'Segundo Cérebro' in window._history.toPlainText()
    assert 'núcleo de ferramentas está ativo' in window._history.toPlainText()
    send(window,'Quem sou eu?')
    assert 'Engenharia Biomédica' in window._history.toPlainText()
    assert '01 - Pessoal/Perfil.md' in window._history.toPlainText()
    send(window,'abrir o obsidian')
    assert window._pending_plan is not None
    assert not window._processing
    assert not window._confirm_panel.isHidden()
    assert window._pending_plan.intent.target=='Obsidian'
    assert host._agent_proposals.list()==[]
    assert host._agent_store.operations()[0]['state']=='awaiting_confirmation'
    window._handle_confirmation('não')
    wait_until(lambda:not window._processing)
    assert host._agent_store.operations()[0]['state']=='cancelled'
    host.executor.execute_real.assert_not_called()
    provider.generate.assert_not_called()


def test_personal_question_displays_limitation_when_model_cannot_compose(panel):
    window,provider,_=panel
    window._orchestrator._agent_config['enabled']=True
    provider.describe_result.return_value=None
    send(window,'Quem sou eu?')
    answer=window._history.toPlainText().split('Quem sou eu?')[-1]
    assert 'Não consegui compor' in answer
    assert 'Fontes:' in answer and '01 - Pessoal/Perfil.md' in answer
    assert not window._processing and window._pending_plan is None
    provider.generate.assert_not_called()


def test_registered_chrome_reaches_normal_confirmation_panel(panel,daily):
    window,provider,_=panel
    host=window._orchestrator
    host._agent_config['enabled']=True
    host._init_autonomy(daily.autonomy)
    host.executor.execute_real=Mock(side_effect=AssertionError('Nenhuma abertura real'))
    send(window,'abre o chrome')
    assert 'Chrome' in window._history.toPlainText()
    assert window._pending_plan is not None and not window._processing
    assert not window._confirm_panel.isHidden()
    receipt=host._agent_store.operations()[0]
    assert receipt['state']=='awaiting_confirmation' and not receipt['verified']
    window._handle_confirmation('não')
    wait_until(lambda:not window._processing)
    assert host._agent_store.operations(receipt['call_id'])[0]['state']=='cancelled'
    host.executor.execute_real.assert_not_called()
    provider.generate.assert_not_called()
