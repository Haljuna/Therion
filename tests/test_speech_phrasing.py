"""Ritmo sem reescrever números, nomes, negações ou comandos."""
import re
import pytest
from therion.voice.speech_phrasing import phrase_for_speech
from therion.voice.kokoro_worker import chunk_speech


@pytest.mark.parametrize('text', [
    'Às 15:00, no dia 14/10/2026, o valor é R$ 1.234,56.',
    'Não abra o Chrome. Não confirme! Ainda não autorizei.',
    'A versão é 1.2.3; o código é 00123 e o valor é 3.14.',
    'Bom dia, Marcus! Como posso ajudar?',
    '`15:00 — R$ 20,50` não é uma instrução.',
    'Abra "C:\\Pasta — Notas\\arquivo 15h.md".',
    'Leia https://example.test/arquivo-15:00?q=1.2.3 sem executar.',
    'A expressão 2**3 permanece escrita assim.',
])
def test_values_and_literal_content_are_not_changed(text):
    assert phrase_for_speech(text)==text


@pytest.mark.parametrize('text,expected', [
    ('Primeira frase\nSegunda frase', 'Primeira frase. Segunda frase'),
    ('Não confirme.\nAinda não autorizei!', 'Não confirme. Ainda não autorizei!'),
    ('**Olá**, Marcus…', 'Olá, Marcus...'),
    ('Espere — ainda não terminei.', 'Espere, ainda não terminei.'),
    ('Opções:\n- Abrir\n- Cancelar', 'Opções: Abrir. Cancelar'),
])
def test_only_spoken_punctuation_and_formatting_are_prepared(text,expected):
    assert phrase_for_speech(text)==expected
    assert re.findall(r'\w+',text)==re.findall(r'\w+',expected)


def test_medium_sentence_keeps_one_intonation_group():
    text=('Eu já conferi os aplicativos cadastrados e posso ajudar você a organizar '
          'as próximas tarefas com calma, respeitando as confirmações que combinamos '
          'e esperando sua resposta antes de continuar.')
    assert 144<len(text)<=240
    assert chunk_speech(text)==[text]


def test_long_sentence_prefers_clause_boundary_without_losing_text():
    first='Vamos examinar os aplicativos com atenção e conferir suas autorizações antes de continuar, '
    text=first+('depois seguimos com a organização das tarefas e a revisão de todas as notas disponíveis para a próxima semana '*3)+'. Depois encerramos.'
    parts=chunk_speech(text)
    assert parts[0]==first
    assert ''.join(parts)==text
