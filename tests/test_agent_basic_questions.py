"""Perguntas simples passam pelo mesmo dispatcher e worker usados pela janela."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from therion.agent import AgentDecision
from therion.interface.desktop import _CommandWorker
from tests.test_agent_runtime import ScriptedProvider
from tests.test_personal_context_flow import case


def enable(host):
    host._agent_config['enabled']=True
    decision=AgentDecision('final','Não há informação na nota.')
    agent=ScriptedProvider(decision,decision)
    host._agent_provider=agent
    return agent


@pytest.mark.parametrize('worker_entry',[False,True])
def test_today_bypasses_agent_and_google_when_runtime_enabled(case,worker_entry):
    host,provider,calendar,_=case
    agent=enable(host)
    host._now_func=lambda:datetime(2026,10,20,14,tzinfo=ZoneInfo('America/Sao_Paulo'))
    if worker_entry:
        worker=_CommandWorker(host,'Que dia é hoje?');worker.run()
        assert not worker.failed
        result=worker.result
    else:result=host.process_command('Que dia é hoje?')
    assert result.status=='success' and result.message=='Hoje é terça-feira, 20/10/2026.'
    assert not agent.observations
    assert calendar.mock_calls==[]
    provider.describe_result.assert_not_called()


@pytest.mark.parametrize('command',['Qual é meu nome?','Qual é o meu nome?','Como eu me chamo?'])
def test_name_uses_fresh_authorized_profile_in_active_agent(case,command):
    host,provider,_,profile=case
    agent=enable(host)
    provider.describe_result.return_value='Seu nome é Luana.'
    before=profile.read_bytes()
    worker=_CommandWorker(host,command);worker.run()
    assert not worker.failed
    assert worker.result.status=='success' and 'Luana' in worker.result.message
    assert '01 - Pessoal/Perfil.md' in worker.result.message
    assert not agent.observations and profile.read_bytes()==before
    assert provider.describe_result.call_args.args[1]['kind']=='personal_context'


def test_name_does_not_reuse_profile_after_access_revoked(case):
    host,provider,_,_=case
    agent=enable(host)
    provider.describe_result.return_value='Seu nome é Luana.'
    host.process_command('Qual é meu nome?')
    provider.describe_result.reset_mock()
    host.second_brain.allowed_roots=[]
    result=host.process_command('Qual é meu nome?')
    assert 'Luana' not in result.message
    provider.describe_result.assert_not_called()
    assert not agent.observations


def test_actual_full_read_request_still_rejects_unverified_conclusion(case):
    host,_,_,_=case
    agent=enable(host)
    result=host.process_command('Releia a nota Aurora.md inteira.')
    assert result.status=='partial' and 'Não há leitura integral verificada' in result.message
    assert len(agent.observations)==2


def test_date_after_rejected_read_does_not_inherit_reading_requirement(case):
    host,_,_,_=case
    agent=enable(host)
    host._now_func=lambda:datetime(2026,10,20,14,tzinfo=ZoneInfo('America/Sao_Paulo'))
    assert host.process_command('Releia a nota Aurora.md inteira.').status=='partial'
    observations=len(agent.observations)
    result=host.process_command('Que dia é hoje?')
    assert result.status=='success' and '20/10/2026' in result.message
    assert len(agent.observations)==observations


def test_real_qt_send_path_with_enabled_agent_uses_local_date(tmp_path):
    import time
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    app=QApplication.instance() or QApplication([])
    config={'tts':{'enabled':False},'agent':{'enabled':True}}
    vault=tmp_path/'vault';vault.mkdir()
    knowledge=KnowledgeRuntime(vault,tmp_path/'memory',lambda:config)
    with patch.object(MainWindow,'_setup_tray'):
        window=MainWindow(app,config,knowledge_runtime=knowledge,log_dir=str(tmp_path/'logs'))
    try:
        agent=enable(window._orchestrator)
        window._orchestrator._now_func=lambda:datetime(2026,10,20,14,tzinfo=ZoneInfo('America/Sao_Paulo'))
        window._input.setPlainText('Que dia é hoje?')
        window._send_command()
        deadline=time.monotonic()+3
        while window._processing and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        assert not window._processing
        assert 'Hoje é terça-feira, 20/10/2026.' in window._history.toPlainText()
        assert 'Não há leitura integral verificada' not in window._history.toPlainText()
        assert not agent.observations
    finally:
        window._orchestrator.close();window.deleteLater();app.processEvents()
