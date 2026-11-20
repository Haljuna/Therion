"""Vigia do PC: avisa sozinho, uma vez por problema; no jogo ou em tela cheia só escreve."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent, QRect
from PySide6.QtWidgets import QApplication

from therion.config.local import _validate_config
from therion.interface import pc_watch, reminders
from therion.interface.pc_watch import PcWatch

GB = 1024 ** 3
DISK = 'Senhor, o disco C está quase cheio: 4,0 GB livres.'


def pc(ram=.5, commit=.5, c=50, top=(('chrome.exe', 3 * GB),)):
    return dict(ram_total=16 * GB, ram_free=ram * 16 * GB, commit_total=20 * GB, commit_free=commit * 20 * GB,
                disks={'C': c * GB, 'F': 100 * GB}, top=list(top))


def test_warns_once_and_again_only_after_really_recovering():
    watch = PcWatch()
    assert watch.check(pc()) == []
    assert watch.check(pc(c=4)) == [DISK]
    assert watch.check(pc(c=4)) == []
    assert watch.check(pc(c=5.5)) == [] and watch.check(pc(c=4)) == []   # oscilar perto do limite não repete
    assert watch.check(pc(c=7)) == []
    assert watch.check(pc(c=4)) == [DISK]


def test_disk_almost_empty_is_a_second_louder_warning_said_once():
    watch = PcWatch()
    assert watch.check(pc(c=4)) == [DISK]
    critical = watch.check(pc(c=.8))
    assert len(critical) == 1 and 'crítico' in critical[0] and '0,8 GB' in critical[0]
    assert watch.check(pc(c=.8)) == []
    first = PcWatch().check(pc(c=.08))
    assert len(first) == 1 and 'crítico' in first[0]                       # já crítico: um aviso só


def test_memory_warnings_name_the_heaviest_app():
    assert PcWatch().check(pc(commit=.05)) == [
        'Senhor, a memória virtual está quase esgotada: 1,0 GB livres de 20,0 GB; é esse limite que derruba o meu modelo. '
        'O que mais usa memória: chrome (3,0 GB).']
    assert PcWatch().check(pc(ram=.1, top=())) == ['Senhor, a memória RAM está quase cheia: 1,6 GB livres de 16,0 GB.']


def test_a_hot_video_card_needs_two_readings_and_no_nvidia_is_fine():
    watch = PcWatch()
    assert watch.check(pc(), 90) == []
    assert watch.check(pc(), 90) == ['Senhor, a placa de vídeo está a 90 °C há alguns minutos.']
    assert watch.check(pc(), 90) == [] and watch.check(pc(), 82) == [] and watch.check(pc(), 90) == []
    assert watch.check(pc(), 70) == [] and watch.check(pc(), 88) == []
    assert watch.check(pc(), 88) == ['Senhor, a placa de vídeo está a 88 °C há alguns minutos.']
    assert PcWatch().check(pc(), None) == []


def test_the_watch_reads_the_driver_and_the_windows_counters_without_opening_programs(monkeypatch):
    from therion.interface import pc_health
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: (GB, 8 * GB, 41))
    assert pc_watch.gpu_temperature() == 41
    monkeypatch.setattr(pc_health, 'gpu_memory', lambda: None)
    assert pc_watch.gpu_temperature() is None
    def no_programs(*a, **k):
        raise AssertionError('o vigia não abre tasklist nem nvidia-smi')
    monkeypatch.setattr(subprocess, 'run', no_programs)
    monkeypatch.setattr(pc_health, '_read_counters', lambda: {'pid': [('svchost', 7)], 'ram': [('svchost', GB)]})
    assert pc_watch._measure()['processes'] == {7: ('svchost', GB)}


def quiet_disk(monkeypatch, sizes=None, spare=0):
    """Nada de andar nas pastas reais do C nos testes."""
    monkeypatch.setattr(pc_watch, 'folder_sizes', lambda: dict(sizes or {}))
    monkeypatch.setattr(pc_watch.pc_cleanup, 'estimate', lambda rows=None: spare)
    monkeypatch.setattr(pc_watch, 'gpu_temperature', lambda: None)


def test_poll_survives_a_failed_measurement(monkeypatch, tmp_path):
    def broken():
        raise OSError('GlobalMemoryStatusEx falhou.')
    monkeypatch.setattr(pc_watch, '_measure', broken)
    assert PcWatch(tmp_path / 'foto.json').poll() == []
    quiet_disk(monkeypatch)
    monkeypatch.setattr(pc_watch, '_measure', lambda: pc(c=4))
    assert PcWatch(str(tmp_path / 'foto.json')).poll() == [(DISK, False)]   # sem nada para limpar: sem oferta


def test_disk_warning_says_what_grew_since_the_daily_photo_and_offers_the_cleanup(monkeypatch, tmp_path):
    from datetime import datetime
    import json
    photo = tmp_path / 'foto.json'
    photo.write_text(json.dumps(dict(day='2026-11-16', time='2026-11-16T09:12', free=8 * GB,
                                     sizes={'Temp do usuário': 1 * GB, 'Downloads': 2 * GB})), encoding='utf-8')
    quiet_disk(monkeypatch, sizes={'Temp do usuário': 4.1 * GB, 'Downloads': 2 * GB}, spare=3 * GB)
    monkeypatch.setattr(pc_watch, '_measure', lambda: pc(c=4))
    said = PcWatch(str(photo)).poll(datetime(2026, 11, 17, 15, 0))
    assert said == [(DISK + ' O C perdeu 4,0 GB desde ontem às 09:12; quem cresceu: Temp do usuário (+3,1 GB).'
                     ' Quer que eu limpe os temporários seguros? Dá uns 3,0 GB.', True)]
    assert json.loads(photo.read_text(encoding='utf-8'))['day'] == '2026-11-17'   # foto nova do dia


def test_explain_tells_pagefile_from_files_and_stays_quiet_without_a_real_drop():
    from datetime import datetime
    now = datetime(2026, 11, 17, 15, 0)
    photo = dict(time='2026-11-17T08:00', free=10 * GB, sizes={'Memória virtual': 2 * GB, 'Temp do usuário': GB})
    assert 'foi a memória virtual, não arquivo; o pagefile cresceu 4,0 GB' in pc_watch.explain(
        photo, 5 * GB, {'Memória virtual': 6 * GB, 'Temp do usuário': GB}, now)
    assert pc_watch.explain(photo, 5 * GB, dict(photo['sizes']), now) == (
        ' O C perdeu 5,0 GB desde hoje às 08:00; não foi nas pastas de sempre, pode ser atualização ou programa novo.')
    assert pc_watch.explain(photo, 9.8 * GB, {}, now) == '' and pc_watch.explain(None, GB, {}, now) == ''
    assert pc_watch.explain({'time': 'lixo', 'free': 1}, GB, {}, now) == ''


class Clock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now


def test_forecast_warns_once_when_the_disk_falls_fast():
    clock = Clock()
    watch = PcWatch(clock=clock)
    said = []
    for step in range(16):                        # 0,5 GB a cada 2 min, de 15 GB para baixo
        clock.now = step * 120
        said += watch.check(pc(c=15 - .5 * step))
    assert said == ['Senhor, o disco C está caindo rápido: no ritmo da última meia hora, chega a 1 GB em uns 35 minutos (10,0 GB livres agora).']
    slow, said = PcWatch(clock=Clock()), []
    for step in range(30):                        # 0,05 GB a cada 2 min: ainda longe
        slow._clock.now = step * 120
        said += slow.check(pc(c=15 - .05 * step))
    assert said == []


def test_game_summary_tells_the_worst_moment_only_when_something_was_tight():
    watch = PcWatch()
    watch.game(True)
    watch.check(pc(ram=.1), 88); watch.check(pc(), 80)
    assert watch.game(False) == 'Senhor, na partida a placa chegou a 88 °C e a RAM ficou quase cheia.'
    watch.game(True)
    watch.check(pc(), 60)
    assert watch.game(False) is None
    watch.check(pc(ram=.1), 95)                   # fora do jogo não guarda
    watch.game(True)
    assert watch.game(False) is None


def test_leak_is_a_process_that_grows_for_an_hour_and_never_lets_go():
    clock = Clock()
    watch = PcWatch(service=lambda pid: 'StorSvc' if pid == 100 else None, clock=clock)
    said = []
    for step in range(31):
        clock.now = step * 120
        said += watch.check(dict(pc(), processes={
            100: ('svchost.exe', .3 * GB + step * .08 * GB),                          # vaza
            200: ('ollama.exe', (4 if step > 3 else .1) * GB),                        # modelo carregando: salto e para
            300: ('chrome.exe', (1 + step * .06 if step < 20 else .5) * GB)}))        # cresce mas solta
    assert said == ['Senhor, o svchost (StorSvc) foi de 0,3 GB para 2,3 GB em 1 hora e não para de crescer; '
                    'parece vazamento. Reiniciar o programa, ou o PC, resolve.']


def test_the_watch_is_on_unless_the_user_turns_it_off():
    assert _validate_config({})['ui']['pc_watch'] is True
    assert _validate_config({'ui': {'pc_watch': 'sim'}})['ui']['pc_watch'] is True
    assert _validate_config({'ui': {'pc_watch': False}})['ui']['pc_watch'] is False


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_window(tmp_path, monkeypatch, enabled):
    for variable in ('APPDATA', 'LOCALAPPDATA'):
        folder = tmp_path / variable
        folder.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    from therion.interface.desktop import MainWindow
    config = {'ai': {'enabled': False}, 'tts': {'enabled': False}, 'ui': {'pc_watch': enabled}}
    with patch.object(MainWindow, '_setup_tray'):
        return MainWindow(MagicMock(), config=config, config_writer=MagicMock(), log_dir=tmp_path / 'logs')


def close(app, window):
    window._closing = True
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


class FakeWatch:
    def __init__(self, said):
        self.said, self.polls, self.in_game, self.summary = said, 0, False, None

    def poll(self):
        self.polls += 1
        return list(self.said)

    def game(self, on):
        self.in_game = on
        return None if on else self.summary


def test_window_measures_in_the_background_and_speaks_only_when_free(app, tmp_path, monkeypatch):
    window = make_window(tmp_path, monkeypatch, True)
    try:
        assert window._reminder_timer.isActive()
        window._pc_watch = watch = FakeWatch([(DISK, False)])
        window._speech_output = MagicMock()
        said = []
        monkeypatch.setattr(window, '_append', lambda sender, text: said.append(text))
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: True)
        window._poll_reminders()                       # 1º ciclo: mede numa thread
        window._pc_watch_thread.join(5)
        assert watch.polls == 1 and said == [] and watch.in_game
        window._poll_reminders()                       # tela cheia: só escreve
        assert said == [DISK] and not window._speech_output.speak.called
        window._poll_reminders(); window._poll_reminders()
        assert watch.polls == 1                        # mede a cada 4 ciclos (2 min)
        window._processing = True
        window._poll_reminders()                       # 5º ciclo mede de novo; pedido em andamento segura o aviso
        window._pc_watch_thread.join(5)
        window._poll_reminders()
        assert watch.polls == 2 and said == [DISK]
        window._processing = False
        watch.summary = 'Senhor, na partida a placa chegou a 88 °C.'
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
        window._poll_reminders()                       # saiu da tela cheia: fala o que guardou e o resumo
        assert said == [DISK, DISK, watch.summary] and not watch.in_game
        assert [call.args[0] for call in window._speech_output.speak.call_args_list] == [DISK, watch.summary]
        window._game_forced = True
        window._pc_watch_said.append((DISK, False))
        window._poll_reminders()                       # modo jogo pedido por voz: só escreve
        assert len(said) == 4 and window._speech_output.speak.call_count == 2
    finally:
        window._processing = False
        window._game_forced = False
        window._speech_output = None
        close(app, window)


def test_window_opens_the_cleanup_offer_only_when_the_warning_is_shown(app, tmp_path, monkeypatch):
    window = make_window(tmp_path, monkeypatch, True)
    try:
        window._pc_watch = FakeWatch([])
        window._orchestrator._pc_cleanup_offer = None
        window._orchestrator._focus_offer = 'pausa'   # oferta de foco antiga: o "sim" passa a ser da limpeza
        monkeypatch.setattr(window, '_append', lambda sender, text: None)
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
        window._pc_watch_said.append((DISK + ' Quer que eu limpe os temporários seguros? Dá uns 2,0 GB.', True))
        window._processing = True
        window._poll_reminders()
        assert window._orchestrator._pc_cleanup_offer is None   # aviso ainda guardado: sem oferta
        window._processing = False
        window._poll_reminders()
        assert window._orchestrator._pc_cleanup_offer > __import__('time').monotonic() + 100
        assert window._orchestrator._focus_offer is None
    finally:
        window._processing = False
        close(app, window)


def test_window_with_the_watch_off_never_measures(app, tmp_path, monkeypatch):
    window = make_window(tmp_path, monkeypatch, False)
    try:
        assert window._pc_watch is None   # o tique roda sempre (lembretes por voz), mas não mede
        window._poll_reminders()
    finally:
        close(app, window)


def test_tight_ignores_leaks_already_told():
    watch = PcWatch()
    watch._active = {'leak:9'}
    assert watch.tight() is False
    watch._active = {'leak:9', 'disk'}
    assert watch.tight() is True


def test_the_mini_orb_is_on_unless_the_user_turns_it_off():
    assert _validate_config({})['ui']['mini_orb'] is True
    assert _validate_config({'ui': {'mini_orb': 'sim'}})['ui']['mini_orb'] is True
    assert _validate_config({'ui': {'mini_orb': False}})['ui']['mini_orb'] is False


class FakeMini:
    def __init__(self, *args, **kwargs):
        self.kwargs, self.calls, self.rect = kwargs, [], QRect(100, 100, 96, 96)

    def show(self):
        self.calls.append(('show',))

    def set_state(self, state, tight):
        self.calls.append(('state', state, tight))

    def set_quiet(self, quiet):
        self.calls.append(('quiet', quiet))

    def hide_for_game(self, hidden):
        self.calls.append(('hide', hidden))

    def frameGeometry(self):
        return self.rect

    def park(self, on):
        self.calls.append(('park', on))

    def set_timer(self, look):
        self.calls.append(('timer', look))

    def shut(self):
        self.calls.append(('shut',))


def make_mini_window(tmp_path, monkeypatch, mini=True, watch=True):
    from therion.interface import desktop
    monkeypatch.setattr(desktop, 'MiniOrb', FakeMini)
    for variable in ('APPDATA', 'LOCALAPPDATA'):
        folder = tmp_path / variable
        folder.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    config = {'ai': {'enabled': False}, 'tts': {'enabled': False}, 'ui': {'mini_orb': mini, 'pc_watch': watch}}
    with patch.object(desktop.MainWindow, '_setup_tray'):
        window = desktop.MainWindow(MagicMock(), config=config, config_writer=MagicMock(), log_dir=tmp_path / 'logs')
    if window._pc_watch is not None:   # sem isto o 1º ciclo mede o PC de verdade (tasklist, nvidia-smi, pastas)
        monkeypatch.setattr(window._pc_watch, 'poll', lambda: [])
    return window


def test_window_without_the_setting_has_no_mini_orb(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, mini=False, watch=False)
    assert window._mini_orb is None
    close(app, window)


def test_window_mirrors_the_orb_state_and_turns_amber_when_the_pc_is_tight(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch)
    mini = window._mini_orb
    assert mini.kwargs['path'].endswith('mini_orb.json') and ('show',) in mini.calls and window._reminder_timer.isActive()
    window._pc_watch._active = {'disk'}
    window._update_orbe('idle')
    assert mini.calls[-1] == ('state', 'idle', True)
    window._pc_watch._active = set()
    window._update_orbe('idle')
    assert mini.calls[-1] == ('state', 'idle', False)
    window._pc_watch._active = {'disk'}
    window._pc_watch_said.append(('Senhor, o disco C está cheio.', False))
    monkeypatch.setattr(window, '_append', lambda *a, **k: None)
    window._poll_pc_watch(False)
    assert mini.calls[-1] == ('state', 'idle', True)
    window._mini_orb = None
    close(app, window)


def test_a_fullscreen_game_on_the_same_monitor_hides_the_mini_orb(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    mini = window._mini_orb
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: True)
    monkeypatch.setattr(reminders, 'fullscreen_screen', lambda: mini.frameGeometry())
    window._poll_reminders()
    assert ('hide', True) in mini.calls and ('quiet', True) in mini.calls
    monkeypatch.setattr(reminders, 'fullscreen_screen', lambda: QRect(0, 0, 10, 10))
    window._poll_reminders()
    assert ('hide', False) in mini.calls[-2:]
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    monkeypatch.setattr(reminders, 'fullscreen_screen', lambda: None)
    window._poll_reminders()
    assert [call for call in mini.calls[-3:] if call[0] != 'state'] == [('quiet', False), ('hide', False)]
    window._mini_orb = None
    close(app, window)


def test_quitting_closes_the_mini_orb_first(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    mini = window._mini_orb
    order = []
    monkeypatch.setattr(window._app, 'quit', lambda: order.append('quit'))
    mini.shut = lambda: order.append('shut')
    window._quit_application()
    assert order == ['shut', 'quit']
    window._mini_orb = None
    close(app, window)


def test_amber_clears_on_the_next_tick_when_the_problem_passes_quietly(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch)
    mini = window._mini_orb
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    monkeypatch.setattr(reminders, 'fullscreen_screen', lambda: None)
    window._pc_watch._active = {'disk'}
    window._update_orbe('idle')
    assert mini.calls[-1] == ('state', 'idle', True)
    window._pc_watch._active = set()
    window._poll_reminders()
    assert ('state', 'idle', False) in mini.calls[-4:]
    window._mini_orb = None
    close(app, window)


def test_the_open_main_menu_action_uses_the_same_path_as_the_tray(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    assert window._mini_orb.kwargs['on_open_main'] == window._show_window
    window._mini_orb = None
    close(app, window)


def test_speaking_and_push_to_talk_reach_the_mini_orb_through_the_presentation(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from therion.interface.presentation import Presentation
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    mini = window._mini_orb
    window._dashboard = SimpleNamespace(presentation=Presentation(), interaction=lambda state: None)
    window._on_speech_state('playing')
    assert mini.calls[-1][:2] == ('state', 'speaking')
    window._on_speech_state('idle')
    assert mini.calls[-1][:2] == ('state', 'idle')
    window._on_voice_pipeline_state_changed('recording')
    assert mini.calls[-1][:2] == ('state', 'listening')
    window._on_voice_pipeline_state_changed('idle')
    assert mini.calls[-1][:2] == ('state', 'idle')
    window._dashboard = window._mini_orb = None
    close(app, window)


def test_game_mode_quiets_the_mini_orb_at_once(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    mini = window._mini_orb
    monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
    window._set_game_mode(True)
    assert ('quiet', True) in mini.calls
    window._set_game_mode(False)
    assert [call for call in mini.calls if call[0] == 'quiet'][-1] == ('quiet', False)
    window._mini_orb = None
    close(app, window)


# ---- só a orbe no segundo monitor: modo jogo, foco e minimizar ----
def _parks(mini):
    return [call[1] for call in mini.calls if call[0] == 'park']


def test_game_mode_hides_the_window_and_parks_the_orb(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.show(); app.processEvents()
    window._set_game_mode(True); app.processEvents()
    assert not window.isVisible() and _parks(window._mini_orb)[-1] is True
    window._set_game_mode(False); app.processEvents()
    assert window.isVisible() and _parks(window._mini_orb)[-1] is False
    close(app, window)


def test_game_mode_does_not_reopen_a_window_that_was_hidden(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.hide(); app.processEvents()
    window._set_game_mode(True); window._set_game_mode(False); app.processEvents()
    assert not window.isVisible()
    close(app, window)


def test_focus_and_game_keep_the_orb_parked_until_both_end(app, tmp_path, monkeypatch):
    from datetime import datetime
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.show(); app.processEvents()
    window._set_game_mode(True)
    window._apply_focus({'phase': 'focus', 'start': datetime.now().isoformat(), 'minutes': 25})
    window._set_game_mode(False)
    assert _parks(window._mini_orb)[-1] is True
    window._apply_focus({})
    assert _parks(window._mini_orb)[-1] is False
    close(app, window)


def test_minimize_hides_into_the_orb_and_full_open_brings_it_back(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.show(); app.processEvents()
    window._minimize_window(); app.processEvents()
    assert not window.isVisible() and _parks(window._mini_orb)[-1] is True
    window._show_window(); app.processEvents()
    assert window.isVisible() and _parks(window._mini_orb)[-1] is False
    close(app, window)


def test_hiding_into_the_orb_keeps_the_voice_conversation(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.show(); app.processEvents()
    ended = []
    monkeypatch.setattr(window, '_end_conversation', lambda *a, **k: ended.append('conversa'))
    monkeypatch.setattr(window, '_stop_speech', lambda *a, **k: ended.append('fala'))
    window._minimize_window(); app.processEvents()
    window._set_game_mode(True); app.processEvents()
    assert ended == []
    close(app, window)


def test_orb_click_toggles_the_chat(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    window.show(); app.processEvents()
    window._set_game_mode(True); app.processEvents()
    window._toggle_chat_from_orb(); app.processEvents()
    assert window.isVisible()
    window._toggle_chat_from_orb(); app.processEvents()
    assert not window.isVisible() and _parks(window._mini_orb)[-1] is True
    close(app, window)


def test_the_orb_click_is_wired_to_the_chat(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, watch=False)
    assert window._mini_orb.kwargs['on_click'] == window._toggle_chat_from_orb
    close(app, window)


def test_without_mini_orb_minimize_still_minimizes(app, tmp_path, monkeypatch):
    window = make_mini_window(tmp_path, monkeypatch, mini=False, watch=False)
    window.show(); app.processEvents()
    window._minimize_window(); app.processEvents()
    assert window.isMinimized()
    close(app, window)
