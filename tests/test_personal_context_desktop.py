"""Fluxo de compreensão pelo painel Qt, com cofre e serviços fictícios."""
from datetime import datetime, timedelta, timezone
import time
from unittest.mock import MagicMock, patch
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from therion.context.second_brain import SecondBrainReader
from therion.core.ai_core import AICore
from therion.interface.desktop import MainWindow
from therion.voice.service import VoiceModelService


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def panel(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    vault = tmp_path/'cofre-ficticio'
    profile = vault/'01 - Pessoal'/'Perfil.md'
    profile.parent.mkdir(parents=True)
    profile.write_text('# Luana fictícia\nCurso atual: Engenharia Biomédica\nTécnico concluído: Instrumentação', encoding='utf-8')
    original = profile.read_bytes()
    monkeypatch.setattr(SecondBrainReader, 'DEFAULT_VAULT_ROOT', str(vault))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local-ficticio'))
    settings = {'knowledge_access': dict(read_all=True, supervised_memory=False,
        authorization='teste-contexto-ficticio', expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), revision=1)}
    provider, voice = MagicMock(), MagicMock()
    provider.describe_result.return_value = 'Você cursa Engenharia Biomédica e concluiu Instrumentação.'
    voice.state = VoiceModelService.STATE_READY
    with patch.object(MainWindow, '_setup_tray'), \
            patch.object(MainWindow, '_build_ai_core', return_value=AICore(provider, [])), \
            patch.object(MainWindow, '_build_calendar_adapter', return_value=None):
        window = MainWindow(MagicMock(), config=settings,
            voice_service=voice, config_loader=lambda: settings, log_dir=str(tmp_path/'logs'))
    yield window, provider, profile
    wait_until(lambda: not window._processing)
    assert profile.read_bytes() == original
    assert not (vault/'90 - Sistema da IA'/'Notas de Rascunho da IA'/'Registros').exists()
    window._memory_timer.stop()
    window._conversation_timer.stop()
    window._orchestrator.close()
    window.deleteLater()
    qt.processEvents()


def send(window, command):
    window._input.setPlainText(command)
    window._send_command()
    wait_until(lambda: not window._processing)


def test_profile_answer_reaches_panel_without_confirmation_or_write(panel):
    window, provider, _ = panel
    send(window, 'Leia meu perfil e explique minha formação atual e o que já conclui.')
    assert 'Engenharia Biomédica' in window._history.toPlainText()
    assert '01 - Pessoal/Perfil.md' in window._history.toPlainText()
    assert window._pending_plan is None
    assert window._confirm_panel.isHidden()
    provider.generate.assert_not_called()


def test_assistant_identity_and_refusal_use_conversation_in_panel(panel):
    window, provider, _ = panel
    provider.describe_result.return_value = 'Uma melhoria seria organizar as tarefas por prioridade.'
    send(window, 'O que implementar para você ficar melhor?')
    provider.describe_result.return_value = 'Tudo bem.'
    send(window, 'Não.')
    assert 'proposta pendente' not in window._history.toPlainText()
    assert provider.describe_result.call_args.args[1]['dialogue_act'] == 'decline'
    assert window._pending_plan is None
    provider.generate.assert_not_called()
