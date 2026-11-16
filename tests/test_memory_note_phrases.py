"""'Anota que…' usa o fluxo supervisionado de memória, não um caminho novo de escrita."""
import pytest

from therion.memory.commands import memory_request


@pytest.mark.parametrize('command,text', [
    ('Anota que o filtro da geladeira troca em março', 'o filtro da geladeira troca em março'),
    ('anote aí que a chave reserva está na gaveta.', 'a chave reserva está na gaveta'),
    ('Por favor, anota essa ideia: orbe com anel duplo', 'ideia: orbe com anel duplo'),
    ('anota uma ideia para o Prismion: tela dividida', 'ideia para o Prismion: tela dividida')])
def test_note_phrases_become_a_memory_candidate(command, text):
    assert memory_request(command) == {'operation': 'add', 'text': text}


def test_note_with_a_date_asks_whether_it_is_a_reminder():
    assert memory_request('anota que amanhã tem dentista') == {'operation': 'ambiguous'}
    assert memory_request('anota essa ideia') == {'operation': 'clarify'}


@pytest.mark.parametrize('command', ['anota comprar pão', 'anotações de ontem', 'não anota nada', 'anota a tarefa estudar'])
def test_other_phrases_keep_their_routes(command):
    assert memory_request(command) is None
