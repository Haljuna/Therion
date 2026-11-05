"""Roteamento das frases reais em tests/frases_reais.txt; nenhuma frase que já falhou pode voltar a falhar."""
from pathlib import Path

import pytest

from therion.agent.briefing import briefing_command
from therion.core.intent import IntentRecognizer
from therion.integrations.task_query import task_query_request, task_state_request

BANK = Path(__file__).with_name('frases_reais.txt')


def cases():
    if not BANK.exists():  # banco pessoal, fica fora do git
        return
    for number, line in enumerate(BANK.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        phrase, expected = (part.strip() for part in line.split('=>', 1))
        yield pytest.param(phrase, expected, id=f'L{number}:{phrase[:40]}')


def route(phrase):
    """Mesma ordem do orquestrador: panorama e tarefas antes das regras fixas; o resto vai para a IA."""
    if briefing_command(phrase):
        return 'panorama'
    if task_query_request(phrase):
        return 'tarefas'
    from therion.core.workflows import read_only_workflow
    if read_only_workflow(phrase):
        return 'composto'
    from therion.context.conversation_frame import app_close_request
    if app_close_request(phrase):
        return 'fechar aplicativo'
    state = task_state_request(phrase)
    if state:
        return 'concluir tarefa' if state['state'] == 'completed' else 'reabrir tarefa'
    intent = IntentRecognizer().parse(phrase)
    return intent.action if intent else 'conversa'


@pytest.mark.parametrize('phrase,expected', list(cases()))
def test_real_phrase_routes_as_expected(phrase, expected):
    assert route(phrase) == expected
