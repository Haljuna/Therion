"""Regressões de buscas ditadas e capacidades da instalação atual."""
from unittest.mock import MagicMock

import pytest

from therion.core.ai_provider import AIResponse
from therion.core.ai_core import ClassifyOutcome
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator


@pytest.mark.parametrize("command,term", [
    ("procure no segundo cerebro prova", "prova"),
    ("Procura no Segundo Cérebro prova.", "prova"),
    ("Procura no Segundo Cérebro, prova!", "prova"),
    ("Procure, no Segundo Cérebro, prova.", "prova"),
    ("Procure no Segundo Cérebro Engenharia Econômica.", "Engenharia Econômica"),
    ("Procure no Segundo Cérebro relatório.md.", "relatório.md"),
])
def test_search_sentence_punctuation(tmp_path, command, term):
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.second_brain.search_notes = MagicMock(return_value=[])
    orch.ai_core = MagicMock()
    result = orch.process_command(command)
    assert orch.second_brain.search_notes.call_args.args[0].casefold() == term.casefold()
    assert result.status == "success"
    orch.ai_core.classify_detailed.assert_not_called()


def test_ai_search_also_normalizes_term(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path), ai_core=MagicMock())
    orch.ai_core.classify_detailed.return_value = ClassifyOutcome(response=AIResponse(
        type="action", message="Busca", intent="buscar segundo cérebro", arguments={"term": "prova!"},
    ))
    orch.second_brain.search_notes = MagicMock(return_value=[])
    orch.process_command("Ache minhas notas de prova")
    assert orch.second_brain.search_notes.call_args.args[0] == "prova"


@pytest.mark.parametrize("simulate,calendar", [(True, None), (False, MagicMock())])
def test_capabilities_reflect_runtime_and_do_not_execute(tmp_path, simulate, calendar):
    orch = Orchestrator(simulate=simulate, log_dir=str(tmp_path), calendar_adapter=calendar,
                        ai_core=MagicMock())
    orch.executor = MagicMock()
    for question in ["O que você pode fazer?", "Eu queria saber o que você pode fazer.",
                     "Quais são suas capacidades?", "Você consegue abrir algum aplicativo?",
                     "Você pode abrir programas?"]:
        result = orch.process_command(question)
        assert result.status == "success"
        assert "Segundo Cérebro" in result.message
        assert result.speech_message != result.message
        assert 'notas autorizadas' in result.speech_message
        assert 'confirmação' in result.speech_message
        if simulate:
            assert "não abro o aplicativo de verdade" in result.message
            assert "não posso consultar nem criar eventos agora" in result.message
            assert 'não os abro de verdade' in result.speech_message
            assert 'calendário está indisponível' in result.speech_message
        else:
            assert "confirmação antes da execução" in result.message
            assert "depende da conexão" in result.message
            assert 'depende da conexão e da autorização' in result.speech_message
    orch.executor.assert_not_called()
    orch.ai_core.classify_detailed.assert_not_called()
    if calendar is not None:
        assert calendar.mock_calls == []
    context = orch._build_ai_context("Você consegue abrir o Obsidian?")
    payload = OllamaProvider()._build_payload("Você consegue abrir o Obsidian?", context, [])
    assert context["capabilities_summary"] in payload["messages"][0]["content"]


def test_pending_flow_precedes_capabilities(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path))
    orch._alias_flow_step = "awaiting_keyword"
    result = orch.process_command("O que você pode fazer?")
    assert result.message != orch._capabilities_summary()


@pytest.mark.parametrize('command', ['Abra o Chrome.', 'Você consegue abrir o Obsidian?',
    'Não abra nenhum aplicativo.', 'Abra um aplicativo chamado Discord.'])
def test_app_capability_question_does_not_capture_named_or_negative_requests(command):
    from therion.context.conversation_frame import capabilities_request
    assert not capabilities_request(command)


def test_no_ai_capability_is_not_advertised(tmp_path):
    orch = Orchestrator(log_dir=str(tmp_path))
    result = orch.process_command("O que você consegue fazer?")
    assert "desabilitada" in result.message
    assert 'modelo local está desativada' in result.speech_message
