"""Bateria integrada sem rede, credenciais, modelos ou dispositivos reais."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse, ProviderTimeoutError, ProviderTransportError
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def system(tmp_path):
    notes = tmp_path / '10 - Projetos' / 'Therion'
    notes.mkdir(parents=True)
    (notes / 'z-material.md').write_text('# Prova\nRevisar tabelas-verdade.', encoding='utf-8')
    (notes / 'a-sistema.md').write_text('# Sistema\nUma prova de conceito.', encoding='utf-8')
    provider = MagicMock()
    provider.generate.return_value = AIResponse(type='chat', message='Podemos começar pela prioridade de hoje.')
    provider.describe_result.return_value = 'Encontrei uma nota sobre sua prova. Quer revisar o trecho?'
    adapter = MagicMock()
    adapter.create_event.side_effect = lambda **kw: SimpleNamespace(summary=kw['summary'])
    orch = Orchestrator(log_dir=str(tmp_path / 'logs'), vault_root=str(tmp_path),
                        calendar_adapter=adapter, ai_core=AICore(provider, []))
    orch._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    return orch, provider, adapter


def test_conversation_search_correction_confirmation_cancel_and_clear(system):
    orch, provider, adapter = system
    def send(command):
        return orch.process_session_command(command, orch.session_id, orch.confirmation_id)

    assert send('Estou cansado e preciso decidir o que fazer primeiro').status == 'success'
    result = send('procure no segundo cérebro prova')
    assert result.status == 'success'
    assert result.message.index('z-material.md') < result.message.index('a-sistema.md')
    assert result.speech_message == provider.describe_result.return_value
    assert orch._last_tool_evidence is not None

    first = send('marque reunião amanhã às 15h')
    session, token = orch.session_id, first.confirmation_id
    corrected = send('troque para hoje')
    assert corrected.confirmation_id != token
    assert orch.process_session_command('sim', session, token).status == 'cancelled'
    adapter.create_event.assert_not_called()
    assert send('sim').status == 'success'
    adapter.create_event.assert_called_once()
    assert send('sim').status == 'cancelled'

    send('marque reunião amanhã às 15h')
    assert send('cancele!').status == 'cancelled'
    adapter.create_event.assert_called_once()
    send('crie um lembrete')
    assert 'não consigo configurar avisos' in send('aviso').message
    old_session = orch.session_id
    orch.clear_session()
    assert orch._last_tool_evidence is None
    assert orch._pending_event_draft is None
    assert not orch._pending_reminder_choice
    assert orch.process_session_command('sim', old_session, None).status == 'cancelled'
    assert 'Não encontrei' in send('Qual é meu nome?').message
    adapter.create_event.assert_called_once()


@pytest.mark.parametrize('error,status', [
    (ProviderTimeoutError('tempo excedido'), 'ai_timeout'),
    (ProviderTransportError('ausente'), 'ai_unavailable'),
])
def test_model_failure_still_allows_search_and_calendar_controls(system, error, status):
    orch, provider, adapter = system
    provider.generate.side_effect = error
    provider.describe_result.side_effect = error
    assert orch.process_command('Preciso decidir minhas prioridades').status == status
    found = orch.process_command('procure no segundo cérebro prova')
    assert found.status == 'success'
    assert 'z-material.md' in found.message
    orch.process_command('marque reunião amanhã às 15h')
    orch.process_command('troque para hoje')
    assert orch.process_command('cancele.').status == 'cancelled'
    adapter.create_event.assert_not_called()


def test_uncertain_write_requires_a_new_explicit_request(system):
    orch, _, adapter = system
    adapter.create_event.side_effect = TimeoutError('resposta perdida')
    orch.process_command('marque reunião amanhã às 15h')
    result = orch.process_command('sim')
    assert 'pode ter sido criado' in result.message
    assert orch.process_command('sim').status == 'cancelled'
    adapter.create_event.assert_called_once()
    adapter.create_event.side_effect = lambda **kw: SimpleNamespace(summary=kw['summary'])
    orch.process_command('marque reunião amanhã às 15h')
    assert orch.process_command('sim').status == 'success'
    assert adapter.create_event.call_count == 2
