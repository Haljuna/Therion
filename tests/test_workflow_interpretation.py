"""Pedidos fictícios, sem calendário, arquivos pessoais ou inferência real."""
from datetime import datetime
from unittest.mock import Mock

import pytest

from therion.core.ai_provider import AIProvider, ProviderTimeoutError
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.workflows import WorkflowError, interpret_workflow


@pytest.mark.parametrize('message', [
    'olá', 'Estou cansado e preciso estudar.', 'Liste minhas tarefas.',
    'Therion, abra o Obsidian', 'Por favor, abra o Obsidian',
    'Olá, consulte a agenda amanhã',
    'Minha ideia é organizar arquivos e liste minhas tarefas',
    'Adicione uma tarefa comprar pão e leite',
    'Adicione tarefas estudar; limpar; comprar pão',
    'Adicione uma tarefa leia a primeira nota',
    'Adicione uma tarefa "leia a nota e liste minhas tarefas"',
    'Adicione tarefas: leia a primeira nota; resuma o artigo',
    'Adicione tarefas: marque duas reuniões; estudar',
    'Marque uma reunião Pesquisa e desenvolvimento amanhã às 15 por uma hora',
    'Procure notas sobre "circuitos e resuma a primeira"',
    'Monte um plano de Circuitos Lógicos e Álgebra Linear',
])
def test_simple_commands_do_not_call_model(message):
    provider = Mock()
    assert interpret_workflow(message, provider) is None
    provider.interpret_workflow_commands.assert_not_called()


@pytest.mark.parametrize('message, actions', [
    ('Veja minha agenda amanhã e liste minhas tarefas pendentes.', ['calendar_query', 'task_list']),
    ('Veja minha agenda amanhã e minhas tarefas pendentes.', ['calendar_query', 'task_list']),
    ('O que tenho amanhã? E liste minhas tarefas.', ['calendar_query', 'task_list']),
    ('Procure minhas notas sobre circuitos e resuma a primeira.', ['note_search', 'note_summary']),
    ('Busque no Segundo Cérebro circuitos; leia a segunda nota; resuma a primeira.', ['note_search', 'note_read', 'note_summary']),
    ('Adicione uma tarefa organizar arquivos e depois liste minhas tarefas.', ['task_add', 'task_list']),
    ('Adicione organizar arquivos à minha lista e mostre as tarefas.', ['task_add', 'task_list']),
    ('Conclua a tarefa 2 e reabra a tarefa 3', ['task_complete', 'task_reopen']),
    ('Planeje meu dia e liste as tarefas', ['calendar_query', 'task_list']),
    ('Liste tarefas e prepare uma reunião amanhã às 15 por uma hora', ['task_list', 'calendar_create']),
    ('Veja a agenda amanhã e marque uma reunião amanhã das 15 às 16', ['calendar_query', 'calendar_create']),
])
def test_compound_recognition(message, actions):
    provider = Mock()
    spec = interpret_workflow(message, provider, {'now': datetime(2026, 10, 9, 8)})
    assert [step.action for step in spec.steps] == actions
    assert all(step.command in message for step in spec.steps)
    provider.interpret_workflow_commands.assert_not_called()


def test_parameters_are_preserved_and_references_bound_to_each_search():
    text = 'Procure notas sobre Circuitos e Álgebra; resuma a primeira; procure notas sobre Matrizes; leia a segunda nota'
    spec = interpret_workflow(text)
    assert spec.steps[0].arguments == {'query': 'Circuitos e Álgebra'}
    assert spec.steps[1].arguments == {'index': 1}
    assert spec.steps[1].depends_on == (0,)
    assert spec.steps[3].depends_on == (2,)


def test_titles_and_task_descriptions_keep_literals():
    spec = interpret_workflow('Adicione uma tarefa comprar pão e leite e liste tarefas')
    assert spec.steps[0].arguments['request']['text'] == 'comprar pão e leite'
    spec = interpret_workflow('Liste tarefas e marque uma reunião "Pesquisa e liste tarefas" amanhã às 15')
    assert spec.steps[1].arguments['draft']['title'] == '"Pesquisa e liste tarefas"'


def test_explicit_batch_keeps_imperatives_as_descriptions_before_list():
    spec = interpret_workflow('Adicione tarefas: leia a nota; resuma o artigo e depois liste tarefas')
    assert spec.steps[0].arguments['request']['text'] == 'leia a nota; resuma o artigo'
    assert spec.steps[1].action == 'task_list'


@pytest.mark.parametrize('message', [
    'Liste tarefas e não marque uma reunião amanhã às 15',
    'Não liste tarefas e marque uma reunião amanhã às 15',
    'Liste tarefas e salve minhas notas',
    'Liste tarefas e envie meus e-mails',
    'Liste tarefas e abra o Obsidian',
    'Liste tarefas e marque uma reunião',
    'Liste tarefas e marque uma reunião amanhã às 25',
    'Liste tarefas e marque uma reunião em 31/02/2027 às 15',
    'Liste tarefas e marque uma reunião amanhã das 16 às 15',
    'Liste tarefas e marque uma reunião amanhã das 15 às 16 por duas horas',
    'Liste tarefas e marque uma reunião amanhã às 15 por 0 minutos',
    'Marque uma reunião amanhã às 15 e liste tarefas',
    'Marque uma reunião amanhã às 15 e marque outra reunião amanhã às 17',
    'Agende duas reuniões amanhã às 15',
    'Liste tarefas e agende 2 eventos amanhã às 15',
    'Liste tarefas e resuma a primeira nota',
    'Procure notas sobre circuitos e leia essa nota',
    'Adicione uma tarefa e liste tarefas',
    'Conclua a tarefa dois e liste tarefas',
    'Liste tarefas e marque uma reunião amanhã às 15 sem confirmar',
    'Liste tarefas; liste tarefas; liste tarefas; liste tarefas; liste tarefas; liste tarefas',
])
def test_invalid_compounds_never_return_partial_plan(message):
    with pytest.raises(WorkflowError):
        interpret_workflow(message)


def test_optional_fallback_decomposes_only_literal_complete_request_once():
    message = 'Liste tarefas; e veja agenda amanhã'
    provider = Mock()
    provider.interpret_workflow_commands.return_value = {'commands': ['Liste tarefas', 'veja agenda amanhã']}
    spec = interpret_workflow(message, provider)
    assert [step.action for step in spec.steps] == ['task_list', 'calendar_query']
    provider.interpret_workflow_commands.assert_called_once_with(message, context={}, timeout_seconds=20)


@pytest.mark.parametrize('proposal', [
    {'commands': ['Liste tarefas', 'marque reunião amanhã às 15']},
    {'commands': ['veja agenda amanhã', 'Liste tarefas']},
    {'commands': ['Liste tarefas']},
    {'commands': ['Liste tarefas', 'veja agenda amanhã'], 'execute': True},
    {'commands': ['Liste tarefas', 'veja agenda amanhã'], 'arguments': {}},
    {'commands': ['Liste tarefas', 'veja agenda amanhã', 'veja agenda amanhã']},
    {'commands': [None, 'veja agenda amanhã']},
])
def test_fallback_cannot_invent_drop_reorder_or_add_commands(proposal):
    provider = Mock()
    provider.interpret_workflow_commands.return_value = proposal
    with pytest.raises(WorkflowError):
        interpret_workflow('Liste tarefas; e veja agenda amanhã', provider)
    provider.interpret_workflow_commands.assert_called_once()


def test_fallback_cannot_drop_unsupported_action():
    provider = Mock()
    provider.interpret_workflow_commands.return_value = {'commands': ['Liste tarefas', 'veja agenda amanhã']}
    with pytest.raises(WorkflowError):
        interpret_workflow('Liste tarefas e envie e-mail e veja agenda amanhã', provider)


def test_provider_failure_and_elapsed_timeout_do_not_return_partial_plan(monkeypatch):
    provider = Mock()
    provider.interpret_workflow_commands.side_effect = ProviderTimeoutError('fake')
    with pytest.raises(WorkflowError):
        interpret_workflow('Liste tarefas; e veja agenda amanhã', provider)
    provider.interpret_workflow_commands.side_effect = None
    provider.interpret_workflow_commands.return_value = {'commands': ['Liste tarefas', 'veja agenda amanhã']}
    ticks = iter((0, 21))
    monkeypatch.setattr('therion.core.workflows.time.monotonic', lambda: next(ticks))
    with pytest.raises(WorkflowError, match='demorou'):
        interpret_workflow('Liste tarefas; e veja agenda amanhã', provider)


def test_optional_provider_default_keeps_compatibility():
    assert AIProvider.interpret_workflow_commands(object(), 'fake') is None


def test_ollama_fallback_schema_timeout_and_no_conversation_context(monkeypatch):
    provider = OllamaProvider(model='fake', timeout=8)
    captured = {}
    def send(payload, timeout):
        captured.update(payload=payload, timeout=timeout)
        return '{"commands":["Liste tarefas","veja agenda amanhã"]}'
    monkeypatch.setattr(provider, '_send_request', send)
    result = provider.interpret_workflow_commands('Liste tarefas; e veja agenda amanhã',
        context={'recent_turns': [{'role': 'user', 'text': 'PRIVATE OLD CONTEXT'}]}, timeout_seconds=99)
    assert len(result['commands']) == 2
    assert captured['timeout'] == 8
    assert captured['payload']['format']['additionalProperties'] is False
    assert 'PRIVATE OLD CONTEXT' not in str(captured['payload'])
