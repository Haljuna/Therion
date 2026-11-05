"""Pedidos compostos de leitura com e-mail (04/11): resposta determinística, sem o modelo."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from therion.calendar.models import CalendarEvent
from therion.core.orchestrator import Orchestrator
from therion.core.workflows import WorkflowError, interpret_workflow

TZ = ZoneInfo('America/Sao_Paulo')
NOW = datetime(2026, 11, 4, 15, 22, tzinfo=TZ)


def actions(command):
    spec = interpret_workflow(command, context={'now': NOW})
    return [(step.action, step.depends_on) for step in spec.steps] if spec else None


@pytest.mark.parametrize('command', [
    'Quais são minhas tarefas de hoje e tem algum e-mail importante?',
    'Queria saber quais são minhas tarefas de hoje, e se tem algum e meio importante.',
])
def test_tasks_and_important_mail_split(command):
    assert actions(command) == [('saved_tasks', ()), ('mail_important', ())]


def test_agenda_and_mail_about_its_events_depend_on_calendar():
    assert actions('O que eu tenho na agenda para esta semana, e algum e-mail fala desses compromissos?') == [
        ('calendar_query', ()), ('mail_about_events', (0,))]


def test_mail_about_events_without_calendar_step_is_rejected():
    with pytest.raises(WorkflowError):
        interpret_workflow('Quais são minhas tarefas de hoje e algum e-mail fala desses compromissos?', context={'now': NOW})


def test_only_read_only_compounds_skip_the_agent():
    from therion.core.workflows import read_only_workflow
    assert read_only_workflow('Quais são minhas tarefas de hoje e tem algum e-mail importante?', NOW)
    # Escrita continua no fluxo com proposta e confirmação.
    assert not read_only_workflow('Veja minha agenda de hoje e marque reunião amanhã às 15h', NOW)
    assert not read_only_workflow('Quais são minhas tarefas de hoje?', NOW)  # simples: não é composto


def test_existing_compound_is_unchanged():
    assert [a for a, _ in actions('Veja minha agenda de hoje e liste minhas tarefas')] == ['calendar_query', 'task_list']


def message(identifier, subject, sender='Fulano <f@example.com>'):
    return {'id': identifier, 'threadId': 't' + identifier, 'internalDate': '1793800000000', 'labelIds': ['INBOX', 'IMPORTANT'],
            'payload': {'headers': [{'name': 'Subject', 'value': subject}, {'name': 'From', 'value': sender}]}}


@pytest.fixture
def host(tmp_path):
    client = MagicMock()
    client.profile.return_value = {'email': 'eu@example.com'}
    boxes = {}
    client.search.side_effect = lambda query, page=None: {'messages': [
        {'id': m['id'], 'threadId': m['threadId']} for m in boxes.get(query, [])]}
    client.metadata.side_effect = lambda identifier: next(m for ms in boxes.values() for m in ms if m['id'] == identifier)
    calendar = MagicMock()
    start = datetime(2026, 11, 5, 15, tzinfo=TZ)
    calendar.list_events_for_day.side_effect = lambda day: (
        [CalendarEvent('e1', 'Reunião de negócios', start, start + timedelta(hours=1), False)] if day == start.date() else [])
    orch = Orchestrator(simulate=True, vault_root=str(tmp_path), log_dir=str(tmp_path / 'logs'), calendar_adapter=calendar,
                        agent_config={'enabled': True, 'gmail_enabled': True, 'tasks_enabled': True,
                                      'context_tokens': 5120, 'output_tokens': 4352},
                        agent_state_root=tmp_path / 'agent')
    orch._now_func = lambda: NOW
    orch._gmail_adapter_factory = lambda mode: client
    from therion.integrations.tasks import TaskInbox
    TaskInbox(orch._get_agent_store()).create('Escolher Lugar do date', {'id': 'user:current'})
    yield orch, client, boxes
    orch.close()


def test_tasks_and_important_mail_answered_without_model(host):
    orch, client, boxes = host
    boxes['in:inbox is:important newer_than:1d'] = [message('m1', 'Reunião confirmada')]
    result = orch.process_command('Quais são minhas tarefas de hoje e tem algum e-mail importante?')
    assert result.status == 'success', result.message
    assert 'Escolher Lugar do date' in result.message
    assert 'Reunião confirmada' in result.message and 'Fulano' in result.message
    assert 'Escolher Lugar do date' in result.speech_message and 'Reunião confirmada' in result.speech_message


def test_mail_about_this_week_events(host):
    orch, client, boxes = host
    boxes['"Reunião de negócios" newer_than:30d'] = [message('m2', 'Pauta da reunião de negócios')]
    result = orch.process_command('O que eu tenho na agenda para esta semana, e algum e-mail fala desses compromissos?')
    assert result.status == 'success', result.message
    assert 'Reunião de negócios' in result.message
    assert 'Pauta da reunião de negócios' in result.message


def test_no_important_mail_says_so(host):
    orch, _, _ = host
    result = orch.process_command('Quais são minhas tarefas de hoje e tem algum e-mail importante?')
    assert 'Nenhum e-mail marcado como importante' in result.message
