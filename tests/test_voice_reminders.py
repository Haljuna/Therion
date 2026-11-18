"""Frases de lembrete: entende quando e o quê, sem Qt e com relógio injetado."""
from datetime import date, datetime

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
    ('me lembra hoje às 6 de ligar', NOW, 'ligar', datetime(2026, 11, 18, 18, 0)),
    ('me lembra amanhã às 6 de ligar', NOW, 'ligar', datetime(2026, 11, 19, 6, 0)),
    ('me lembra à 1 da tarde de ligar', NOW, 'ligar', datetime(2026, 11, 19, 13, 0)),
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
    for phrase in ('me lembra de ligar a uma amiga', 'me lembra de dar comida a 2 gatos'):
        assert parse_reminder(phrase, NOW).kind == 'need_when'
    day = parse_reminder('me lembra amanhã de levar o carregador', NOW)
    assert (day.kind, day.text, day.day) == ('need_when', 'levar o carregador', date(2026, 11, 19))
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


# --- depósito -------------------------------------------------------------------------------------------------
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
from datetime import timedelta  # noqa: E402

from therion.core.voice_reminders import Reminder, ReminderStore, due_message, late_message  # noqa: E402

EVERY_DAY = Repeat(ALL, '08:00')


def _store(tmp_path):
    return ReminderStore(tmp_path / 'lembretes.json')


def test_roundtrip_and_atomic_write(tmp_path):
    store = _store(tmp_path)
    first = store.add('tirar a roupa da máquina', datetime(2026, 11, 18, 18, 0), None, NOW)
    second = store.add('tomar remédio', datetime(2026, 11, 19, 8, 0), EVERY_DAY, NOW)
    again = _store(tmp_path).items()
    assert again == [first, second]
    assert first.id.startswith('r-') and first.id != second.id
    assert not list(tmp_path.glob('*.tmp'))
    data = json.loads((tmp_path / 'lembretes.json').read_text(encoding='utf-8'))
    assert data['version'] == 1 and data['items'][1]['repeat'] == {'days': list(ALL), 'time': '08:00'}
    assert data['items'][0]['due'] == '2026-11-18T18:00:00' and data['items'][0]['repeat'] is None


def test_limit_50(tmp_path):
    store = _store(tmp_path)
    for n in range(50):
        store.add(f'item {n}', NOW + timedelta(hours=n + 1), None, NOW)
    with pytest.raises(ValueError, match='^Você já tem 50 lembretes; cancele algum antes.$'):
        store.add('mais um', NOW + timedelta(days=9), None, NOW)


def test_remove_and_next_time(tmp_path):
    store = _store(tmp_path)
    assert store.next_time() is None
    a = store.add('a', datetime(2026, 11, 18, 19, 0), None, NOW)
    b = store.add('b', datetime(2026, 11, 18, 18, 0), None, NOW)
    assert store.next_time() == b.due
    assert store.remove([b.id, 'r-nope']) == [b]
    assert store.items() == [a]


def test_take_due_on_time_removes_once_and_reschedules_repeat(tmp_path):
    store = _store(tmp_path)
    once = store.add('tirar a roupa da máquina', datetime(2026, 11, 18, 18, 0), None, NOW)
    store.add('tomar remédio', datetime(2026, 11, 19, 8, 0), EVERY_DAY, NOW)
    on_time, late, old = store.take_due(datetime(2026, 11, 18, 18, 0, 30))
    assert (on_time, late, old) == ([once], [], 0)
    assert [r.text for r in store.items()] == ['tomar remédio']
    assert store.items()[0].due == datetime(2026, 11, 19, 8, 0)
    assert store.take_due(datetime(2026, 11, 18, 18, 1)) == ([], [], 0)


def test_take_due_repeat_on_time_gets_next_date(tmp_path):
    store = _store(tmp_path)
    store.add('tomar remédio', datetime(2026, 11, 19, 8, 0), EVERY_DAY, NOW)
    on_time, late, old = store.take_due(datetime(2026, 11, 19, 8, 0, 10))
    assert [r.text for r in on_time] == ['tomar remédio'] and late == [] and old == 0
    assert store.items()[0].due == datetime(2026, 11, 20, 8, 0)


def test_sleep_three_hours(tmp_path):
    store = _store(tmp_path)
    store.add('tirar a roupa da máquina', datetime(2026, 11, 18, 18, 0), None, NOW)
    store.add('tomar remédio', datetime(2026, 11, 18, 8, 0), EVERY_DAY, datetime(2026, 11, 17, 9, 0))
    on_time, late, old = store.take_due(datetime(2026, 11, 18, 21, 0))
    assert on_time == [] and old == 0
    assert sorted(r.text for r in late) == ['tirar a roupa da máquina', 'tomar remédio']
    assert store.items()[0].due == datetime(2026, 11, 19, 8, 0) and len(store.items()) == 1


def test_week_closed_daily_said_once_old_counted(tmp_path):
    store = _store(tmp_path)
    now = datetime(2026, 11, 25, 9, 0)
    store.add('tomar remédio', datetime(2026, 11, 18, 8, 0), EVERY_DAY, datetime(2026, 11, 17, 9, 0))
    store.add('ligar para Fulano', datetime(2026, 11, 17, 10, 0), None, datetime(2026, 11, 16, 9, 0))
    on_time, late, old = store.take_due(now)
    assert on_time == [] and old == 1
    assert [r.text for r in late] == ['tomar remédio'] and late[0].due == datetime(2026, 11, 25, 8, 0)
    assert store.items()[0].due == datetime(2026, 11, 26, 8, 0)


def test_corrupt_file_is_kept_and_reported(tmp_path):
    path = tmp_path / 'lembretes.json'
    path.write_text('{x', encoding='utf-8')
    store = ReminderStore(path)
    assert store.items() == []
    bad = list(tmp_path.glob('lembretes.json.bad-*'))
    assert len(bad) == 1 and bad[0].read_text(encoding='utf-8') == '{x'
    assert store.broken_notice.startswith('Não consegui ler seus lembretes antigos')
    assert bad[0].name in store.broken_notice


def test_mtime_and_reload(tmp_path):
    store = _store(tmp_path)
    assert store.mtime() is None
    store.add('a', NOW + timedelta(hours=1), None, NOW)
    assert store.mtime() is not None
    other = _store(tmp_path)
    other.add('b', NOW + timedelta(hours=2), None, NOW)
    assert len(store.items()) == 1
    store.reload()
    assert len(store.items()) == 2


def _r(text, due):
    return Reminder('r-0000', text, due, None, NOW)


def test_messages():
    one = _r('tirar a roupa da máquina', datetime(2026, 11, 18, 18, 0))
    two = _r('ligar para Fulano', datetime(2026, 11, 18, 18, 0))
    assert due_message([one]) == 'Lembrete: tirar a roupa da máquina.'
    assert due_message([one, two]) == 'Dois lembretes: tirar a roupa da máquina; ligar para Fulano.'
    assert late_message([], 0) is None
    assert late_message([one], 0) == 'Enquanto eu estava fechado, passou da hora de: tirar a roupa da máquina (18:00).'
    four = [_r(f'item {n}', datetime(2026, 11, 18, 18, n)) for n in range(4)]
    assert late_message(four, 0) == 'Passaram 4 lembretes enquanto eu estava fechado: item 0, item 1, item 2 e mais 1.'
    assert late_message([one], 2) == ('Enquanto eu estava fechado, passou da hora de: tirar a roupa da máquina (18:00) e mais 2 antigos.')


def test_invalid_utf8_is_quarantined(tmp_path):
    path = tmp_path / 'lembretes.json'
    path.write_bytes(bytes([0xff, 0xfe, 0x7b]))
    store = ReminderStore(path)
    assert store.items() == [] and store.broken_notice
    assert len(list(tmp_path.glob('lembretes.json.bad-*'))) == 1


def test_transient_read_error_does_not_quarantine(tmp_path, monkeypatch):
    first = _store(tmp_path)
    kept = first.add('a', NOW + timedelta(hours=1), None, NOW)
    real = Path.read_bytes

    def locked(self):
        raise PermissionError('em uso')
    monkeypatch.setattr(Path, 'read_bytes', locked)
    store = ReminderStore(tmp_path / 'lembretes.json')
    assert store.items() == [] and store.broken_notice is None
    assert not list(tmp_path.glob('lembretes.json.bad-*'))
    monkeypatch.setattr(Path, 'read_bytes', real)
    store.reload()
    assert store.items() == [kept]


def _failing_replace(monkeypatch):
    def boom(*args):
        raise OSError('disco cheio')
    monkeypatch.setattr(os, 'replace', boom)


def test_add_and_remove_keep_memory_when_write_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)
    kept = store.add('a', NOW + timedelta(hours=1), None, NOW)
    _failing_replace(monkeypatch)
    with pytest.raises(OSError):
        store.add('b', NOW + timedelta(hours=2), None, NOW)
    with pytest.raises(OSError):
        store.remove([kept.id])
    assert store.items() == [kept]
    assert not list(tmp_path.glob('*.tmp'))


def test_take_due_speaks_even_when_write_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)
    once = store.add('a', datetime(2026, 11, 18, 18, 0), None, NOW)
    _failing_replace(monkeypatch)
    assert store.take_due(datetime(2026, 11, 18, 18, 0, 5)) == ([once], [], 0)
    assert store.take_due(datetime(2026, 11, 18, 18, 0, 10)) == ([], [], 0)


def test_late_sorted_and_plural_forms():
    a = _r('a', datetime(2026, 11, 18, 9, 0))
    b = _r('b', datetime(2026, 11, 18, 8, 0))
    assert late_message([a], 1) == 'Enquanto eu estava fechado, passou da hora de: a (09:00) e mais 1 antigo.'
    assert late_message([], 1) == 'Passou 1 lembrete antigo enquanto eu estava fechado.'
    assert late_message([], 3) == 'Passaram 3 lembretes antigos enquanto eu estava fechado.'


def test_take_due_late_sorted(tmp_path):
    store = _store(tmp_path)
    store.add('tarde', datetime(2026, 11, 18, 9, 0), None, NOW)
    store.add('cedo', datetime(2026, 11, 18, 8, 0), EVERY_DAY, NOW)
    late = store.take_due(datetime(2026, 11, 18, 12, 0))[1]
    assert [r.text for r in late] == ['cedo', 'tarde']
