"""Modo foco: frases, estado salvo, texto do fim e ofertas. Relógio sempre injetado."""
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from therion.core import focus
from therion.core.focus import FocusState, FocusStore, answer, ended_text, end_at, focus_request, offer, remaining

NOW = datetime(2026, 11, 18, 14, 50)


@pytest.fixture
def box(tmp_path, monkeypatch):
    shared = FocusStore(tmp_path / 'foco.json')
    monkeypatch.setattr(focus, 'store', lambda: shared)
    monkeypatch.setattr(focus, '_config_minutes', lambda key, default, low, high: default)
    return shared


@pytest.fixture
def host():
    return SimpleNamespace(desktop_timers=True)


@pytest.mark.parametrize('phrase, expected', [
    ('foco', ('start', None)),
    ('modo foco', ('start', None)),
    ('ativa o modo foco', ('start', None)),
    ('Therion, ativa o modo foco.', ('start', None)),
    ('foco 50 minutos', ('start', 50)),
    ('foco de 1 hora', ('start', 60)),
    ('foco de uma hora e meia', ('start', 90)),
    ('foco de duas horas', ('start', 120)),
    ('foco de meia hora', ('start', 30)),
    ('vou focar 30 minutos', ('start', 30)),
    ('vou focar trinta minutos', ('start', 30)),
    ('quero focar', ('start', None)),
    ('começa um foco', ('start', None)),
    ('foco 200 minutos', ('start', 200)),
    ('mais 10 minutos', ('extend', 10)),
    ('estica o foco em 15 minutos', ('extend', 15)),
    ('sai do foco', ('stop',)),
    ('para o foco', ('stop',)),
    ('cancela o foco', ('stop',)),
    ('chega de foco', ('stop',)),
    ('quanto falta do foco?', ('left',)),
    ('quanto falta?', ('left',)),
    ('pausa de 10 minutos', ('pause', 10)),
    ('faz uma pausa', ('pause', None)),
    ('sai da pausa', ('stop_pause',)),
])
def test_focus_request(phrase, expected):
    assert focus_request(phrase) == expected


@pytest.mark.parametrize('phrase', ['pausa', 'o foco da câmera está errado', 'me lembra de focar', 'mais café', 'quanto custa', 'abre o foco'])
def test_not_focus_phrases(phrase):
    assert focus_request(phrase) is None


def test_start_default_answer_and_saved_state(box, host):
    text, payload = answer('foco', host, NOW)
    assert text == 'Foco de 50 minutos, até as 15h40. Seguro meus avisos até lá; seus lembretes continuam valendo.'
    assert payload == {'phase': 'focus', 'minutes': 50, 'start': '2026-11-18T14:50:00', 'ended': False}
    saved = box.state()
    assert (saved.phase, saved.start, saved.minutes, saved.held) == ('focus', NOW, 50, [])


def test_start_spoken_duration(box, host):
    text, payload = answer('foco de uma hora e meia', host, NOW)
    assert payload['minutes'] == 90 and text.startswith('Foco de 1 hora e 30 minutos, até as 16h20.')


def test_start_limits(box, host):
    for phrase in ('foco 200 minutos', 'foco 3 minutos'):
        assert answer(phrase, host, NOW) == ('Dá para focar de 5 a 180 minutos.', None)
    assert box.state().phase == 'off'


def test_start_uses_configured_default(box, host, monkeypatch):
    monkeypatch.setattr(focus, '_config_minutes', lambda key, default, low, high: 25 if key == 'minutes' else default)
    assert answer('foco', host, NOW)[1]['minutes'] == 25


def test_already_in_focus_and_how_much_is_left(box, host):
    answer('foco', host, NOW)
    later = NOW + timedelta(minutes=18)
    assert answer('foco', host, later) == ('Você já está em foco; faltam 32 minutos.', None)
    assert answer('quanto falta do foco?', host, later) == ('Faltam 32 minutos de foco.', None)
    assert answer('quanto falta', host, NOW + timedelta(minutes=49, seconds=10))[0] == 'Falta 1 minuto de foco.'


def test_extend_respects_the_limit(box, host):
    answer('foco', host, NOW)
    text, payload = answer('mais 10 minutos', host, NOW + timedelta(minutes=5))
    assert text == 'Mais 10 minutos de foco, até as 15h50.' and payload['minutes'] == 60 and payload['start'] == '2026-11-18T14:50:00'
    assert box.state().minutes == 60
    text, payload = answer('mais três horas', host, NOW + timedelta(minutes=6))
    assert payload['minutes'] == 180 and text.startswith('O máximo é 180 minutos de foco')
    assert answer('mais 10 minutos', host, NOW + timedelta(minutes=7)) == ('O foco já está no máximo de 180 minutos.', None)


def test_extend_and_bare_left_are_not_ours_without_a_focus(box, host):
    assert answer('mais 10 minutos', host, NOW) is None
    assert answer('quanto falta', host, NOW) is None
    assert answer('quanto falta do foco', host, NOW) == ('Você não está em foco.', None)


def test_stop_counts_real_time_and_clears_held(box, host):
    answer('foco', host, NOW)
    box.save(FocusState('focus', NOW, 50, ['o disco C ficou com 3 GB']))
    text, payload = answer('sai do foco', host, NOW + timedelta(minutes=30, seconds=50))
    assert text == 'Foco encerrado.'          # o resumo (com e-mails e pausa) quem fala é a janela, uma vez só
    assert payload == {'phase': 'off', 'minutes': 30, 'start': '2026-11-18T14:50:00', 'ended': True,
                       'held': ['o disco C ficou com 3 GB']}
    assert box.state().phase == 'off' and box.state().held == []
    assert box.today(NOW.date()) == 30


def test_stop_without_focus_or_right_away(box, host):
    assert answer('sai do foco', host, NOW) == ('Você não está em foco.', None)
    answer('foco', host, NOW)
    assert answer('sai do foco', host, NOW + timedelta(seconds=20))[0] == 'Foco encerrado.'
    assert box.today(NOW.date()) == 0


def test_pause_by_phrase_and_end_of_pause(box, host):
    text, payload = answer('pausa de 10 minutos', host, NOW)
    assert text == 'Pausa de 10 minutos, até as 15h.' and payload['phase'] == 'pause' and payload['minutes'] == 10
    assert answer('quanto falta', host, NOW + timedelta(minutes=4))[0] == 'Faltam 6 minutos de pausa.'
    assert answer('faz uma pausa', host, NOW + timedelta(minutes=4)) == ('Você já está em pausa; faltam 6 minutos.', None)
    text, payload = answer('sai da pausa', host, NOW + timedelta(minutes=5))
    assert text == 'Pausa encerrada.' and payload['phase'] == 'off'
    assert box.today(NOW.date()) == 0                     # pausa não conta
    assert answer('sai da pausa', host, NOW) == ('Você não está em pausa.', None)


def test_pause_during_focus_and_limits(box, host):
    assert answer('pausa de 90 minutos', host, NOW) == ('Dá para fazer pausas de 1 a 60 minutos.', None)
    answer('foco', host, NOW)
    assert answer('pausa de 10 minutos', host, NOW + timedelta(minutes=18)) == ('Você está em foco; faltam 32 minutos.', None)


def test_terminal_has_no_state(box, host):
    host.desktop_timers = False
    assert answer('foco', host, NOW) == ('Lembretes e foco funcionam com a janela do Therion aberta.', None)
    assert box.state().phase == 'off'
    assert answer('bom dia', host, NOW) is None


def test_ended_text_all_parts():
    text = ended_text(50, 100, {'count': 6, 'important': [('Fulano', 'Prova'), ('Sicrano', 'Entrega')]},
                      ['o disco C ficou com 3 GB', 'a reunião das 15h começou'], 10)
    assert text == ('Foco de 50 minutos concluído. Hoje são 1 hora e 40 de foco. '
                    'Chegaram 6 e-mails, 2 importantes: Fulano, sobre Prova; Sicrano, sobre Entrega. '
                    'Enquanto você focava: o disco C ficou com 3 GB; a reunião das 15h começou. '
                    'Que tal 10 minutos de pausa?')


@pytest.mark.parametrize('total, spoken', [(100, '1 hora e 40'), (60, '1 hora'), (120, '2 horas'), (45, '45 minutos'), (61, '1 hora e 1')])
def test_ended_text_hours_format(total, spoken):
    assert ended_text(50, total, None, [], None) == f'Foco de 50 minutos concluído. Hoje são {spoken} de foco.'


def test_ended_text_mail_variants():
    base = 'Foco de 50 minutos concluído. Hoje são 50 minutos de foco.'
    assert ended_text(50, 50, None, [], None) == base
    assert ended_text(50, 50, {'count': 0, 'important': []}, [], None) == base + ' Nenhum e-mail novo.'
    assert ended_text(50, 50, {'error': True}, [], None) == base + ' Não consegui contar os e-mails agora.'
    assert ended_text(50, 50, {'count': 4, 'important': []}, [], None) == base + ' Chegaram 4 e-mails.'
    assert ended_text(50, 50, {'count': 1, 'important': [('Fulano', '')]}, [], None) == base + ' Chegou 1 e-mail, importante: Fulano.'
    assert ended_text(50, 50, {'count': 9, 'important': [('A', 'x'), ('B', 'y'), ('C', 'z')]}, [], None).endswith(
        'Chegaram 9 e-mails, 3 importantes: A, sobre x; B, sobre y; C, sobre z.')
    five = {'count': 9, 'important_count': 5, 'important': [('A', 'x'), ('B', 'y'), ('C', 'z')]}
    assert ended_text(50, 50, five, [], None).endswith('Chegaram 9 e-mails, 5 importantes: A, sobre x; B, sobre y; C, sobre z.')


def test_ended_text_many_held_warnings():
    held = ['Aviso um.', 'Aviso dois', 'Aviso três', 'Aviso quatro', 'Aviso cinco']
    assert ended_text(50, 50, None, held, None).endswith('Enquanto você focava: aviso um; aviso dois; aviso três e mais 2 avisos.')
    assert ended_text(50, 50, None, held[:4], None).endswith('aviso três e mais 1 aviso.')


def test_ended_text_suggested_pause_only_when_given():
    assert 'pausa' not in ended_text(50, 50, None, [], None)
    assert ended_text(50, 50, None, [], 1).endswith('Que tal 1 minuto de pausa?')


def test_offer_pause_yes_and_no(box, host):
    offer(host, 'pause')
    text, payload = answer('Sim, pode.', host, NOW)
    assert text == 'Pausa de 10 minutos, até as 15h.' and payload['phase'] == 'pause'
    assert host._focus_offer is None
    offer(host, 'pause')
    assert answer('não', host, NOW) == ('Tudo bem.', None)
    assert box.state().phase == 'pause'


def test_offer_again_uses_last_focus_length(box, host):
    answer('foco 30 minutos', host, NOW)
    answer('pausa de 5 minutos', host, NOW + timedelta(minutes=30))
    offer(host, 'again')
    text, payload = answer('sim', host, NOW + timedelta(minutes=36))
    assert payload['phase'] == 'focus' and payload['minutes'] == 30 and text.startswith('Foco de 30 minutos')


def test_offer_goes_away_with_another_phrase_or_time(box, host):
    offer(host, 'pause')
    assert answer('que horas são', host, NOW) is None
    assert host._focus_offer is None and answer('sim', host, NOW) is None
    offer(host, 'pause')
    host._focus_offer = (time.monotonic() - 1, 'pause')            # passou dos 120 s
    assert answer('sim', host, NOW) is None
    assert focus.wanted('sim', host) is False


def test_offer_is_the_only_owner_of_yes(box, host):
    host._pc_cleanup_offer = time.monotonic() + 100
    host._reminder_pending = (time.monotonic() + 100, 'cancel_all', ('r-1',))
    offer(host, 'pause')
    assert host._pc_cleanup_offer is None and host._reminder_pending is None
    assert host._focus_offer[1] == 'pause' and 110 < host._focus_offer[0] - time.monotonic() <= 120
    assert focus.wanted('sim', host) is True


def test_wanted_is_side_effect_free(box, host):
    offer(host, 'pause')
    assert focus.wanted('sim', host) and focus.wanted('sim', host) and host._focus_offer is not None
    assert focus.wanted('foco', host)
    assert not focus.wanted('mais 10 minutos', host)                 # sem foco ligado não é nossa
    answer('foco', host, datetime.now())                              # wanted() usa o relógio de verdade
    assert focus.wanted('mais 10 minutos', host)


def test_history_adds_up_and_cuts_after_30_days(box):
    today = date(2026, 11, 18)
    box.add_minutes(today - timedelta(days=31), 40)
    box.add_minutes(today - timedelta(days=30), 20)
    box.add_minutes(today, 50)
    box.add_minutes(today, 50)
    assert box.today(today) == 100
    days = json.loads(box.path.read_text(encoding='utf-8'))['days']
    assert sorted(days) == ['2026-10-19', '2026-11-18']


def test_store_roundtrip_and_remaining(box):
    state = FocusState('focus', NOW, 50, ['aviso'])
    box.save(state)
    assert FocusStore(box.path).state() == state
    assert end_at(state) == datetime(2026, 11, 18, 15, 40)
    assert remaining(state, NOW + timedelta(minutes=18)) == 32 * 60
    assert remaining(state, NOW + timedelta(hours=2)) == 0
    assert remaining(FocusState('off', None, 0, []), NOW) == 0


def test_store_survives_a_broken_file(box):
    box.path.write_text('{ não é json', encoding='utf-8')
    assert box.state() == FocusState('off', None, 0, [])
    assert box.today(NOW.date()) == 0
    assert list(box.path.parent.glob('foco.json.bad-*'))
    box.add_minutes(NOW.date(), 10)
    assert box.today(NOW.date()) == 10


def test_config_values_are_range_checked(monkeypatch):
    import therion.config.local as local
    monkeypatch.setattr(local, 'load_config', lambda: {'focus': {'minutes': 200, 'pause': 'x'}})
    assert focus._config_minutes('minutes', 50, 5, 180) == 50
    assert focus._config_minutes('pause', 10, 1, 60) == 10
    monkeypatch.setattr(local, 'load_config', lambda: {'focus': {'minutes': 25, 'pause': 15}})
    assert focus._config_minutes('minutes', 50, 5, 180) == 25
    assert focus._config_minutes('pause', 10, 1, 60) == 15
    monkeypatch.setattr(local, 'load_config', lambda: {})
    assert focus._config_minutes('minutes', 50, 5, 180) == 50


def test_update_reads_and_writes_under_one_lock(box):
    box.save(FocusState('focus', NOW, 50, []))
    before, after = box.update(lambda state: replace(state, held=[*state.held, 'aviso']))
    assert before.held == [] and after.held == ['aviso'] and box.state().held == ['aviso']
    assert box.last_minutes() == 50


def test_settle_ends_only_what_ran_out_and_credits_the_focus(box):
    box.save(FocusState('focus', NOW, 50, ['aviso']))
    assert focus.settle(NOW + timedelta(minutes=49)) is None and box.state().phase == 'focus'
    ended = focus.settle(NOW + timedelta(minutes=50))
    assert ended == FocusState('focus', NOW, 50, ['aviso']) and box.state().phase == 'off'
    assert box.today(NOW.date()) == 50
    assert focus.settle(NOW + timedelta(minutes=51)) is None and box.today(NOW.date()) == 50   # uma vez só
    box.save(FocusState('pause', NOW, 10, []))
    assert focus.settle(NOW + timedelta(minutes=10)).phase == 'pause' and box.today(NOW.date()) == 50


def test_pause_and_closed_texts():
    assert focus.pause_ended_text(50) == 'Pausa acabou. Mais 50 minutos de foco?'
    assert focus.closed_text(datetime(2026, 11, 18, 15, 40), 100) == (
        'Seu foco terminou às 15h40 enquanto eu estava fechado. Hoje são 1 hora e 40 de foco.')
    assert focus.closed_text(datetime(2026, 11, 18, 1, 5), None) == 'Seu foco terminou à 1h05 enquanto eu estava fechado.'


# --- e-mails do foco (caixa falsa) --------------------------------------------------------------------------
class FakeAdapter:
    def __init__(self, box):
        self.box = box

    def search(self, query, page=None, limit=None):
        self.box.queries.append((query, page, limit))
        if self.box.hang is not None:
            self.box.hang.wait(11)
        ids = self.box.important if 'is:important' in query else self.box.ids
        if page is None and len(ids) > 4 and limit == 500:      # duas páginas para a contagem
            return {'messages': [{'id': i} for i in ids[:4]], 'next_page': 'p2'}
        return {'messages': [{'id': i} for i in (ids[4:] if page else ids)], 'next_page': None}

    def metadata(self, identifier):
        who, subject = self.box.headers[identifier]
        return {'id': identifier, 'payload': {'headers': [{'name': 'From', 'value': who}, {'name': 'Subject', 'value': subject}]}}


class FakeBox:
    def __init__(self, account='conta-teste', ids=(), important=(), headers=None, hang=None):
        self.account, self.ids, self.important = account, list(ids), list(important)
        self.headers, self.hang, self.queries, self.io_lock = headers or {}, hang, [], threading.Lock()

    def identity(self):
        return self.account

    def _check(self, account, token):
        token.check()

    @contextmanager
    def _adapter(self, account, token):
        yield FakeAdapter(self)


START = datetime(2026, 11, 18, 14, 50)


def test_focus_mail_counts_and_lists_three_important():
    from therion.agent.contracts import CancellationToken
    headers = {'a': ('Fulano <fulano@example.com>', 'Prova de cálculo'), 'b': ('sicrano@example.com', 'Entrega'),
               'c': ('Beltrano <b@example.com>', ''), 'd': ('Outro <o@example.com>', 'Quarto')}
    box = FakeBox(ids=['a', 'b', 'c', 'd', 'e', 'f'], important=['a', 'b', 'c', 'd'], headers=headers)
    mail = focus.focus_mail(SimpleNamespace(_mailbox=box), START, CancellationToken())
    assert mail == {'count': 6, 'important_count': 4,
                    'important': [('Fulano', 'Prova de cálculo'), ('sicrano@example.com', 'Entrega'), ('Beltrano', '')]}
    after = int(START.timestamp())
    assert ('in:inbox after:%d' % after, None, 500) in box.queries and ('in:inbox after:%d' % after, 'p2', 500) in box.queries
    assert (f'in:inbox is:important after:{after}', None, 500) in box.queries
    assert not box.io_lock.locked()


def test_focus_mail_without_account_is_none():
    from therion.agent.contracts import CancellationToken
    box = FakeBox(account=None)
    assert focus.focus_mail(SimpleNamespace(_mailbox=box), START, CancellationToken()) is None and box.queries == []


def test_focus_mail_timeout_is_error():
    from therion.agent.contracts import CancellationToken
    hang = threading.Event()
    box = FakeBox(ids=['a'], hang=hang)
    try:
        began = time.monotonic()
        assert focus.focus_mail(SimpleNamespace(_mailbox=box), START, CancellationToken(), timeout=0.2) == {'error': True}
        assert time.monotonic() - began < 2
    finally:
        hang.set()


def test_focus_mail_failure_is_error():
    from therion.agent.contracts import CancellationToken
    box = FakeBox(ids=['a'], important=['a'], headers={})       # metadata sem o id → KeyError
    assert focus.focus_mail(SimpleNamespace(_mailbox=box), START, CancellationToken()) == {'error': True}
    token = CancellationToken()
    token.cancel()
    assert focus.focus_mail(SimpleNamespace(_mailbox=FakeBox(ids=['a'])), START, token) == {'error': True}


def test_focus_mail_unexpected_adapter_error_is_error_without_traceback(monkeypatch):
    from therion.agent.contracts import CancellationToken
    hooked = []
    monkeypatch.setattr(threading, 'excepthook', hooked.append)
    box = FakeBox(ids=['a'])
    def broken(query, page=None, limit=None):
        raise AttributeError('adapter quebrado')
    monkeypatch.setattr(FakeAdapter, 'search', lambda self, query, page=None, limit=None: broken(query))
    assert focus.focus_mail(SimpleNamespace(_mailbox=box), START, CancellationToken()) == {'error': True}
    assert hooked == [] and not box.io_lock.locked()


def test_timer_look_shows_minutes_and_fraction():
    state = FocusState('focus', START, 50, [])
    look = focus.timer_look(state, START + timedelta(minutes=18, seconds=10))
    assert look == focus.TimerLook(fraction=pytest.approx((31*60+50)/3000), label='32', phase='focus', warn=False)
    assert focus.timer_look(state, START).label == '50' and focus.timer_look(state, START).fraction == 1


def test_timer_look_last_minute_shows_seconds():
    state = FocusState('focus', START, 50, [])
    assert focus.timer_look(state, end_at(state) - timedelta(seconds=44.2)).label == '45'
    assert focus.timer_look(state, end_at(state) - timedelta(seconds=61)).label == '2'
    assert focus.timer_look(state, end_at(state)) is None                  # zerou: nada a desenhar
    assert focus.timer_look(FocusState('off', None, 0, []), START) is None


def test_timer_look_warn_last_five_minutes():
    state = FocusState('focus', START, 50, [])
    assert not focus.timer_look(state, end_at(state) - timedelta(seconds=301)).warn
    assert focus.timer_look(state, end_at(state) - timedelta(seconds=300)).warn
    pause = FocusState('pause', START, 10, [])
    look = focus.timer_look(pause, end_at(pause) - timedelta(seconds=120))
    assert look.phase == 'pause' and not look.warn                        # a pausa não fica âmbar
