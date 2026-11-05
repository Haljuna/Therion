"""Concluir/reabrir tarefa salva: o modelo não decide se a tarefa existe; a confirmação continua obrigatória."""
import asyncio
import json

import pytest

from therion.agent.contracts import CancellationToken
from therion.agent.direct import ExplicitTaskStateProvider
from therion.integrations.task_query import task_state_request

PENDING = [{'id': 'a' * 32, 'title': 'Escolher Lugar do date', 'state': 'pending'},
           {'id': 'b' * 32, 'title': 'Comprar presente', 'state': 'pending'}]


@pytest.mark.parametrize('phrase,state,hint', [
    ('Conclui a tarefa pendente', 'completed', ''),
    ('conclua a tarefa pendente', 'completed', ''),
    ('marque a tarefa pendente como feita', 'completed', ''),
    ('finalize a tarefa escolher lugar do date', 'completed', 'escolher lugar do date'),
    ('reabra a tarefa comprar presente', 'pending', 'comprar presente'),
])
def test_requests_are_recognized(phrase, state, hint):
    assert task_state_request(phrase) == {'state': state, 'hint': hint}


@pytest.mark.parametrize('phrase', [
    'conclua a tarefa 2', 'marque a tarefa 3 como concluída', 'conclua essa tarefa',  # tarefas da sessão
    'qual é a tarefa pendente?', 'crie uma tarefa', 'conclua o relatório',
])
def test_other_requests_are_not_captured(phrase):
    assert task_state_request(phrase) is None


def run(provider, observations):
    """Simula o runtime: cada chamada de ferramenta recebe a observação seguinte."""
    messages, calls = [], []
    while True:
        decision = asyncio.run(provider.decide(messages, [], None, CancellationToken(), lambda *a: None))
        if decision.kind == 'final':
            return calls, decision.message
        call = decision.calls[0]
        if call.name == 'load_tools':  # o runtime só aceita ferramentas carregadas
            assert call.arguments == {'names': ['list_inbox', 'prepare_task_state']}
            messages.append({'role': 'tool', 'content': json.dumps({'status': 'success'})})
            continue
        calls.append((call.name, call.arguments))
        messages.append({'role': 'tool', 'content': json.dumps(observations.pop(0))})


def test_tools_are_loaded_before_use():
    decision = asyncio.run(ExplicitTaskStateProvider('completed', '').decide([], [], None, CancellationToken(), None))
    assert decision.calls[0].name == 'load_tools'


def listing(rows):
    return {'status': 'success', 'data': {'tasks': rows}}


def test_single_pending_task_is_prepared_for_confirmation():
    prepared = {'status': 'awaiting_confirmation', 'message': 'Alterar tarefa Escolher Lugar do date. Confirma?'}
    calls, message = run(ExplicitTaskStateProvider('completed', ''), [listing(PENDING[:1]), prepared])
    assert calls[0] == ('list_inbox', {'state': 'pending', 'limit': 10})
    assert calls[1] == ('prepare_task_state', {'id': 'a' * 32, 'state': 'completed'})
    assert message == prepared['message']


def test_hint_selects_one_of_many():
    calls, _ = run(ExplicitTaskStateProvider('completed', 'escolher lugar do date'),
                   [listing(PENDING), {'status': 'awaiting_confirmation', 'message': 'ok'}])
    assert calls[1][1]['id'] == 'a' * 32


def test_ambiguous_asks_which_one_without_preparing():
    calls, message = run(ExplicitTaskStateProvider('completed', ''), [listing(PENDING)])
    assert [name for name, _ in calls] == ['list_inbox']
    assert 'Escolher Lugar do date' in message and 'Comprar presente' in message and 'Qual' in message


def test_none_found_says_so_with_source():
    calls, message = run(ExplicitTaskStateProvider('completed', ''), [listing([])])
    assert len(calls) == 1
    assert 'tarefas salvas' in message


@pytest.fixture
def real_host(tmp_path):
    from therion.core.orchestrator import Orchestrator
    from therion.integrations.tasks import TaskInbox
    # Mesmo orçamento da configuração real: 5120/4352 estourava com o prompt do sistema.
    orch = Orchestrator(simulate=True, vault_root=str(tmp_path), log_dir=str(tmp_path / 'logs'),
                        agent_config={'enabled': True, 'tasks_enabled': True, 'gmail_enabled': False,
                                      'context_tokens': 5120, 'output_tokens': 4352, 'history_enabled': True},
                        agent_state_root=tmp_path / 'agent')
    inbox = TaskInbox(orch._get_agent_store())
    identifier = inbox.create('Escolher Lugar do date', {'id': 'user:current'})
    yield orch, inbox, identifier
    orch.close()


def test_real_host_prepares_completion_and_writes_only_after_confirmation(real_host):
    orch, inbox, identifier = real_host
    result = orch.process_command('Conclui a tarefa pendente')
    assert result.status == 'awaiting_confirmation', result.message
    assert 'Escolher Lugar do date' in result.message
    assert isinstance(orch._agent_runtime.provider, ExplicitTaskStateProvider)
    assert inbox.get(identifier)['state'] == 'pending'  # nada muda antes da aprovação
    # Escritas do agente são aprovadas no painel Capacidades, como as demais.
    row = orch._agent_proposals.list()[0]
    approved = orch._agent_proposals.approve_visual(row.id, row.digest, CancellationToken())
    assert approved.status == 'success', approved.message
    assert inbox.get(identifier)['state'] == 'completed'


def test_blocked_listing_reports_tool_message():
    _, message = run(ExplicitTaskStateProvider('completed', ''),
                     [{'status': 'blocked', 'message': 'Tarefas locais estão desativadas.'}])
    assert message == 'Tarefas locais estão desativadas.'
