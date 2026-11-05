from unittest.mock import MagicMock
import pytest
from therion.voice.echo import strip_spoken_echo_prefix
from tests.test_voice_conversation import window,activate


@pytest.mark.parametrize('text,spoken,expected',[
    ('específico. Procura circuitos lógicos para mim.','Posso sugerir algo específico?',
     'Procura circuitos lógicos para mim.'),
    ('e básicos. Consegue me mandar o que está escrito no prompt do tutor intensivo?',
     'Portas lógicas, tabelas-verdade e circuitos básicos.',
     'Consegue me mandar o que está escrito no prompt do tutor intensivo?'),
    ('Não. Procura circuitos lógicos.','Não.','Não. Procura circuitos lógicos.'),
    ('específico. Abra o Obsidian.','Algo específico.','específico. Abra o Obsidian.'),
    ('específico. sim','Algo específico.','específico. sim'),
    ('específico. Procura circuitos.','Outra resposta.','específico. Procura circuitos.'),
    ('mais. Procura circuitos.','Algo mais?','mais. Procura circuitos.'),
])
def test_echo_filter_only_changes_known_tail_before_read_only_request(text,spoken,expected):
    assert strip_spoken_echo_prefix(text,spoken)==expected


def test_automatic_voice_routes_cleaned_read_only_request(window):
    activate(window)
    window._last_conversation_spoken='Posso sugerir algo específico?'
    window._on_voice_transcribed(window._voice_pipeline.generation,'específico. Procura circuitos lógicos para mim.')
    window._start_command_worker.assert_called_once_with('Procura circuitos lógicos para mim.')


def test_confirmation_bypasses_echo_cleanup(window):
    activate(window)
    plan=object();window._pending_plan=plan;window._conversation_confirmation_plan=plan
    window._last_conversation_spoken='Algo específico.'
    window._handle_confirmation=MagicMock()
    window._on_voice_transcribed(window._voice_pipeline.generation,'específico. sim')
    window._handle_confirmation.assert_called_once_with('específico. sim')
