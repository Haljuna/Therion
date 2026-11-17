"""Vigia do PC: avisa sozinho, uma vez por problema; no jogo ou em tela cheia só escreve."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent
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


def test_gpu_temperature_reads_nvidia_smi_and_gives_up_quietly(monkeypatch):
    answer = lambda code, out: (lambda *a, **k: subprocess.CompletedProcess(a, code, out, ''))
    monkeypatch.setattr(pc_watch.subprocess, 'run', answer(0, '41\n'))
    assert pc_watch.gpu_temperature() == 41
    monkeypatch.setattr(pc_watch.subprocess, 'run', answer(1, ''))
    assert pc_watch.gpu_temperature() is None
    monkeypatch.setattr(pc_watch.subprocess, 'run', answer(0, '[N/A]\n'))
    assert pc_watch.gpu_temperature() is None
    def missing(*a, **k):
        raise FileNotFoundError('nvidia-smi')
    monkeypatch.setattr(pc_watch.subprocess, 'run', missing)
    assert pc_watch.gpu_temperature() is None


def test_poll_survives_a_failed_measurement(monkeypatch):
    def broken():
        raise OSError('GlobalMemoryStatusEx falhou.')
    monkeypatch.setattr(pc_watch, '_measure', broken)
    assert PcWatch().poll() == []
    monkeypatch.setattr(pc_watch, '_measure', lambda: pc(c=4))
    monkeypatch.setattr(pc_watch, 'gpu_temperature', lambda: None)
    assert PcWatch().poll() == [DISK]


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


def test_window_measures_in_the_background_and_speaks_only_when_free(app, tmp_path, monkeypatch):
    window = make_window(tmp_path, monkeypatch, True)
    try:
        assert window._reminder_timer.isActive()
        window._pc_watch = MagicMock()
        window._pc_watch.poll.return_value = [DISK]
        window._speech_output = MagicMock()
        said = []
        monkeypatch.setattr(window, '_append', lambda sender, text: said.append(text))
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: True)
        window._poll_reminders()                       # 1º ciclo: mede numa thread
        window._pc_watch_thread.join(5)
        assert window._pc_watch.poll.call_count == 1 and said == []
        window._poll_reminders()                       # tela cheia: só escreve
        assert said == [DISK] and not window._speech_output.speak.called
        window._poll_reminders(); window._poll_reminders()
        assert window._pc_watch.poll.call_count == 1   # mede a cada 4 ciclos (2 min)
        window._processing = True
        window._poll_reminders()                       # 5º ciclo mede de novo; pedido em andamento segura o aviso
        window._pc_watch_thread.join(5)
        window._poll_reminders()
        assert window._pc_watch.poll.call_count == 2 and said == [DISK]
        window._processing = False
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
        window._poll_reminders()                       # livre: escreve e fala
        assert said == [DISK, DISK]
        window._speech_output.speak.assert_called_once_with(DISK)
        window._game_forced = True
        window._pc_watch_said.append(DISK)
        window._poll_reminders()                       # modo jogo pedido por voz: só escreve
        assert len(said) == 3 and window._speech_output.speak.call_count == 1
    finally:
        window._processing = False
        window._game_forced = False
        window._speech_output = None
        close(app, window)


def test_window_with_the_watch_off_never_measures(app, tmp_path, monkeypatch):
    window = make_window(tmp_path, monkeypatch, False)
    try:
        assert window._pc_watch is None and not window._reminder_timer.isActive()
        window._poll_reminders()
    finally:
        close(app, window)
