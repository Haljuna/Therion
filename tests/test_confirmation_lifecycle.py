"""Confirmações são consumidas uma vez, inclusive sob concorrência."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.core.orchestrator import Orchestrator


@pytest.fixture
def orch(tmp_path):
    adapter = MagicMock()
    adapter.create_event.side_effect = lambda **kw: SimpleNamespace(summary=kw['summary'])
    instance = Orchestrator(log_dir=str(tmp_path), calendar_adapter=adapter, simulate=False)
    instance._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    instance.executor.execute_real = MagicMock(return_value=SimpleNamespace(success=True, message='executado'))
    instance.verifier.verify_real = MagicMock(return_value=SimpleNamespace(success=True, message='verificado'))
    return instance


def concurrently_confirm(call):
    barrier = Barrier(2)
    def invoke():
        barrier.wait(timeout=5)
        return call()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        return [f.result(timeout=5) for f in futures]


def test_concurrent_action_clicks_execute_only_once_and_new_request_is_allowed(orch):
    proposal = orch.process_command('abra o Obsidian')
    session, token = orch.session_id, proposal.confirmation_id
    results = concurrently_confirm(lambda: orch.confirm_session_proposal(proposal.plan, True, session, token))
    assert sorted(r.status for r in results) == ['cancelled', 'success']
    orch.executor.execute_real.assert_called_once()
    fresh = orch.process_command('abra o Obsidian')
    assert orch.confirm_and_execute(fresh.plan, True).status == 'success'
    assert orch.executor.execute_real.call_count == 2


def test_concurrent_calendar_transcripts_create_at_most_one_event(orch):
    proposal = orch.process_command('marque reunião amanhã às 15h')
    session, token = orch.session_id, proposal.confirmation_id
    results = concurrently_confirm(lambda: orch.process_session_command('sim', session, token))
    assert sorted(r.status for r in results) == ['cancelled', 'success']
    orch.calendar_adapter.create_event.assert_called_once()
    assert orch.process_command('sim').status == 'cancelled'
    orch.calendar_adapter.create_event.assert_called_once()


@pytest.mark.parametrize('change', ['troque para hoje', 'crie outro compromisso', 'cancele.'])
def test_old_calendar_token_cannot_confirm_after_change(orch, change):
    proposal = orch.process_command('marque reunião amanhã às 15h')
    session, token = orch.session_id, proposal.confirmation_id
    orch.process_command(change)
    assert orch.process_session_command('sim', session, token).status == 'cancelled'
    orch.calendar_adapter.create_event.assert_not_called()


def test_clear_invalidates_workers_and_erases_temporary_evidence(orch):
    proposal = orch.process_command('abra o Obsidian')
    session, token = orch.session_id, proposal.confirmation_id
    orch._last_tool_evidence = object()
    orch._pending_clarification = 'temporário'
    orch.clear_session()
    assert orch.session_id != session
    assert orch.confirmation_id is None
    assert orch._last_tool_evidence is None
    assert orch._pending_clarification is None
    assert orch._pending_action_plan is None
    assert orch._pending_event_draft is None
    assert orch.confirm_session_proposal(proposal.plan, True, session, token).status == 'cancelled'
    assert orch.process_session_command('abra o Obsidian', session, token).status == 'cancelled'
    orch.executor.execute_real.assert_not_called()


def test_changed_or_superseded_action_plan_is_rejected(orch):
    first = orch.process_command('abra o Obsidian')
    first.plan.steps.append('Etapa não confirmada')
    assert orch.confirm_and_execute(first.plan, True).status == 'cancelled'
    second = orch.process_command('abra o Obsidian')
    orch.process_command('liste meus aliases')
    assert orch.confirm_and_execute(second.plan, True).status == 'cancelled'
    orch.executor.execute_real.assert_not_called()


@pytest.mark.parametrize('invalid_reply', [None, SimpleNamespace()])
def test_calendar_uncertain_response_is_not_retried(orch, invalid_reply):
    orch.calendar_adapter.create_event.side_effect = None
    orch.calendar_adapter.create_event.return_value = invalid_reply
    orch.process_command('marque reunião amanhã às 15h')
    result = orch.process_command('sim')
    assert result.status == 'execution_failed'
    assert 'pode ter sido criado' in result.message
    assert 'automaticamente' in result.message
    assert orch._pending_event_draft is None
    orch.process_command('sim')
    orch.calendar_adapter.create_event.assert_called_once()


def test_calendar_write_then_timeout_is_consumed_without_retry(orch):
    orch.calendar_adapter.create_event.side_effect = TimeoutError('resposta perdida')
    orch.process_command('marque reunião amanhã às 15h')
    result = orch.process_command('sim')
    assert result.status == 'execution_failed'
    assert 'Confira seu calendário' in result.message
    orch.process_command('sim!')
    orch.calendar_adapter.create_event.assert_called_once()


def test_cancelled_dispatch_never_processes_or_writes(orch):
    proposal = orch.process_command('marque reunião amanhã às 15h')
    cancelled = Event()
    cancelled.set()
    result = orch.process_session_command('sim', orch.session_id, proposal.confirmation_id, cancelled)
    assert result.status == 'cancelled'
    orch.calendar_adapter.create_event.assert_not_called()
    # Encerrar a voz não apaga a proposta ainda válida para confirmação por texto.
    assert orch.process_command('sim').status == 'success'


@pytest.mark.parametrize('commands,method', [
    (['adicione um alias', 'teste', 'Obsidian'], 'add_alias'),
    (['exclua um alias', 'teste'], 'remove_alias'),
    (['substitua um alias', 'teste', 'Obsidian'], 'replace_alias'),
    (['abra o apelido ficticio', 'Obsidian'], 'add_alias'),
])
def test_failed_alias_write_is_consumed_and_never_retried(orch, commands, method):
    orch.alias_manager.list_aliases = MagicMock(return_value={} if len(commands) == 3 and method == 'add_alias'
                                               else {'teste': 'Obsidian'})
    operation = MagicMock(side_effect=TimeoutError('persistência incerta'))
    setattr(orch.alias_manager, method, operation)
    for command in commands:
        result = orch.process_command(command)
    assert result.status == 'awaiting_confirmation'
    result = orch.process_command('sim')
    assert result.status == 'execution_failed'
    assert 'não vou repetir' in result.message
    assert orch.process_command('sim').status == 'cancelled'
    operation.assert_called_once()
