"""Perguntas sobre tarefas usam a mesma fonte do panorama; o modelo não pode negar o que existe."""
from unittest.mock import patch

import pytest

from therion.core.orchestrator import Orchestrator
from therion.integrations.task_query import render, task_query_request

ROW = {'state': 'ready', 'message': '', 'temporary': [],
       'saved': [{'title': 'Escolher Lugar do date', 'state': 'pending'},
                 {'title': 'teste', 'state': 'completed'}]}


@pytest.mark.parametrize('phrase', [
    'Come a tarefa pendente', 'Qual é a tarefa pendente?', 'quais tarefas eu tenho?',
    'tenho alguma tarefa?', 'me fala a tarefa pendente', 'lista de tarefas', 'Therion, tarefas pendentes',
])
def test_reading_requests_are_recognized(phrase):
    assert task_query_request(phrase)


@pytest.mark.parametrize('phrase', [
    'crie uma tarefa de comprar pão', 'marque a tarefa como concluída', 'apague a tarefa pendente',
    'adicione uma tarefa', 'qual é o compromisso?', 'boa noite', 'a tarefa',
    # Já tratados pelo fluxo de tarefas da sessão ou de workflows:
    'liste tarefas pendentes', 'quais são minhas tarefas', 'minha agenda de hoje e minhas tarefas',
])
def test_writes_and_other_subjects_are_not_captured(phrase):
    assert not task_query_request(phrase)


def test_render_lists_only_pending():
    screen, spoken = render(ROW)
    assert spoken == 'Você tem uma tarefa pendente: Escolher Lugar do date.'
    assert 'teste' not in screen


def test_render_empty_and_unavailable():
    assert render(dict(ROW, saved=[]))[1] == 'Você não tem tarefas pendentes.'
    assert 'Não consegui' in render({'state': 'disconnected', 'message': 'Ative Tarefas.', 'saved': [], 'temporary': []})[1]


def test_orchestrator_answers_from_same_source_as_briefing(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path))
    with patch('therion.interface.dashboard_data.DashboardSource.tasks', return_value=ROW):
        result = orch.process_command('Come a tarefa pendente')
    assert result.status == 'success'
    assert 'Escolher Lugar do date' in result.speech_message
