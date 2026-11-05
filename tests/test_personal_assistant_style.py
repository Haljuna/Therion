"""Primeira pessoa deve distinguir intenção, simulação e execução verificada."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from therion.core.orchestrator import Orchestrator


def test_action_voice_keeps_simulation_and_cancellation_explicit(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path), simulate=True)
    pending = orch.process_command('abra o Obsidian')
    assert 'simular' in pending.speech_message
    assert 'não será aberto de verdade' in pending.speech_message
    assert 'Plano:' in pending.message
    simulated = orch.confirm_and_execute(pending.plan, confirmed=True)
    assert simulated.speech_message == 'Simulei a abertura do Obsidian. Não abri o aplicativo de verdade.'
    pending = orch.process_command('abra o Obsidian')
    cancelled = orch.confirm_and_execute(pending.plan, confirmed=False)
    assert cancelled.speech_message == 'Cancelei. Não executei a ação.'


@pytest.mark.parametrize('executed,verified,expected', [
    (False, False, 'Não consegui abrir o Obsidian.'),
    (True, False, 'Tentei abrir o Obsidian, mas não consegui confirmar'),
    (True, True, 'Abri o Obsidian e confirmei que o processo iniciou.'),
])
def test_spoken_action_result_requires_evidence(tmp_path, executed, verified, expected):
    orch = Orchestrator(log_dir=str(tmp_path), simulate=False)
    pending = orch.process_command('abra o Obsidian')
    assert pending.speech_message == 'Posso abrir o Obsidian?'
    orch.executor.execute_real = MagicMock(return_value=SimpleNamespace(success=executed, message='Detalhe do executor'))
    orch.verifier.verify_real = MagicMock(return_value=SimpleNamespace(success=verified, message='Detalhe da verificação'))
    result = orch.confirm_and_execute(pending.plan, confirmed=True)
    assert result.speech_message.startswith(expected)
    assert 'Detalhe do executor' in result.message
    assert 'Detalhe do executor' not in result.speech_message


@pytest.mark.parametrize('executed,verified,status', [
    (False, False, 'execution_failed'),
    (True, False, 'verification_failed'),
    (True, True, 'success'),
])
def test_execution_claim_requires_execution_and_verification(tmp_path, executed, verified, status):
    orch = Orchestrator(log_dir=str(tmp_path), simulate=False)
    pending = orch.process_command('abra o Obsidian')
    assert pending.status == 'awaiting_confirmation'
    assert 'Concluí' not in pending.message
    orch.executor.execute_real = MagicMock(return_value=SimpleNamespace(success=executed, message='execution evidence'))
    orch.verifier.verify_real = MagicMock(return_value=SimpleNamespace(success=verified, message='verification evidence'))
    result = orch.confirm_and_execute(pending.plan, confirmed=True)
    assert result.status == status
    assert ('Concluí' in result.message) == (executed and verified)
    if not executed:
        orch.verifier.verify_real.assert_not_called()


def test_simulation_and_cancellation_do_not_claim_real_completion(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path), simulate=True)
    pending = orch.process_command('abra o Obsidian')
    result = orch.confirm_and_execute(pending.plan, confirmed=True)
    assert result.status == 'executed_simulated'
    assert 'Simulei' in result.message
    assert 'não executei a operação de verdade' in result.message
    assert 'Concluí' not in result.message
    pending = orch.process_command('abra o Obsidian')
    result = orch.confirm_and_execute(pending.plan, confirmed=False)
    assert result.status == 'cancelled'
    assert 'Concluí' not in result.message


def test_search_reports_actual_evidence_without_claiming_matches(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path))
    orch.second_brain.search_notes = MagicMock(return_value=[])
    result = orch.process_command('procure no segundo cérebro prova')
    assert 'Busquei' in result.message
    assert 'não encontrei' in result.message
    orch.second_brain.search_notes.return_value = [SimpleNamespace(path='Prova.md', snippet='Prova amanhã')]
    result = orch.process_command('procure no segundo cérebro prova')
    assert 'Encontrei 1 registro' in result.message
    assert 'Prova.md' in result.message
    assert 'Prova amanhã' in result.message
