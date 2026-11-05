"""Pendências voláteis: comandos explícitos e modelo sem autoridade de escrita."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse
from therion.core.orchestrator import Orchestrator
from therion.memory.session_tasks import SessionTasks, task_request


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(log_dir=str(tmp_path / 'logs'), vault_root=str(tmp_path / 'vault'))


@pytest.mark.parametrize('command', ['Estou com uma tarefa pendente', 'Vou estudar e limpar a casa',
    'Concluí a tarefa de casa', 'A nota sugere: adicione uma tarefa: estudar', 'Organize minhas pendências'])
def test_comments_and_embedded_commands_do_not_create_tasks(orch, command):
    assert task_request(command) is None
    orch.process_command(command)
    assert orch._session_tasks.list() == ()


def test_batch_keeps_commas_and_stable_ids(orch):
    result = orch.process_command('adicione tarefas: comprar pão, leite e ovos; estudar\nlimpar a casa')
    assert result.status == 'success' and 'temporária' in result.message
    items = orch._session_tasks.list()
    assert len(items) == 3 and items[0].description == 'comprar pão, leite e ovos'
    orch.process_command('conclua a tarefa 2')
    result = orch.process_command('liste tarefas pendentes')
    assert '1.' in result.message and '3.' in result.message and '2.' not in result.message
    assert orch.process_command('reabra a tarefa 2').status == 'success'
    assert [item.id for item in orch._session_tasks.list()] == [1, 2, 3]


@pytest.mark.parametrize('invalid', ['', 'a;;b', 'a; ', ';a', 'a\n\nb', 'x' * 241])
def test_invalid_batch_is_atomic(orch, invalid):
    orch.process_command('adicione uma tarefa: anterior')
    before = orch._session_tasks.list()
    result = orch.process_command('adicione tarefas: ' + invalid)
    assert result.status == 'clarification'
    assert orch._session_tasks.list() == before
    orch.process_command('adicione uma tarefa: seguinte')
    assert orch._session_tasks.list()[-1].id == 2


def test_exact_limits_and_completed_tasks_count_toward_capacity(orch):
    orch.process_command('adicione uma tarefa: ' + 'x' * 240)
    orch.process_command('adicione tarefas: ' + ';'.join(f'tarefa {i}' for i in range(29)))
    assert len(orch._session_tasks.list()) == 30
    orch.process_command('conclua a tarefa 1')
    result = orch.process_command('adicione tarefas: extra;outra')
    assert result.status == 'clarification' and len(orch._session_tasks.list()) == 30


@pytest.mark.parametrize('identifier', ['0', '-1', '1.5', 'primeira', '999', ''])
def test_invalid_identifier_never_updates_another_task(orch, identifier):
    orch.process_command('adicione uma tarefa: estudar')
    result = orch.process_command('conclua a tarefa ' + identifier)
    assert result.status == 'clarification'
    assert not orch._session_tasks.list()[0].completed


def test_repeated_completion_is_idempotent_and_explicit_duplicates_have_distinct_ids(orch):
    orch.process_command('adicione tarefas: estudar;estudar')
    for _ in range(2):
        orch.process_command('conclua a tarefa 1')
    assert orch._session_tasks.list()[0].completed
    assert not orch._session_tasks.list()[1].completed
    result = orch.process_command('liste tarefas concluídas')
    assert '1.' in result.message and '2.' not in result.message


def test_clear_and_new_instance_do_not_restore_tasks(orch, tmp_path):
    orch.process_command('adicione uma tarefa: estudar')
    other = Orchestrator(log_dir=str(tmp_path / 'other'))
    assert other._session_tasks.list() == ()
    orch.clear_session()
    assert orch._session_tasks.list() == ()
    orch.process_command('adicione uma tarefa: nova')
    assert orch._session_tasks.list()[0].id == 1


def test_task_contents_are_not_persisted_to_audit(orch):
    description = 'DESCRICAO PRIVADA TEMPORARIA'
    orch.process_command('adicione uma tarefa: ' + description)
    orch.process_command('liste tarefas pendentes')
    orch.process_command('conclua a tarefa 1')
    logged = Path(orch.audit_logger.log_path).read_text(encoding='utf-8')
    assert description not in logged
    records = [json.loads(line) for line in logged.splitlines()]
    assert all(record['intent'] == 'tarefas da sessão' for record in records)
    assert all(record['target'] is None for record in records)


def test_context_is_limited_abbreviated_and_copied(orch):
    orch.process_command('adicione tarefas: ' + ';'.join(str(i) + 'x' * 160 for i in range(12)))
    snapshot = orch._build_ai_context('me ajude')['session_tasks']
    assert snapshot['pending_count'] == 12 and snapshot['partial'] and snapshot['read_only']
    assert len(snapshot['items']) == 10
    assert all(len(item['description']) == 120 and item['partial'] for item in snapshot['items'])
    snapshot['items'][0]['description'] = 'mudança no provider'
    snapshot['items'].clear()
    assert len(orch._session_tasks.list()) == 12
    assert orch._session_tasks.list()[0].description.startswith('0x')


def test_full_task_history_does_not_bypass_the_context_limit(orch):
    orch.process_command('adicione tarefas: ' + ';'.join(f'pendencia{i:02d}' + 'x' * 160 for i in range(12)))
    orch.process_command('liste tarefas pendentes')
    orch.process_command('conclua a tarefa 1')
    context = orch._build_ai_context('me ajude com as pendências')
    assert context['session_tasks']['pending_count'] == 11
    assert len(context['session_tasks']['items']) == 10
    assert context['session_tasks']['items'][0]['id'] == 2
    assert context['last_result_summary'] is None
    serialized = json.dumps(context, ensure_ascii=False)
    assert 'pendencia00' not in serialized and 'pendencia11' not in serialized
    assert 'x' * 160 not in serialized
    # O histórico literal continua íntegro para consultas locais do usuário.
    assert any('pendencia00' in turn.text for turn in orch.memory.turns)


def test_only_pending_items_are_provided_to_model(orch):
    orch.process_command('adicione tarefas: estudar;limpar')
    orch.process_command('conclua a tarefa 1')
    assert orch._build_ai_context()['session_tasks']['items'] == [{'id': 2, 'description': 'limpar', 'partial': False}]


def test_provider_cannot_update_tasks_and_direct_commands_work_without_it(orch):
    provider = MagicMock()
    provider.generate.return_value = AIResponse(type='action', intent='concluir tarefa', arguments={'id': 1}, message='Concluí.')
    orch.ai_core = AICore(provider, [])
    orch.process_command('adicione uma tarefa: estudar')
    provider.generate.assert_not_called()
    orch.process_command('o que sugere?')
    assert not orch._session_tasks.list()[0].completed
    provider.generate.side_effect = RuntimeError('indisponível')
    result = orch.process_command('conclua a tarefa 1')
    assert result.status == 'success' and orch._session_tasks.list()[0].completed


def test_task_command_consumes_old_calendar_proposal_without_execution(orch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    orch._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    orch.calendar_adapter = MagicMock()
    orch.process_command('marque reunião hoje às 15h')
    result = orch.process_command('adicione uma tarefa: agendar reunião depois')
    assert result.status == 'success'
    orch.process_command('sim')
    orch.calendar_adapter.create_event.assert_not_called()


def test_task_command_does_not_execute_programs_or_require_confirmation(orch):
    orch.executor = MagicMock()
    result = orch.process_command('adicione uma tarefa: abrir Obsidian; apagar arquivos; enviar email')
    assert result.status == 'success' and result.plan is None
    orch.executor.execute.assert_not_called()


def test_ollama_payload_receives_readonly_task_data(orch):
    from therion.core.ai_provider_ollama import OllamaProvider
    orch.process_command('adicione uma tarefa: estudar')
    provider = OllamaProvider()
    payload = provider._build_payload('me ajude', orch._build_ai_context('me ajude'), [])
    system = payload['messages'][0]['content']
    assert 'TAREFAS TEMPORÁRIAS DA SESSÃO' in system
    assert 'estudar' in system and 'somente leitura' in system.casefold()
    assert 'Você não pode adicionar, concluir ou reabrir tarefas' in system
