"""Coordenação de etapas com executores fictícios e bloqueios controlados."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from therion.core.workflow_runtime import WorkflowRuntime, render_workflow
from therion.core.workflows import WorkflowSpec, WorkflowStep


def spec(*steps):
    return WorkflowSpec(tuple(
        WorkflowStep(action, action, {}, dependencies)
        for action, dependencies in steps
    ))


def result(status='success', message='Resultado verificado.', speech='Resumo falado.', **fields):
    return SimpleNamespace(status=status, message=message, speech_message=speech, **fields)


def test_sequential_dependencies_receive_verified_receipts_and_same_session():
    runtime, calls = WorkflowRuntime(), []
    source = {'paths': ('Nota fictícia.md',), 'roots': ('cofre fictício',)}

    def execute(step, index, receipts):
        calls.append((step.action, index))
        assert runtime.active
        assert runtime.snapshot().receipts[index].state == 'running'
        if index:
            assert receipts[0].state == 'completed'
            assert receipts[0].evidence is source
            assert receipts[index].state == 'running'
        return result(message=step.action), source if index == 0 else {'read': True}

    outcome = runtime.run(spec(('note_search', ()), ('note_read', (0,))), 'session-one', execute)
    assert calls == [('note_search', 0), ('note_read', 1)]
    assert outcome.session_id == 'session-one'
    assert outcome.state == 'completed'
    assert [row.state for row in outcome.receipts] == ['completed', 'completed']
    assert runtime.snapshot() is outcome
    assert not runtime.active


@pytest.mark.parametrize('failure', ['status', 'exception'])
def test_failures_block_dependents_but_continue_independent_steps(failure):
    runtime, calls = WorkflowRuntime(), []

    def execute(step, index, receipts):
        calls.append(index)
        if index == 0:
            if failure == 'exception':
                raise RuntimeError('falha simulada sem informação pessoal')
            return result('execution_failed', 'Serviço fictício indisponível.'), None
        return result(), {'ok': True}

    outcome = runtime.run(spec(('note_search', ()), ('note_read', (0,)), ('task_list', ())),
                          'session-one', execute)
    assert calls == [0, 2]
    assert outcome.state == 'partial'
    assert [row.state for row in outcome.receipts] == ['failed', 'blocked', 'completed']
    assert outcome.receipts[1].evidence is None
    assert not runtime.active


@pytest.mark.parametrize(('status', 'state'), [('clarification', 'awaiting_clarification'),
                                             ('uncertain', 'uncertain')])
def test_clarification_or_uncertain_write_stops_all_later_steps(status, state):
    runtime, calls = WorkflowRuntime(), []

    def execute(step, index, receipts):
        calls.append(index)
        return result(status), None

    outcome = runtime.run(spec(('task_add', ()), ('calendar_query', ())), 's', execute)
    assert calls == [0]
    assert outcome.state == state
    assert [row.state for row in outcome.receipts] == [state, 'blocked']
    assert not runtime.active


def test_only_one_active_request_and_only_last_finished_result_is_retained():
    runtime = WorkflowRuntime()
    first = runtime.run(spec(('task_list', ())), 's', lambda *_: (result(), None))
    entered, release = Event(), Event()

    def execute(*_):
        entered.set()
        assert release.wait(3)
        return result(), None

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.run, spec(('calendar_query', ())), 's', execute)
        try:
            assert entered.wait(2)
            active = runtime.snapshot()
            assert active.id != first.id
            assert active.state == 'running'
            with pytest.raises(ValueError, match='ativo'):
                runtime.run(spec(('task_list', ())), 's', lambda *_: (result(), None))
        finally:
            release.set()
        second = future.result(timeout=3)
    assert runtime.snapshot() is second
    third = runtime.run(spec(('task_list', ())), 's', lambda *_: (result(), None))
    assert runtime.snapshot() is third
    assert third.id != second.id
    assert not runtime.active


@pytest.mark.parametrize('cancel_kind', ['runtime', 'worker'])
def test_cancel_during_blocking_call_returns_immediately_and_prevents_next_step(cancel_kind):
    runtime, calls = WorkflowRuntime(), []
    entered, release, worker_cancelled = Event(), Event(), Event()

    def execute(step, index, receipts):
        calls.append(index)
        entered.set()
        assert release.wait(3)
        return result(), {'already_finished': True}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.run, spec(('calendar_query', ()), ('task_add', ())),
                             's', execute, worker_cancelled)
        try:
            assert entered.wait(2)
            runtime.cancel() if cancel_kind == 'runtime' else worker_cancelled.set()
            assert not future.done()
        finally:
            release.set()
        outcome = future.result(timeout=3)
    assert calls == [0]
    assert outcome.state == 'cancelled'
    assert [row.state for row in outcome.receipts] == ['completed', 'cancelled']
    assert outcome.receipts[0].evidence == {'already_finished': True}


def test_clear_invalidates_late_results_without_repopulating_snapshot():
    runtime = WorkflowRuntime()
    entered, release = Event(), Event()
    calls = []

    def execute(step, index, receipts):
        calls.append(index)
        entered.set()
        assert release.wait(3)
        return result(), {'discard_me': True}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.run, spec(('note_search', ()), ('note_read', (0,))), 'old', execute)
        try:
            assert entered.wait(2)
            runtime.clear()
            assert runtime.snapshot() is None
            assert not runtime.active
        finally:
            release.set()
        outcome = future.result(timeout=3)
    assert calls == [0]
    assert outcome.state == 'cancelled'
    assert runtime.snapshot() is None


@pytest.mark.parametrize('interrupt', ['clear', 'abandon'])
def test_new_request_cannot_reset_cancellation_of_old_blocked_request(interrupt):
    runtime, old_calls = WorkflowRuntime(), []
    old_entered, old_release, new_entered, new_release = Event(), Event(), Event(), Event()

    def old_execute(step, index, receipts):
        old_calls.append(index)
        if index == 0:
            old_entered.set()
            assert old_release.wait(3)
        return result(message='Resultado antigo.'), None

    def new_execute(*_):
        new_entered.set()
        assert new_release.wait(3)
        return result(message='Resultado atual.'), None

    with ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(runtime.run, spec(('calendar_query', ()), ('task_add', ())), 'old', old_execute)
        try:
            assert old_entered.wait(2)
            getattr(runtime, interrupt)()
            new_future = pool.submit(runtime.run, spec(('task_list', ())), 'new', new_execute)
            assert new_entered.wait(2)
            new_id = runtime.snapshot().id
            old_release.set()
            old_result = old_future.result(timeout=3)
            assert old_calls == [0], 'Pedido antigo não pode executar próxima etapa após começar outro pedido.'
            assert old_result.state == 'cancelled'
            assert runtime.snapshot().id == new_id
            assert runtime.snapshot().session_id == 'new'
        finally:
            old_release.set()
            new_release.set()
        new_result = new_future.result(timeout=3)
    assert runtime.snapshot() is new_result
    assert new_result.state == 'completed'


def test_calendar_proposal_and_correction_keep_same_workflow_and_terminal_step():
    runtime, calls = WorkflowRuntime(), []

    def execute(step, index, receipts):
        calls.append(index)
        if index == 1:
            return result('awaiting_confirmation', 'Vou criar: reunião às 15h. Confirmar?',
                          confirmation_id='proposal-first'), {'draft': 'first'}
        return result(), {'verified': True}

    pending = runtime.run(spec(('calendar_query', ()), ('calendar_create', ())), 's', execute)
    assert pending.state == 'awaiting_confirmation'
    assert runtime.active
    assert [row.state for row in pending.receipts] == ['completed', 'awaiting_confirmation']
    corrected = runtime.calendar_result(result('awaiting_confirmation', 'Vou criar: reunião às 16h. Confirmar?',
                                               confirmation_id='proposal-new'))
    assert corrected.id == pending.id
    assert corrected.state == 'awaiting_confirmation'
    assert corrected.receipts[-1].message == 'Vou criar: reunião às 16h. Confirmar?'
    assert corrected.receipts[0] == pending.receipts[0]
    assert calls == [0, 1]
    finished = runtime.calendar_result(result('success', 'Criei a reunião às 16h.'))
    assert finished.state == 'completed'
    assert not runtime.active
    assert runtime.snapshot() is finished
    assert runtime.calendar_result(result('success', 'Não repetir.')) is None


@pytest.mark.parametrize(('status', 'message', 'state'), [
    ('cancelled', 'Operação cancelada.', 'cancelled'),
    ('execution_failed', 'Serviço indisponível.', 'failed'),
    ('execution_failed', 'O evento pode ter sido criado. Confira antes de tentar novamente.', 'uncertain'),
])
def test_calendar_terminal_failure_or_cancel_does_not_resume_or_retry(status, message, state):
    runtime, calls = WorkflowRuntime(), []

    def execute(step, index, receipts):
        calls.append(index)
        return result('awaiting_confirmation'), None

    runtime.run(spec(('calendar_create', ())), 's', execute)
    outcome = runtime.calendar_result(result(status, message))
    assert outcome.state == state
    assert outcome.receipts[-1].state == state
    assert calls == [0]
    assert not runtime.active
    assert runtime.calendar_result(result('success')) is None


def test_calendar_success_preserves_earlier_partial_failure():
    runtime = WorkflowRuntime()

    def execute(step, index, receipts):
        return (result('execution_failed'), None) if index == 0 else (result('awaiting_confirmation'), None)

    runtime.run(spec(('calendar_query', ()), ('calendar_create', ())), 's', execute)
    outcome = runtime.calendar_result(result('success', 'Criei o evento confirmado.'))
    assert outcome.state == 'partial', 'Criar evento não transforma consulta anterior falha em sucesso integral.'
    assert [row.state for row in outcome.receipts] == ['failed', 'completed']
    assert not runtime.active


def test_abandon_preserves_completed_operations_and_cancels_proposal():
    runtime = WorkflowRuntime()
    outcome = runtime.run(spec(('task_add', ()), ('calendar_create', ())), 's',
                          lambda step, index, rows: (result('success' if index == 0 else 'awaiting_confirmation'),
                                                    {'task_id': 1} if index == 0 else None))
    runtime.abandon()
    abandoned = runtime.snapshot()
    assert abandoned.id == outcome.id
    assert abandoned.state == 'cancelled'
    assert abandoned.receipts[0] == outcome.receipts[0]
    assert abandoned.receipts[0].evidence == {'task_id': 1}
    assert abandoned.receipts[1].state == 'cancelled'
    assert not runtime.active
    assert runtime.calendar_result(result('success')) is None
    message, speech = render_workflow(abandoned)
    assert 'não foram desfeitas' in message
    assert 'não foram desfeitas' in speech


def test_render_keeps_full_details_and_limits_spoken_summary():
    runtime = WorkflowRuntime()
    outcome = runtime.run(spec(('task_list', ()), ('calendar_query', ())), 's',
                          lambda *_: (result(message='Detalhe verificado. ' * 60, speech='Fala. ' * 150), None))
    message, speech = render_workflow(outcome)
    assert '1. concluída' in message
    assert '2. concluída' in message
    assert message.count('Detalhe verificado.') == 120
    assert len(speech) <= 1800
def test_terminal_confirmation_remains_spoken_after_four_large_results():
    from therion.core.workflow_runtime import WorkflowSnapshot, StepReceipt, render_workflow
    rows = tuple(StepReceipt(i, 'note_read', 'completed', speech='Resposta longa. ' * 100) for i in range(4))
    rows += (StepReceipt(4, 'calendar_create', 'awaiting_confirmation', speech='Vou criar uma reunião amanhã, às quinze horas. Confirmar?'),)
    _, speech = render_workflow(WorkflowSnapshot('id', 'session', 'awaiting_confirmation', rows))
    assert len(speech) <= 1800 and speech.endswith('Confirmar?')

