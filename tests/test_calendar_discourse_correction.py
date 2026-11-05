"""Retomada positiva não elimina negação da ação nem confirma eventos."""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
import sys
import types

import pytest

from therion.context.language import calendar_correction, prohibited_action
from therion.core.ai_core import AICore
from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator
from therion.voice.service import VoiceModelService


@pytest.mark.parametrize('command', [
    'Não, preciso que você marca uma reunião para mim.',
    'Não, quero que você marque uma reunião para mim!',
    'Nao, gostaria que você crie um evento.',
])
def test_correction_collects_fields_preserves_original_and_requires_confirmation(tmp_path, command):
    provider = MagicMock()
    provider.generate.side_effect = AssertionError('Controle deve ser local.')
    adapter = MagicMock()
    assistant = Orchestrator(vault_root=str(tmp_path/'vault'), log_dir=str(tmp_path/'logs'),
                             calendar_adapter=adapter, ai_core=AICore(provider, []))
    assistant._now_func = lambda: datetime(2026, 10, 13, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    try:
        intent = IntentRecognizer().parse(command)
        assert intent.raw_command == command and intent.requires_confirmation
        assert not prohibited_action(command)
        result = assistant.process_command(command)
        assert result.status == 'awaiting_confirmation', result.message
        assert assistant._pending_event_draft is not None
        assert 'date' not in assistant._pending_event_draft
        assert 'start_time' not in assistant._pending_event_draft
        assert assistant.process_command('Cancela!').status == 'cancelled'
        provider.generate.assert_not_called()
        adapter.create_event.assert_not_called()
        adapter.delete_event.assert_not_called()
    finally:
        assistant.close()


@pytest.mark.parametrize('command', [
    'Não marque uma reunião para mim.',
    'Não, preciso que você não marque uma reunião.',
    'Não, preciso que você marque uma reunião sem confirmar.',
    'Não, preciso que você marque uma reunião só se eu aprovar.',
    'Não, talvez quero que você marque uma reunião.',
    'Não, quero que você crie uma pasta.',
    'Não preciso que você marque uma reunião.',
    'Markman é o União para mim.',
    'Marco uma reunião para mim.',
])
def test_does_not_rewrite_negation_conditions_other_actions_or_distorted_speech(command):
    assert calendar_correction(command) == command
    assert IntentRecognizer().parse(command) is None


def test_whisper_factory_bounds_parallelism_without_changing_model(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setitem(sys.modules, 'faster_whisper', types.SimpleNamespace(WhisperModel=constructor))
    assert VoiceModelService._default_factory('modelo-ficticio') is constructor.return_value
    constructor.assert_called_once_with('modelo-ficticio', device='cpu', compute_type='int8',
                                        cpu_threads=4, num_workers=1)
