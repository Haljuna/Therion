"""Pedidos naturais coletam dados; cancelar nunca exclui evento existente."""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
import pytest
from therion.core.ai_core import AICore
from therion.core.orchestrator import Orchestrator
from therion.core.intent import IntentRecognizer
from therion.governance.confirmation import ConfirmationHandler


@pytest.fixture
def orch(tmp_path):
    provider=MagicMock();provider.generate.side_effect=AssertionError('Não depender do classificador para estes controles.')
    adapter=MagicMock();adapter.create_event.return_value.summary='Reunião fictícia'
    instance=Orchestrator(vault_root=str(tmp_path/'vault'),log_dir=str(tmp_path/'logs'),
                          calendar_adapter=adapter,ai_core=AICore(provider,[]))
    instance._now_func=lambda:datetime(2026,10,13,10,tzinfo=ZoneInfo('America/Sao_Paulo'))
    yield instance,provider,adapter
    instance.close()


@pytest.mark.parametrize('command',[
    'marca uma reunião para mim', 'Marca uma reunião pra mim!', 'cria um evento para mim',
    'agenda uma reunião para mim', 'Na verdade, preciso que você cria um evento',
    'Preciso que você crie um evento', 'Quero que você marque uma reunião',
])
def test_natural_start_collects_missing_fields_without_inventing_dates(orch,command):
    assistant,provider,adapter=orch
    result=assistant.process_command(command)
    assert result.status=='awaiting_confirmation',result.message
    assert assistant._pending_event_draft is not None
    assert 'date' not in assistant._pending_event_draft and 'start_time' not in assistant._pending_event_draft
    assert assistant._pending_event_draft.get('title') not in {'Para mim','Pra mim'}
    provider.generate.assert_not_called();adapter.create_event.assert_not_called()


@pytest.mark.parametrize('cancel',['Cancela','Cancela!','cancele.','cancelar'])
def test_cancel_at_collection_and_without_pending_request_is_deterministic(orch,cancel):
    assistant,provider,adapter=orch
    assistant.process_command('marca uma reunião para mim')
    assert assistant.process_command(cancel).status=='cancelled'
    assert assistant._pending_event_draft is None
    assert assistant.process_command(cancel).status=='cancelled'
    provider.generate.assert_not_called();adapter.create_event.assert_not_called()


def test_full_collection_presents_proposal_and_only_specific_yes_creates(orch):
    assistant,provider,adapter=orch
    assert assistant.process_command('Na verdade, preciso que você cria um evento').status=='awaiting_confirmation'
    assistant.process_command('Reunião fictícia')
    assistant.process_command('amanhã')
    result=assistant.process_command('às 15h')
    assert result.status=='awaiting_confirmation' and 'Confirmar?' in result.message
    adapter.create_event.assert_not_called()
    assert assistant.process_command('sim').status=='success'
    adapter.create_event.assert_called_once()
    assert assistant.process_command('Cancela!').status=='cancelled'
    adapter.create_event.assert_called_once();adapter.delete_event.assert_not_called()
    provider.generate.assert_not_called()


@pytest.mark.parametrize('command',['não marca uma reunião','talvez cria um evento','Na verdade, não preciso que você crie um evento'])
def test_negation_and_uncertainty_do_not_start_creation_parser(command):
    assert IntentRecognizer().parse(command) is None


@pytest.mark.parametrize('command',['Cancela!','cancelar.','CANCELE'])
def test_cancel_is_negative_but_does_not_mean_delete_event(command):
    handler=ConfirmationHandler()
    assert handler.evaluate_response(command) is False
    assert handler.evaluate_response(command+' a reunião de amanhã') is None


def test_cancel_consumes_informational_question_without_model_or_event_mutation(orch):
    assistant,provider,adapter=orch
    assistant._pending_clarification='Qual é a disciplina?'
    assert assistant.process_command('Cancela!').status=='success'
    assert assistant._pending_clarification is None
    provider.generate.assert_not_called();adapter.create_event.assert_not_called()
