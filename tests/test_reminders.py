"""Aviso antes do compromisso: só agenda do panorama, guardado enquanto o usuário está ocupado."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from therion.config.local import _validate_config
from therion.interface import reminders
from therion.interface.reminders import EventReminders

DAY = dict(year=2026, month=11, day=16)
ITEMS = [{'title': 'Dentista', 'time': '14:00'}, {'title': 'Feriado', 'time': 'Dia inteiro'},
         {'title': 'Passado', 'time': '08:00'}, {'title': 'Jantar', 'time': '20:30'}, 'lixo', {'title': 3, 'time': '10:00'}]


def at(hour, minute=0, second=0):
    return datetime(hour=hour, minute=minute, second=second, **DAY)


def test_warns_once_fifteen_minutes_before():
    box = EventReminders()
    box.arm(ITEMS, at(9))
    assert box.due(at(13, 44)) == []
    assert box.due(at(13, 45)) == ['Em 15 minutos: Dentista, às 14:00.']
    assert box.due(at(13, 46)) == [] and box.due(at(14, 5)) == []
    assert box.due(at(20, 29, 20)) == ['Em 1 minuto: Jantar, às 20:30.']


def test_holds_the_warning_while_busy_and_tells_afterwards():
    box = EventReminders()
    box.arm(ITEMS, at(9))
    assert box.due(at(13, 50), busy=True) == [] and box.due(at(14, 10), busy=True) == []
    assert box.due(at(14, 20)) == ['Dentista começou às 14:00; segurei o aviso enquanto o senhor estava ocupado.']
    assert box.due(at(14, 21)) == []


def test_a_warning_held_for_too_long_is_dropped():
    box = EventReminders()
    box.arm(ITEMS, at(9))
    assert box.due(at(16, 30)) == []


def test_a_new_panorama_does_not_repeat_what_was_already_said():
    box = EventReminders()
    box.arm(ITEMS, at(9))
    assert len(box.due(at(13, 50))) == 1
    box.arm(ITEMS, at(13, 52))
    assert box.due(at(13, 53)) == []
    box.arm(None, at(13, 54))
    assert box.due(at(20, 20)) == []


def test_do_not_disturb_reads_the_windows_notification_state(monkeypatch):
    def shell(value, code=0):
        def query(pointer):
            pointer._obj.value = value
            return code
        return type('Shell', (), {'SHQueryUserNotificationState': staticmethod(query)})
    for value, expected in ((1, False), (2, True), (3, True), (4, True), (5, False)):
        monkeypatch.setattr(reminders.ctypes, 'windll', type('Dll', (), {'shell32': shell(value)}), raising=False)
        assert reminders.do_not_disturb() is expected
    monkeypatch.setattr(reminders.ctypes, 'windll', type('Dll', (), {'shell32': shell(3, code=1)}), raising=False)
    assert reminders.do_not_disturb() is False


def test_reminders_are_off_unless_the_user_turns_them_on():
    assert _validate_config({})['ui']['event_reminders'] is False
    assert _validate_config({'ui': {'event_reminders': 'sim'}})['ui']['event_reminders'] is False
    assert _validate_config({'ui': {'event_reminders': True}})['ui']['event_reminders'] is True


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, tmp_path, monkeypatch, enabled, game_mode=False):
    for variable in ('APPDATA', 'LOCALAPPDATA'):
        folder = tmp_path / variable
        folder.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    from therion.interface.desktop import MainWindow
    config = {'ai': {'enabled': False}, 'tts': {'enabled': False}, 'ui': {'event_reminders': enabled, 'game_mode': game_mode}}
    with patch.object(MainWindow, '_setup_tray'):
        return MainWindow(MagicMock(), config=config, config_writer=MagicMock(), log_dir=tmp_path / 'logs')


def close(app, window):
    window._closing = True
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def test_window_speaks_the_warning_only_when_free(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, True)
    try:
        assert window._reminder_timer.isActive()
        window._reminders = MagicMock()
        window._reminders.due.return_value = ['Em 15 minutos: Dentista, às 14:00.']
        window._speech_output = MagicMock()
        said = []
        monkeypatch.setattr(window, '_append', lambda sender, text: said.append((sender, text)))
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: True)
        window._poll_reminders()
        assert window._reminders.due.call_args.args[1] is True     # tela cheia: pede para segurar
        monkeypatch.setattr(reminders, 'do_not_disturb', lambda: False)
        window._poll_reminders()
        assert window._reminders.due.call_args.args[1] is False
        assert said[-1] == ('Therion', 'Em 15 minutos: Dentista, às 14:00.')
        window._speech_output.speak.assert_called_with('Em 15 minutos: Dentista, às 14:00.')
        window._processing = True
        window._poll_reminders()
        assert window._reminders.due.call_args.args[1] is True     # pedido em andamento: segura
    finally:
        window._processing = False
        window._speech_output = None
        close(app, window)


def test_window_without_the_setting_never_warns(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, False)
    try:
        assert window._reminders is None and not window._reminder_timer.isActive()
        window._poll_reminders()
    finally:
        close(app, window)


def test_game_mode_unloads_the_model_once_per_full_screen_session(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, False, game_mode=True)
    try:
        assert window._reminder_timer.isActive()
        window._orchestrator.ai_core = MagicMock()
        provider = window._orchestrator.ai_core._provider
        said = []
        monkeypatch.setattr(window, '_append', lambda sender, text: said.append(text))
        window._poll_game_mode(True)
        assert provider.unload.call_count == 0          # um ciclo só pode ser troca de janela
        window._processing = True
        window._poll_game_mode(True)
        assert provider.unload.call_count == 0          # nunca no meio de um pedido
        window._processing = False
        window._poll_game_mode(True)
        window._game_thread.join(5)
        assert provider.unload.call_count == 1 and said == [
            'Modo jogo: liberei a placa de vídeo. Meu primeiro pedido depois disso demora um pouco mais.']
        window._poll_game_mode(True)
        assert provider.unload.call_count == 1          # uma vez por sessão de tela cheia
        window._poll_game_mode(False)
        window._poll_game_mode(True); window._poll_game_mode(True)
        window._game_thread.join(5)
        assert provider.unload.call_count == 2
        provider.unload.side_effect = OSError('Ollama fora do ar')
        window._poll_game_mode(False)
        window._poll_game_mode(True); window._poll_game_mode(True)
        window._game_thread.join(5)                     # falha ao liberar nunca derruba a janela
    finally:
        window._processing = False
        close(app, window)


def test_game_mode_is_off_by_default_and_unload_asks_ollama_to_drop_the_model():
    assert _validate_config({})['ui']['game_mode'] is False
    assert _validate_config({'ui': {'game_mode': True}})['ui']['game_mode'] is True
    from therion.core.ai_provider_ollama import OllamaProvider
    provider = OllamaProvider.__new__(OllamaProvider)
    provider.model = 'modelo-teste'
    sent = []
    provider._send_request = lambda payload, timeout: sent.append((payload, timeout))
    provider.unload()
    assert sent == [({'model': 'modelo-teste', 'messages': [], 'stream': False, 'keep_alive': 0}, 15)]
