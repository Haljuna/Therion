"""A janela grava a conversa na nota local quando ui.conversation_log está ligado."""
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from therion.core.orchestrator import OrchestrationResult


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_window(app, tmp_path, monkeypatch, enabled):
    for variable in ('APPDATA', 'LOCALAPPDATA'):
        folder = tmp_path / variable
        folder.mkdir(exist_ok=True)
        monkeypatch.setenv(variable, str(folder))
    from therion.interface.desktop import MainWindow
    config = {'ai': {'enabled': False}, 'tts': {'enabled': False}, 'ui': {'conversation_log': enabled}}
    with patch.object(MainWindow, '_setup_tray'):
        return MainWindow(MagicMock(), config=config, config_writer=MagicMock(), log_dir=tmp_path / 'logs')


def close(app, window):
    window._closing = True
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def notes(tmp_path):
    return sorted((tmp_path / 'LOCALAPPDATA' / 'Therion' / 'conversas').glob('*.md'))


def test_window_records_typed_exchange_spoken_text_and_rotates_on_clear(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, True)
    try:
        window._append('Você', 'agenda de amanhã')
        window._apply_command_result(OrchestrationResult(
            status='success', message='Consultei seu calendário e encontrei 2 compromissos.',
            speech_message='Amanhã você tem 2 compromissos: Reunião, às 15 horas.'))
        text = notes(tmp_path)[0].read_text(encoding='utf-8')
        assert '· texto' in text and '**Você:** agenda de amanhã' in text
        assert '**Therion (tela):** Consultei seu calendário' in text
        assert '**Therion (falou):** Amanhã você tem 2 compromissos' in text
        assert 'status: success' in text
        window._clear_conversation()
        window._append('Você', 'depois de limpar')
        assert len(notes(tmp_path)) == 2
    finally:
        close(app, window)


def test_voice_channel_is_marked(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, True)
    try:
        window._next_user_channel = 'voz'
        window._append('Você', 'Boa noite')
        window._append('Você', 'digitado depois')
        text = notes(tmp_path)[0].read_text(encoding='utf-8')
        assert text.index('· voz') < text.index('Boa noite') < text.index('· texto')
    finally:
        close(app, window)


def test_disabled_by_default_writes_nothing(app, tmp_path, monkeypatch):
    window = make_window(app, tmp_path, monkeypatch, False)
    try:
        window._append('Você', 'oi')
        assert notes(tmp_path) == []
    finally:
        close(app, window)
