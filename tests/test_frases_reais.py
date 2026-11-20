"""Roteamento das frases reais em tests/frases_reais.txt; nenhuma frase que já falhou pode voltar a falhar."""
from pathlib import Path
import pytest

from therion.core.intent import IntentRecognizer
from therion.core.routes import fixed_route

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
    """Mesma ordem do orquestrador: regras fixas primeiro; o resto vai para a IA."""
    fixed = fixed_route(phrase, projects={})
    if fixed:
        return fixed
    intent = IntentRecognizer().parse(phrase)
    return intent.action if intent else 'conversa'


@pytest.mark.parametrize('phrase,expected', list(cases()))
def test_real_phrase_routes_as_expected(phrase, expected):
    assert route(phrase) == expected
