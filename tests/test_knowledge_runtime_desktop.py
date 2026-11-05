"""Construção normal da UI com configuração explícita e cofre fictício."""
from datetime import datetime, timedelta, timezone
import time
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from therion.context.second_brain import SecondBrainReader
from therion.interface.desktop import MainWindow
from therion.memory.knowledge import RAS_ROOT
from therion.voice.service import VoiceModelService


@pytest.fixture
def ui(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    vault = tmp_path/'vault'
    monkeypatch.setattr(SecondBrainReader, 'DEFAULT_VAULT_ROOT', str(vault))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    settings = {'knowledge_access':dict(read_all=True, supervised_memory=True,
        authorization='teste-ficticio-desktop', expires_at=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(), revision=1)}
    voice = MagicMock(); voice.state = VoiceModelService.STATE_READY
    with patch.object(MainWindow, '_setup_tray'):
        window = MainWindow(MagicMock(), config=settings, voice_service=voice, config_loader=lambda:settings)
    yield window, vault, settings
    wait_until(lambda: not window._processing)
    window._memory_timer.stop(); window._conversation_timer.stop()
    window._orchestrator.close(); window.deleteLater(); qt.processEvents()


def wait_until(predicate):
    deadline = time.monotonic()+5
    while not predicate() and time.monotonic()<deadline:
        QTest.qWait(5); time.sleep(0.005)
    assert predicate()


def send(window, text):
    window._input.setPlainText(text); window._send_command()
    wait_until(lambda:not window._processing)


def test_configured_runtime_saves_through_existing_panel(ui):
    window, vault, _ = ui
    assert window._orchestrator.second_brain.allowed_roots == [str(vault.resolve())]
    send(window,'lembre que prefiro exemplos fictícios curtos')
    send(window,'salve')
    assert not window._confirm_panel.isHidden()
    assert str(vault/RAS_ROOT) in window._history.toPlainText()
    assert not (vault/RAS_ROOT).exists()
    window._handle_confirmation('sim'); wait_until(lambda:not window._processing)
    assert len(list((vault/RAS_ROOT).glob('RAS-*.md')))==1
    assert window._pending_plan is None
    send(window,'o que você guardou?')
    assert 'Rascunhos válidos recuperados' in window._history.toPlainText()


def test_configuration_revocation_invalidates_visible_confirmation(ui):
    window, vault, settings = ui
    send(window,'lembre que prefiro exemplos fictícios curtos'); send(window,'salve')
    settings['knowledge_access']['supervised_memory']=False
    window._handle_confirmation('sim'); wait_until(lambda:not window._processing)
    assert not list((vault/RAS_ROOT).glob('RAS-*.md'))
    assert window._pending_plan is None
