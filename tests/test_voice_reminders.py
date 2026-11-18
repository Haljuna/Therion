"""Frases de lembrete: entende quando e o quê, sem Qt e com relógio injetado."""
from datetime import datetime

import pytest

from therion.core.voice_reminders import Repeat, next_due, parse_reminder

NOW = datetime(2026, 11, 18, 14, 0)  # quarta
ALL = (0, 1, 2, 3, 4, 5, 6)
WEEK = (0, 1, 2, 3, 4)


@pytest.mark.parametrize('phrase, now, text, due', [
    ('me lembra de tirar a roupa da máquina em 40 minutos', NOW, 'tirar a roupa da máquina', datetime(2026, 11, 18, 14, 40)),
    ('me lembre às 18h de ligar pro João', NOW, 'ligar pro João', datetime(2026, 11, 18, 18, 0)),
    ('me avisa daqui a uma hora e meia para sair', NOW, 'sair', datetime(2026, 11, 18, 15, 30)),
    ('me lembra de beber água daqui a pouco', NOW, 'beber água', datetime(2026, 11, 18, 14, 10)),
    ('me lembra daqui a meia hora de ligar', NOW, 'ligar', datetime(2026, 11, 18, 14, 30)),
    ('me lembra em 1 hora e 15 de ligar', NOW, 'ligar', datetime(2026, 11, 18, 15, 15)),
    ('me lembra em duas horas de ligar', NOW, 'ligar', datetime(2026, 11, 18, 16, 0)),
    ('me lembra amanhã às 9 de levar o carregador', NOW, 'levar o carregador', datetime(2026, 11, 19, 9, 0)),
    ('me lembra às 6 de ligar', NOW, 'ligar', datetime(2026, 11, 18, 18, 0)),
    ('me lembra às 6 de ligar', datetime(2026, 11, 18, 23, 50), 'ligar', datetime(2026, 11, 19, 6, 0)),
    ('me lembra às 6 da manhã de ligar', NOW, 'ligar', datetime(2026, 11, 19, 6, 0)),
    ('me lembra às 13 de ligar', NOW, 'ligar', datetime(2026, 11, 19, 13, 0)),
    ('me lembra ao meio-dia de almoçar', NOW, 'almoçar', datetime(2026, 11, 19, 12, 0)),
    ('me lembra à meia-noite de dormir', NOW, 'dormir', datetime(2026, 11, 19, 0, 0)),
    ('lembrete: pagar o boleto sexta às 10', NOW, 'pagar o boleto', datetime(2026, 11, 20, 10, 0)),
    ('me lembra às dezoito horas de ligar', NOW, 'ligar', datetime(2026, 11, 18, 18, 0)),
    ('me lembra dia 25 às 8 de pagar', NOW, 'pagar', datetime(2026, 11, 25, 8, 0)),
    ('me lembra dia 10 às 8 de pagar', NOW, 'pagar', datetime(2026, 12, 10, 8, 0)),
    ('me lembra sexta que vem às 14h de pagar', NOW, 'pagar', datetime(2026, 11, 20, 14, 0)),
    ('Cria um lembrete às 18:30 para regar as plantas.', NOW, 'regar as plantas', datetime(2026, 11, 18, 18, 30)),
    ('lembra-me às 19h de estudar', NOW, 'estudar', datetime(2026, 11, 18, 19, 0)),
    ('me lembra que às 19h tem reunião', NOW, 'tem reunião', datetime(2026, 11, 18, 19, 0)),
])
def test_parses(phrase, now, text, due):
    parsed = parse_reminder(phrase, now)
    assert (parsed.kind, parsed.text, parsed.due, parsed.repeat) == ('create', text, due, None)


def test_missing_when_or_what():
    assert parse_reminder('me lembra de pagar o boleto', NOW).kind == 'need_when'
    assert parse_reminder('me lembra amanhã de pagar o boleto', NOW).kind == 'need_when'
    what = parse_reminder('me lembra em 10 minutos', NOW)
    assert (what.kind, what.text, what.due) == ('need_what', None, datetime(2026, 11, 18, 14, 10))


@pytest.mark.parametrize('phrase', ['me lembra que eu tenho prova amanhã', 'lembre que meu carro é prata',
                                    'anota que a senha mudou', 'que horas são', 'abre o navegador'])
def test_not_a_reminder(phrase):
    assert parse_reminder(phrase, NOW) is None


def test_invalid_time_and_length():
    bad = parse_reminder('me lembra às dez seis de sair', NOW)
    assert bad.kind == 'invalid' and 'ambíguo' in bad.question
    long = parse_reminder('me lembra de ' + 'x' * 201 + ' em 5 minutos', NOW)
    assert (long.kind, long.question) == ('invalid', 'O lembrete pode ter até 200 caracteres.')
    assert parse_reminder('me lembra de ' + 'x' * 200 + ' em 5 minutos', NOW).kind == 'create'
    assert parse_reminder('me lembra hoje às 8 da manhã de ligar', NOW).kind == 'invalid'


@pytest.mark.parametrize('phrase, days, time', [
    ('me lembra todo dia às 8h de tomar remédio', ALL, '08:00'),
    ('me lembra todos os dias às 20h de tomar remédio', ALL, '20:00'),
    ('me lembra toda segunda e quarta às 19h de treinar', (0, 2), '19:00'),
    ('me lembra às terças e quintas às 19h de treinar', (1, 3), '19:00'),
    ('me lembra nos dias úteis às 9h de abrir o ponto', WEEK, '09:00'),
    ('me lembra de segunda a sexta às 9h de abrir o ponto', WEEK, '09:00'),
    ('me lembra fim de semana às 10h de passear', (5, 6), '10:00'),
    ('me lembra todo dia às 6 da manhã de acordar', ALL, '06:00'),
])
def test_repeats(phrase, days, time):
    parsed = parse_reminder(phrase, NOW)
    assert parsed.kind == 'create' and parsed.repeat == Repeat(days, time)
    assert parsed.due == next_due(parsed.repeat, NOW) and parsed.text


def test_repeat_first_due_and_text():
    parsed = parse_reminder('me lembra todo dia às 8h de tomar remédio', NOW)
    assert (parsed.text, parsed.due) == ('tomar remédio', datetime(2026, 11, 19, 8, 0))


def test_repeat_needs_when_or_period():
    assert parse_reminder('me lembra todo dia de tomar remédio', NOW).kind == 'need_when'
    ask = parse_reminder('me lembra todo dia às 6 de tomar remédio', NOW)
    assert (ask.kind, ask.text, ask.repeat.days, ask.hour) == ('need_period', 'tomar remédio', ALL, 6)
    assert parse_reminder('me lembra todo dia às 12 de almoçar', NOW).kind == 'create'
    assert parse_reminder('me lembra todo dia ao meio-dia de almoçar', NOW).repeat.time == '12:00'
    assert parse_reminder('me lembra todo dia às 18 de jantar', NOW).repeat.time == '18:00'


def test_next_due():
    daily = Repeat(ALL, '08:00')
    assert next_due(daily, datetime(2026, 11, 18, 23, 59)) == datetime(2026, 11, 19, 8, 0)
    assert next_due(daily, datetime(2026, 11, 18, 8, 0)) == datetime(2026, 11, 19, 8, 0)
    assert next_due(daily, datetime(2026, 11, 18, 7, 59)) == datetime(2026, 11, 18, 8, 0)
    assert next_due(Repeat((0,), '09:00'), NOW) == datetime(2026, 11, 23, 9, 0)
    assert next_due(Repeat((2,), '09:00'), NOW) == datetime(2026, 11, 25, 9, 0)
    assert next_due(daily, datetime(2026, 11, 30, 9, 0)) == datetime(2026, 12, 1, 8, 0)
