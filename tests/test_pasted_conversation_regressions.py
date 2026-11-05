"""Frases do teste de voz: escopo, confirmação e fontes permanecem governados."""
from types import SimpleNamespace

import pytest

from tests.test_agent_voice_calendar_search import enable,send
from tests.test_personal_context_flow import case
from tests.test_agent_daily_commands import daily
from therion.core.intent import IntentRecognizer
from therion.context.conversation_frame import personal_request
from therion.governance.confirmation import ConfirmationHandler


@pytest.mark.parametrize('command',[
    'Cria uma reunião para amanhã.',
    'Marca uma reunião para amanhã.',
    'Agende uma reunião para amanhã.',
])
def test_date_connector_is_not_meeting_title(case,command):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    send(host,command)
    result=send(host,'As 15.')
    assert result.status=='awaiting_confirmation'
    assert 'Título: Reunião' in result.message
    assert host._pending_event_draft['date']=='amanhã'
    assert host._pending_event_draft['start_time']=='15:00'
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()


def test_real_title_with_connector_is_preserved():
    intent=IntentRecognizer().parse('Crie um evento Para todos amanhã às 15h')
    assert intent.entities['title']=='Para todos'


@pytest.mark.parametrize('command',['Agora abre o Chrome.','Agora, abre o navegador.'])
def test_now_open_uses_catalog_and_confirmation_without_llm(daily,command):
    result=daily.process_command(command)
    assert result.status=='awaiting_confirmation',result.message
    assert result.plan is not None and daily._confirmation_id
    assert daily._agent_store.operations()[0]['state']=='awaiting_confirmation'
    assert daily.confirm_session_proposal(result.plan,False,daily.session_id,daily._confirmation_id).status=='cancelled'
    daily.executor.execute_real.assert_not_called()


@pytest.mark.parametrize('command',['Agora não abre o Chrome.','Talvez agora abre o Chrome.',
                                  'Se eu pedir, agora abre o Chrome.'])
def test_prefix_does_not_remove_negation_or_conditions(command):
    assert IntentRecognizer().parse(command) is None


@pytest.mark.parametrize('command',['Resume quem sou eu.','Resuma quem sou eu.',
                                  'Resume quem eu sou.'])
def test_summary_uses_authorized_profile_and_rechecks_revocation(case,command):
    host,provider,calendar,profile=case
    enable(host)
    original=profile.read_bytes()
    result=send(host,command)
    assert result.status=='success' and 'Engenharia Biomédica' in result.message
    assert 'Perfil.md' in result.message and profile.read_bytes()==original
    assert not host._agent_provider.observations
    provider.describe_result.reset_mock()
    host.second_brain.allowed_roots=[]
    result=send(host,command)
    assert 'Engenharia Biomédica' not in result.message
    provider.describe_result.assert_not_called()
    calendar.create_event.assert_not_called()


def test_negated_summary_does_not_trigger_profile_read():
    assert personal_request('Não resume quem sou eu.') is None


@pytest.mark.parametrize('answer',['Pode','pode.','Pode!'])
def test_pode_confirms_exact_pending_event_only_once(case,answer):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    calendar.create_event.return_value=SimpleNamespace(summary='Reunião')
    send(host,'Cria uma reunião para amanhã.')
    send(host,'As 15.')
    result=send(host,answer)
    assert result.status=='success',result.message
    calendar.create_event.assert_called_once()
    assert send(host,answer).status in {'cancelled','success'}
    calendar.create_event.assert_called_once()
    provider.generate.assert_not_called()


@pytest.mark.parametrize('answer',['Pode?','talvez pode','pode, mas depois','não pode','pode não','So'])
def test_ambiguous_or_misheard_confirmation_is_not_positive(answer):
    assert ConfirmationHandler().evaluate_response(answer) is None
