"""Painel/worker Qt reais, sem configuração pessoal, rede ou áudio."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from therion.core.orchestrator import Orchestrator
from therion.interface.desktop import MainWindow
from therion.memory.knowledge import MemoryPolicy, RAS_ROOT
from therion.memory.repository import MarkdownMemoryRepository
from therion.memory.supervised import MemoryEvidenceStore
from therion.voice.service import VoiceModelService


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
        time.sleep(0.005)  # Libera o GIL para o worker que publica e verifica SQLite/RAS.
    assert predicate()


@pytest.fixture
def ui(tmp_path):
    app = QApplication.instance() or QApplication([])
    voice = MagicMock(); voice.state = VoiceModelService.STATE_READY
    with patch.object(MainWindow, '_setup_tray'):
        window = MainWindow(MagicMock(), config={}, voice_service=voice)
    window._orchestrator.close()
    vault = tmp_path/'vault'; root = vault/RAS_ROOT
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    policy = MemoryPolicy(mode='authorized', read_roots=(str(vault.resolve()),),
        write_root=str(root.resolve()), authorization='somente-teste-ficticio', expires_at=now+timedelta(days=1))
    window._orchestrator = Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'),
        memory_repository=MarkdownMemoryRepository(root), memory_policy=policy,
        memory_evidence_store=MemoryEvidenceStore(tmp_path/'evidence'))
    window._orchestrator.knowledge.clock = lambda: now
    window._speech_output = MagicMock(); window._speech_output.state = 'idle'
    yield window, root
    if window._command_worker is not None:
        wait_until(lambda: window._command_worker is None)
    if window._confirmation_worker is not None:
        wait_until(lambda: window._confirmation_worker is None)
    window._memory_timer.stop(); window._conversation_timer.stop()
    window._orchestrator.close(); window.deleteLater(); app.processEvents()


def send(window, text):
    window._input.setPlainText(text)
    window._send_command()
    wait_until(lambda: not window._processing)


@pytest.mark.parametrize('answer', ['sim', 'não'])
def test_save_uses_real_confirmation_panel_and_worker(ui, answer):
    window, root = ui
    send(window, 'lembre que prefiro exemplos curtos')
    send(window, 'salve')
    assert window._pending_plan is window._orchestrator._pending_memory_plan
    assert not window._confirm_panel.isHidden()
    assert str(root) in window._history.toPlainText()
    assert not root.exists()
    window._handle_confirmation(answer)
    wait_until(lambda: not window._processing)
    assert window._pending_plan is None and window._confirm_panel.isHidden()
    assert len(list(root.glob('RAS-*.md'))) == (1 if answer == 'sim' else 0)


def test_clear_invalidates_visible_memory_proposal(ui):
    window, root = ui
    send(window, 'lembre que prefiro exemplos curtos'); send(window, 'salve')
    orch = window._orchestrator
    plan, session, token = window._pending_plan, orch.session_id, orch.confirmation_id
    window._clear_conversation()
    assert window._pending_plan is None
    assert orch.confirm_session_proposal(plan, True, session, token).status == 'cancelled'
    assert not root.exists()
