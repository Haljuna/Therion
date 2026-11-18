"""A janela no modo foco: segura avisos, resume no fim com e-mails, oferece pausa e retoma ao reabrir."""
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from therion.core import focus, voice_reminders
from therion.core.focus import FocusState, FocusStore, ended_text
from therion.core.orchestrator import OrchestrationResult
from therion.core.voice_reminders import ReminderStore, _clock
from therion.interface import reminders
from tests.test_reminders import close, make_window

MAIL = {'count': 6, 'important_count': 2, 'important': [('Fulano', 'Prova de cálculo')]}


@pytest.fixture
def shared(tmp_path, monkeypatch):
    store = FocusStore(tmp_path / 'foco.json')
    monkeypatch.setattr(focus, 'store', lambda: store)
    monkeypatch.setattr(focus, '_config_minutes', lambda key, default, low, high: default)
    reminder_store = ReminderStore(tmp_path / 'lembretes.json')
    monkeypatch.setattr(voice_reminders, 'store', lambda: reminder_store)
    store.reminders = reminder_store
    mail = []
    monkeypatch.setattr(focus, 'focus_mail', lambda host, start, token, timeout=10.: mail.append(start) or MAIL)
    store.mail_calls = mail
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    return store


def quiet_window(app, tmp_path, monkeypatch):
    win = make_window(app, tmp_path, monkeypatch, True)
    win._speech_output = MagicMock()
    said = []
    monkeypatch.setattr(win, '_append', lambda sender, text: said.append(text))
    win.said = said
    return win


@pytest.fixture
def window(app, tmp_path, monkeypatch, shared):
    win = quiet_window(app, tmp_path, monkeypatch)
    app.processEvents()                              # o singleShot(0) do __init__
    yield win
    win._speech_output = None
    win._processing = False
    win._game_forced = False
    close(app, win)


def spoken(win):
    return [call.args[0] for call in win._speech_output.speak.call_args_list]


def settle_mail(app, win):
    """Espera a thread dos e-mails e entrega o resultado na thread do Qt."""
    thread = win._focus_mail_thread
    if thread is not None:
        thread.join(5)
    app.processEvents()


def start_focus(win, shared, start, minutes=50, held=()):
    state = FocusState('focus', start, minutes, list(held))
    shared.save(state)
    win._apply_focus(focus._payload(state))
    return state


def watch_stub(win):
    win._pc_watch = SimpleNamespace(in_game=False, game=lambda on: None, poll=lambda: [], tight=lambda: False)
    win._pc_watch_ticks = 1                          # não mede de verdade neste tique


def test_watch_and_event_warnings_held_during_focus_reminder_not(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    start_focus(window, shared, now - timedelta(minutes=10))
    watch_stub(window)
    window._pc_watch_said.append(('O disco C ficou com 3 GB.', False))
    window._reminders = MagicMock()
    window._reminders.due.return_value = ['A reunião das 15h começou.']
    window._poll_reminders()
    window._pc_watch_said.append(('O disco C ficou com 3 GB.', False))     # repetido: não duplica
    window._reminders.due.return_value = []
    window._poll_reminders()
    window._orchestrator.ai_core = MagicMock()
    window._poll_game_mode(True)
    window._poll_game_mode(True)                     # o modo jogo automático também espera o foco
    window._game_thread.join(5)
    assert window.said == [] and spoken(window) == []
    assert shared.state().held == ['O disco C ficou com 3 GB.', 'A reunião das 15h começou.',
                                   'Modo jogo: liberei a placa de vídeo. Meu primeiro pedido depois disso demora um pouco mais.']
    shared.reminders.add('tirar a roupa da máquina', now, None, now - timedelta(hours=1))
    window._fire_reminders(now)                      # o lembrete fura o foco
    assert window.said == ['Lembrete: tirar a roupa da máquina.'] and spoken(window) == ['Lembrete: tirar a roupa da máquina.']


def test_warnings_are_not_held_without_focus(window, shared):
    watch_stub(window)
    window._pc_watch_said.append(('O disco C ficou com 3 GB.', False))
    window._poll_reminders()
    assert window.said == ['O disco C ficou com 3 GB.'] and shared.state().held == []


def test_cleanup_offer_not_rearmed_when_held(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    start = now - timedelta(minutes=10)
    start_focus(window, shared, start)
    watch_stub(window)
    window._orchestrator._pc_cleanup_offer = None
    window._pc_watch_said.append(('O disco C está quase cheio; quer que eu libere espaço?', True))
    window._poll_reminders()
    assert window._orchestrator._pc_cleanup_offer is None
    shared.save(FocusState('focus', start, 10, shared.state().held))      # o foco acaba agora
    window._focus_due(now)
    settle_mail(app, window)
    assert window._orchestrator._pc_cleanup_offer is None and window._orchestrator._focus_offer[1] == 'pause'
    result = window._orchestrator.process_command('sim')
    assert result.ui_action == 'focus' and result.ui_payload['phase'] == 'pause'   # o "sim" é da pausa


@pytest.mark.parametrize('quiet', [False, True])
def test_focus_end_speaks_summary_and_offers_pause(app, window, shared, monkeypatch, quiet):
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: quiet)
    window._game_forced = quiet
    now = datetime.now().replace(microsecond=0)
    held = ['O disco C ficou com 3 GB.', 'A reunião das 15h começou.']
    start = now - timedelta(minutes=50)
    shared.save(FocusState('focus', start, 50, held))
    window._focus_due(now)
    settle_mail(app, window)
    expected = ended_text(50, 50, MAIL, held, 10)
    assert spoken(window) == [expected]
    assert expected in window.said and any(all(item in text for item in held) for text in window.said if text != expected)
    assert window._orchestrator._focus_offer[1] == 'pause' and shared.mail_calls == [start]
    assert shared.state().phase == 'off' and shared.today(now.date()) == 50 and window._focus_view is None


def test_focus_end_while_busy_waits_but_orb_leaves_focus_on_time(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    start_focus(window, shared, now - timedelta(minutes=50) + timedelta(seconds=1))
    assert window._focus_view['phase'] == 'focus' and window._focus_shot.isActive()
    window._processing = True
    deadline = time.monotonic() + 5
    while window._focus_view is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert window._focus_view is None and shared.state().phase == 'off'   # a orbe sai do foco na hora
    settle_mail(app, window)
    assert spoken(window) == []
    window._processing = False
    window._drain_speech()
    assert spoken(window) == [ended_text(50, 50, MAIL, [], 10)]


class TimerOrb:
    def __init__(self):
        self.looks = []

    def set_timer(self, look):
        self.looks.append(look)


def test_both_orbs_get_the_timer_every_second_only_during_focus(app, window, shared):
    mini, big = TimerOrb(), TimerOrb()
    window._mini_orb = mini
    window._dashboard = SimpleNamespace(constellation=big)
    try:
        assert not window._timer_tick.isActive()
        now = datetime.now().replace(microsecond=0)
        start_focus(window, shared, now - timedelta(minutes=18))
        assert window._timer_tick.isActive() and window._timer_tick.interval() == 1000
        look = mini.looks[-1]
        assert big.looks[-1] == look and look.phase == 'focus' and look.label == '32' and not look.warn
        window._timer_tick.timeout.emit()
        assert len(mini.looks) == len(big.looks) == 2
        window._apply_focus({'phase': 'pause', 'minutes': 10, 'start': now.isoformat()})
        assert window._timer_tick.isActive() and mini.looks[-1].phase == 'pause'
        window._apply_focus({'phase': 'off', 'minutes': 0, 'start': None})
        assert not window._timer_tick.isActive() and mini.looks[-1] is None and big.looks[-1] is None
    finally:
        window._mini_orb = None
        window._dashboard = None


def test_the_timer_leaves_the_orbs_when_the_focus_ends(app, window, shared):
    mini = TimerOrb()
    window._mini_orb = mini
    try:
        now = datetime.now().replace(microsecond=0)
        start_focus(window, shared, now - timedelta(minutes=49, seconds=30))
        assert mini.looks[-1].label in ('30', '31') and mini.looks[-1].warn
        window._focus_due(now + timedelta(seconds=31))
        assert mini.looks[-1] is None and not window._timer_tick.isActive()
        settle_mail(app, window)
    finally:
        window._mini_orb = None


def test_pause_end_offers_again(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    shared.save(FocusState('focus', now - timedelta(minutes=60), 50, []))   # o último foco foi de 50
    shared.save(FocusState('pause', now - timedelta(minutes=10), 10, []))
    window._focus_due(now)
    assert spoken(window) == ['Pausa acabou. Mais 50 minutos de foco?'] and window.said == spoken(window)
    assert window._orchestrator._focus_offer[1] == 'again' and shared.today(now.date()) == 0
    assert shared.mail_calls == []


def test_reopen_during_focus_resumes(app, tmp_path, monkeypatch, shared):
    shared.save(FocusState('focus', datetime.now().replace(microsecond=0) - timedelta(minutes=10), 50, ['aviso']))
    win = quiet_window(app, tmp_path, monkeypatch)
    try:
        app.processEvents()
        assert win._focus_view['phase'] == 'focus' and win._focus_shot.isActive()
        assert abs(win._focus_shot.remainingTime() - 40 * 60000) < 3000
        assert shared.state().held == ['aviso'] and win.said == []
    finally:
        win._speech_output = None
        close(app, win)


def test_reopen_after_end_says_it_ended_while_closed(app, tmp_path, monkeypatch, shared):
    end = datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=10)
    if end.date() != date.today():
        pytest.skip('virada do dia')
    shared.add_minutes(end.date(), 30)
    shared.save(FocusState('focus', end - timedelta(minutes=50), 50, ['aviso antigo']))
    win = quiet_window(app, tmp_path, monkeypatch)
    try:
        app.processEvents()
        expected = f'Seu foco terminou {_clock(end.hour, end.minute)} enquanto eu estava fechado. Hoje são 1 hora e 20 de foco.'
        assert win.said == [expected, 'Avisos que segurei durante o foco:\n• aviso antigo'] and spoken(win) == [expected]
        assert shared.mail_calls == [] and getattr(win._orchestrator, '_focus_offer', None) is None
        assert shared.state().phase == 'off' and shared.today(end.date()) == 80 and win._focus_view is None
    finally:
        win._speech_output = None
        close(app, win)


def test_stop_early_counts_real_minutes(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    host = window._orchestrator
    focus.answer('foco', host, now - timedelta(minutes=30, seconds=50))
    window._apply_focus(focus._payload(shared.state()))
    shared.save(FocusState('focus', now - timedelta(minutes=30, seconds=50), 50, ['O disco C ficou com 3 GB.']))
    text, payload = focus.answer('sai do foco', host, now)
    window._apply_command_result(OrchestrationResult(status='success', message=text, ui_action='focus', ui_payload=payload))
    assert not window._focus_shot.isActive() and window._focus_view is None
    settle_mail(app, window)
    expected = ended_text(30, 30, MAIL, ['O disco C ficou com 3 GB.'], 10)
    assert spoken(window) == [expected] and window.said[0] == 'Foco encerrado.' and expected in window.said
    assert shared.today(now.date()) == 30 and host._focus_offer[1] == 'pause'


def test_stop_right_away_has_no_summary(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    host = window._orchestrator
    focus.answer('foco', host, now - timedelta(seconds=20))
    window._apply_focus(focus._payload(shared.state()))
    text, payload = focus.answer('sai do foco', host, now)
    window._apply_command_result(OrchestrationResult(status='success', message=text, ui_action='focus', ui_payload=payload))
    settle_mail(app, window)
    assert window.said == ['Foco encerrado.'] and spoken(window) == [] and shared.mail_calls == []
    assert getattr(host, '_focus_offer', None) is None


def test_pause_offer_starts_only_when_the_summary_is_spoken(app, window, shared, monkeypatch):
    now = datetime.now().replace(microsecond=0)
    host = window._orchestrator
    shared.save(FocusState('focus', now - timedelta(minutes=50), 50, []))
    window._processing = True                        # um pedido longo em andamento
    window._focus_due(now)
    settle_mail(app, window)
    assert spoken(window) == [] and getattr(host, '_focus_offer', None) is None
    clock = [time.monotonic() + 180]                 # 3 minutos ocupado
    monkeypatch.setattr(focus.time, 'monotonic', lambda: clock[0])
    window._processing = False
    window._drain_speech()
    assert spoken(window) == [ended_text(50, 50, MAIL, [], 10)]
    assert host._focus_offer == (clock[0] + 120, 'pause')    # os 120 s contam a partir da fala
    assert focus.answer('sim', host, now + timedelta(minutes=3))[1]['phase'] == 'pause'


def test_offer_waits_for_a_pending_plan_to_clear(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    host = window._orchestrator
    shared.save(FocusState('pause', now - timedelta(minutes=10), 10, []))
    window._pending_plan = object()                  # um plano esperando o "sim" dele
    window._focus_due(now)
    assert spoken(window) == [] and getattr(host, '_focus_offer', None) is None
    window._pending_plan = None
    window._drain_speech()
    assert spoken(window) == ['Pausa acabou. Mais 50 minutos de foco?'] and host._focus_offer[1] == 'again'


def test_without_voice_the_offer_starts_when_written(app, window, shared):
    now = datetime.now().replace(microsecond=0)
    window._speech_output = None
    shared.save(FocusState('pause', now - timedelta(minutes=10), 10, []))
    window._focus_due(now)
    assert window.said == ['Pausa acabou. Mais 50 minutos de foco?'] and window._orchestrator._focus_offer[1] == 'again'
