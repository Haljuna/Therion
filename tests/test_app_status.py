"""Estado atual de aplicativos sem inferência, abertura ou evidência fictícia."""
import os
from unittest.mock import Mock

import pytest

from tests import test_autonomy_v4 as autonomy_fixture
from therion.autonomy.apps import ApplicationCatalog,CatalogLauncher
from therion.autonomy.integration import implementation_version
from therion.context.conversation_frame import app_status_request
from therion.core.orchestrator import Orchestrator


@pytest.fixture(params=[False,True],ids=['legacy','agent'])
def status_host(request):
    fixture=autonomy_fixture.AutonomyTests();fixture.setUp()
    path=fixture.root/'obsidian.exe';path.write_bytes(b'fixture never execute')
    app=ApplicationCatalog(fixture.runtime).register('Obsidian',str(path))
    ai=Mock()
    ai.classify_detailed.side_effect=AssertionError('Sem inferência para consultar processo')
    host=Orchestrator(simulate=False,log_dir=str(fixture.root/'logs'),autonomy_runtime=fixture.runtime,
        ai_core=ai,agent_config={'enabled':request.param},agent_state_root=fixture.root/'agent')
    host.voice_conversation=True
    processes=set();launch=Mock(side_effect=AssertionError('Consulta não abre aplicativos'))
    host.catalog_launcher=CatalogLauncher(host.application_catalog,lambda:processes,launch)
    yield fixture,app,host,processes,launch
    launch.assert_not_called();ai.classify_detailed.assert_not_called()
    host.close();fixture.tearDown()


@pytest.mark.parametrize('command',[
    'O obsidian está aberto.', 'O obzinho está aberto.', 'O obsídio está aberto?',
    'Obsidian já está aberto!', 'Confere se o Obsidian está aberto',
    'Etérion, o Obsidian tá aberto?', 'Eterion, o obsidian tá aberto?',
    'Etério, o Obsidian tá aberto?', 'Eterio o Obsidian está aberto?',
])
def test_status_uses_current_process_and_never_enters_model_context(status_host,command,monkeypatch):
    fixture,app,host,processes,_=status_host
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    store=Mock(side_effect=AssertionError('Consulta não precisa construir contexto do agente'))
    monkeypatch.setattr(host,'_get_agent_store',store)
    result=host.process_command(command)
    assert result.status=='success',result.message
    assert 'Obsidian está aberto' in result.message
    assert result.plan is None and host.confirmation_id is None
    assert fixture.store.recent()==[]
    store.assert_not_called()
    processes.clear()
    result=host.process_command(command)
    assert result.status=='success'
    assert 'Não encontrei um processo acessível' in result.message
    assert 'Não abri' in result.message
    assert fixture.store.recent()==[]


def test_status_failure_is_not_reported_as_closed(status_host):
    _,_,host,_,_=status_host
    host.catalog_launcher.paths=Mock(side_effect=OSError('Processos indisponíveis'))
    result=host.process_command('O Obsidian está aberto?')
    assert result.status=='verification_failed'
    assert 'não confirma' in result.message and 'fechado' in result.message


def test_status_preserves_permission_and_executable_identity(status_host,monkeypatch):
    _,app,host,_,_=status_host
    with monkeypatch.context() as patch:
        patch.setattr(host.permission_manager,'is_allowed',lambda intent:False)
        assert host.process_command('O Obsidian está aberto?').status=='forbidden'
    from pathlib import Path
    Path(app.path).write_bytes(b'changed executable')
    assert host.process_command('O Obsidian está aberto?').status=='verification_failed'


def test_unknown_status_requests_catalog_name_without_guessing(status_host):
    _,_,host,_,_=status_host
    result=host.process_command('O aplicativo desconhecido está aberto?')
    assert result.status=='clarification' and 'nome cadastrado' in result.message


@pytest.mark.parametrize('command',[
    'Abre o Obsidian', 'O Obsidian está aberto e feche o Chrome',
    'Se o Obsidian está aberto', 'Talvez o Obsidian está aberto',
    'Não abra o Obsidian',
])
def test_app_status_parser_never_executes_compound_or_conditional_request(command):
    assert app_status_request(command) is None


@pytest.mark.parametrize('command',['Abre o Obsidian','Então abre o obsidian.','Agora abre o obsidian pra mim.','Abra o Obsidian para mim por favor!','Térion, abre o obsidian pra mim.'])
def test_exact_opening_with_manual_grant_does_not_request_confirmation(status_host,command):
    fixture,app,host,_,_=status_host
    # O processo já está aberto: verifica a autorização sem lançar a fixture.
    host.catalog_launcher.paths=lambda:{os.path.normcase(os.path.realpath(app.path))}
    version=implementation_version(fixture.runtime,app.as_dict())
    fixture.runtime.grant('open_app',app.id,version,'Escolha visual de teste')
    result=host.process_command(command)
    assert result.status=='success',result.message
    assert 'já está aberto' in result.message
    assert host.confirmation_id is None


@pytest.mark.parametrize('command',['Abriu.','Fechou?'])
def test_bare_result_word_is_not_an_execution(status_host,command):
    fixture,_,host,_,_=status_host
    result=host.process_command(command)
    assert result.status=='clarification'
    assert 'Nenhuma ação' in result.message and result.plan is None
    assert fixture.store.recent()==[]


def test_close_after_executable_update_says_what_changed(status_host):
    # 04/11: o Chrome se atualizou e a recusa dizia só "permissão ou executável".
    _,app,host,processes,_=status_host
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    from pathlib import Path
    Path(app.path).write_bytes(b'executavel atualizado')
    result=host.process_command('Fecha o Obsidian')
    assert result.status in {'forbidden','verification_failed'}
    assert 'Obsidian' in result.message and ('mudou' in result.message or 'atualizado' in result.message)


@pytest.mark.parametrize('command',['Fecha o obsidian.','Fecha o obsídio.','Fechar, Obsidian.'])
def test_close_requests_real_confirmation_and_verifies_process(status_host,command):
    fixture,app,host,processes,_=status_host
    processes.add(os.path.normcase(os.path.realpath(app.path)));windows={101};sent=[]
    host.catalog_launcher.windows=lambda path:set(windows)
    def close(path,handles):sent.append((path,handles));windows.clear();processes.clear()
    host.catalog_launcher.close_windows=close
    result=host.process_command(command)
    assert result.status=='awaiting_confirmation',result.message
    assert sent==[] and fixture.store.recent()==[]
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='success',final.message
    assert 'confirmei o encerramento' in final.message
    assert sent==[(app.path,{101})]
    evidence=fixture.store.recent()[0]
    assert evidence.operation=='close_app' and evidence.verified


def test_close_pending_save_dialog_or_tray_process_never_claims_closed(status_host):
    fixture,app,host,processes,_=status_host
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    host.catalog_launcher.windows=lambda path:{101}
    close=Mock();host.catalog_launcher.close_windows=close;host._wait_close=lambda app:False
    result=host.process_command('Fecha o Obsidian')
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='verification_failed'
    assert 'ainda tem janela ou processo ativo' in final.message
    assert 'Fechei' not in final.message
    close.assert_called_once()
    assert fixture.store.recent()[0].status=='uncertain'


def test_unknown_close_and_cancel_never_close_windows(status_host):
    fixture,_,host,_,_=status_host
    close=Mock();host.catalog_launcher.close_windows=close
    assert host.process_command('Fecha o amizade').status=='clarification'
    result=host.process_command('Fecha o Obsidian')
    final=host.confirm_session_proposal(result.plan,False,host.session_id,result.confirmation_id)
    assert final.status=='cancelled'
    close.assert_not_called();assert fixture.store.recent()==[]


def test_close_rechecks_registration_after_confirmation_preview(status_host):
    _,app,host,_,_=status_host
    close=Mock();host.catalog_launcher.close_windows=close
    result=host.process_command('Fecha o Obsidian')
    from pathlib import Path
    Path(app.path).write_bytes(b'changed')
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='execution_failed'
    close.assert_not_called()


def test_close_in_simulation_never_sends_window_messages(status_host):
    fixture,_,host,_,_=status_host
    fixture.runtime._update(lambda section:section.update(app_opening_mode='simulation'))
    close=Mock();host.catalog_launcher.close_windows=close
    host.catalog_launcher.windows=Mock(side_effect=AssertionError('Simulação não consulta janelas'))
    result=host.process_command('Fecha o Obsidian')
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='executed_simulated'
    close.assert_not_called()
    assert fixture.store.recent()[0].mode=='simulation' and not fixture.store.recent()[0].verified


@pytest.mark.parametrize('phase',['begin','finish'])
def test_close_receipt_storage_failure_never_claims_verified_success(status_host,monkeypatch,phase):
    import sqlite3
    fixture,_,host,_,_=status_host
    host.catalog_launcher.windows=lambda path:{101}
    close=Mock();host.catalog_launcher.close_windows=close;host._wait_close=lambda app:True
    result=host.process_command('Fecha o Obsidian')
    monkeypatch.setattr(fixture.store,phase,Mock(side_effect=sqlite3.OperationalError('disk full')))
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='execution_failed'
    assert 'Não confirmei' in final.message and 'Fechei' not in final.message
    assert close.call_count==(0 if phase=='begin' else 1)


def register_browser(fixture,host):
    path=fixture.root/'chrome.exe';path.write_bytes(b'fixture browser never execute')
    return ApplicationCatalog(fixture.runtime).register('Chrome',str(path),('navegador',))


@pytest.mark.parametrize('command',['É. O crônico tá aberto.','Etérion, o Chrome tá aberto?'])
def test_browser_status_with_vocative_and_known_voice_variant(status_host,command):
    fixture,_,host,processes,_=status_host
    app=register_browser(fixture,host)
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    result=host.process_command(command)
    assert result.status=='success' and 'Chrome está aberto' in result.message


def test_bare_browser_name_completes_only_pending_process_query(status_host):
    fixture,_,host,processes,_=status_host
    app=register_browser(fixture,host)
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    first=host.process_command('Etérion, o desconhecido tá aberto?')
    assert first.status=='clarification'
    result=host.process_command('Navegador.')
    assert result.status=='success',result.message
    assert 'Chrome está aberto' in result.message
    assert fixture.store.recent()==[] and host._pending_status_query is None


@pytest.mark.parametrize('change',['timeout','session','topic'])
def test_process_query_followup_expires_on_time_session_or_topic(status_host,monkeypatch,change):
    fixture,_,host,_,_=status_host
    register_browser(fixture,host)
    clock=[100.0];monkeypatch.setattr(host,'_language_clock',lambda:clock[0])
    assert host.process_command('O desconhecido está aberto?').status=='clarification'
    if change=='timeout':clock[0]+=121
    elif change=='session':host._session_id='new-session'
    else:
        result=host.process_command('Que dia é hoje?')
        assert result.status=='success'
    assert host._catalog_status_followup('Navegador') is None


def test_known_browser_voice_variant_does_not_override_literal_catalog_name(status_host):
    fixture,_,host,processes,_=status_host
    register_browser(fixture,host)
    path=fixture.root/'other.exe';path.write_bytes(b'fixture literal name')
    literal=ApplicationCatalog(fixture.runtime).register('Crônico',str(path))
    processes.add(os.path.normcase(os.path.realpath(literal.path)))
    result=host.process_command('O crônico está aberto?')
    assert result.status=='success' and 'Crônico está aberto' in result.message


@pytest.mark.parametrize('command',['Fecha o Jaminai.','Fecha o Geminai.','Fecha o gêmeo.'])
def test_gemini_known_voice_variants_prepare_only_registered_target_with_confirmation(status_host,command):
    fixture,_,host,_,_=status_host
    path=fixture.root/'gemini.exe';path.write_bytes(b'fixture gemini never execute')
    app=ApplicationCatalog(fixture.runtime).register('Gemini',str(path))
    result=host.process_command(command)
    assert result.status=='awaiting_confirmation',result.message
    assert result.intent.target==app.id and 'Gemini' in result.message
    assert fixture.store.recent()==[]
    assert host.confirm_session_proposal(result.plan,False,host.session_id,result.confirmation_id).status=='cancelled'


def test_missing_close_executable_explains_update_instead_of_generic_failure(status_host):
    _,app,host,_,_=status_host
    from pathlib import Path
    Path(app.path).unlink()
    result=host.process_command('Fecha o Obsidian')
    assert result.status=='verification_failed'
    assert 'atualizado' in result.message and 'Revise o caminho' in result.message
    assert result.plan is None


def test_discord_hidden_window_can_be_closed_normally_after_preference_change(status_host):
    fixture,_,host,processes,_=status_host
    path=fixture.root/'discord.exe';path.write_bytes(b'fixture never execute')
    app=ApplicationCatalog(fixture.runtime).register('Discord',str(path))
    processes.add(os.path.normcase(os.path.realpath(app.path)))
    hidden={101};sent=[]
    host.catalog_launcher.windows=lambda path:set()
    host.catalog_launcher.closeable_windows=lambda app:set(hidden)
    def close(path,windows):sent.append((path,windows));hidden.clear();processes.clear()
    host.catalog_launcher.close_windows=close
    result=host.process_command('Fecha o Discord')
    assert result.status=='awaiting_confirmation'
    final=host.confirm_session_proposal(result.plan,True,host.session_id,result.confirmation_id)
    assert final.status=='success' and 'confirmei o encerramento' in final.message
    assert sent==[(app.path,{101})]
    assert fixture.store.recent()[0].verified
