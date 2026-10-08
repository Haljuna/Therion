"""Planos temporizados: orçamento explícito, pausas e rejeição antes da exibição."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from therion.core.ai_provider import AIResponse, PlanContent, PlanSection, plan_duration_minutes, plan_blocks
from therion.core.ai_provider_ollama import OllamaProvider, PLAN_FORMAT_SCHEMA
from therion.core.ai_core import AICore, FAILURE_PLAN_DURATION, FAILURE_PLAN_CONTENT
from therion.core.orchestrator import Orchestrator


@pytest.mark.parametrize("text, expected", [
    ("Plano de duas horas", 120), ("Plano de 2 horas", 120),
    ("Plano de trinta minutos", 30), ("Plano de 120 minutos", 120),
    ("Plano de cinco horas", 300), ("Plano", None),
    ("Plano de 2 horas e meia", None), ("Plano de 1h30", None),
    ("Plano de 1,5 horas", None), ("Plano de vinte e duas horas", None),
    ("Plano de cerca de duas horas", None), ("Plano entre 1 e 2 horas", None),
    ("Plano de 2 horas e 30 minutos", None),
    ("Plano de 60 minutos. Total exatamente 60 minutos.", 60),
    ("Plano de uma hora. Total sessenta minutos.", 60),
    ("Plano de duas horas. Total 120 minutos.", 120),
    ("Plano de 60 minutos. Total 90 minutos.", None),
])
def test_explicit_duration(text, expected):
    assert plan_duration_minutes(text) == expected


def plan(*times):
    return PlanContent(sections=[PlanSection("Estudo" if i % 2 == 0 else "Pausa", "Conteúdo", t)
                                 for i, t in enumerate(times)])


@pytest.mark.parametrize("times", [(30, 45, 45, 30), (None,), (True, 119), (0, 120), (-5, 125)])
def test_invalid_budget_is_rejected(times):
    provider = Mock()
    provider.generate_plan.return_value = plan(*times)
    result, failure = AICore(provider, []).generate_plan_detailed("Plano de duas horas", {})
    assert result is None and failure == FAILURE_PLAN_DURATION
    provider.generate_plan.assert_called_once()


def test_breaks_count_and_untimed_plan_is_compatible():
    provider = Mock()
    provider.generate_plan.return_value = PlanContent(sections=[
        PlanSection("Estudo" if kind == "study" else "Pausa", "Conteúdo", minutes, kind)
        for kind, minutes in plan_blocks(120)
    ])
    assert AICore(provider, []).generate_plan_detailed("Plano de 120 minutos", {})[1] is None
    provider.generate_plan.return_value = plan(None)
    assert AICore(provider, []).generate_plan_detailed("Plano sem duração", {})[1] is None


def test_timed_schema_is_isolated_and_preserves_context():
    provider = OllamaProvider()
    original = deepcopy(PLAN_FORMAT_SCHEMA)
    ctx = {"recent_turns": [{"role": "user", "text": "Vou estudar Álgebra Linear."}]}
    payload = provider._build_plan_payload("Plano de duas horas", ctx)
    assert "120 minutos" in payload["messages"][0]["content"]
    assert "26, 5, 26, 5, 26, 5, 27" in payload["messages"][0]["content"]
    assert "inclusive nas pausas" in payload["messages"][0]["content"]
    blocks = payload["format"]["properties"]["sections"]["properties"]
    assert blocks["bloco_1"]["properties"]["body"]["minLength"] == 1
    assert "duration_minutes" in blocks["bloco_1"]["required"]
    assert sum(block["properties"]["duration_minutes"]["enum"][0] for block in blocks.values()) == 120
    assert blocks["bloco_6"]["properties"]["block_type"]["enum"] == ["break"]
    assert blocks["bloco_7"]["properties"]["block_type"]["enum"] == ["study"]
    assert payload["messages"][1]["content"] == ctx["recent_turns"][0]["text"]
    assert PLAN_FORMAT_SCHEMA == original
    assert provider._build_plan_payload("Plano", {})["format"] is PLAN_FORMAT_SCHEMA
    assert payload["options"]["num_ctx"] == 2048
    parsed = provider._parse_plan_content('{"sections":[{"heading":"Estudo","body":"Matrizes","duration_minutes":120}]}')
    assert parsed.sections[0].duration_minutes == 120
    assert "120 minutos" in Orchestrator._render_plan_content(parsed)
    named = provider._parse_plan_content('{"sections":{"bloco_2":{"heading":"Pausa","body":"Descanse","duration_minutes":5},"bloco_1":{"heading":"Estudo","body":"Matrizes","duration_minutes":115}}}')
    assert [section.duration_minutes for section in named.sections] == [115, 5]


def test_rejected_plan_is_not_candidate_or_executed(tmp_path):
    provider = Mock()
    provider.generate.return_value = AIResponse(type="plan_request", message="Vou montar.")
    provider.generate_plan.return_value = plan(30, 45, 45, 30)
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.ai_core = AICore(provider, [])
    orch.executor = Mock()
    result = orch.process_command("Monte um plano de duas horas para estudar essas disciplinas.")
    assert result.status == "plan_duration_invalid"
    assert "não somam" in result.message
    assert orch._plan_state.candidate is None
    assert orch.executor.mock_calls == []
    provider.generate_plan.assert_called_once()


def test_empty_break_is_rejected_with_specific_reason():
    provider = Mock()
    provider.generate_plan.return_value = PlanContent(sections=[
        PlanSection("Estudo", "Matrizes", 115), PlanSection("Pausa", "", 5),
    ])
    result, failure = AICore(provider, []).generate_plan_detailed("Plano de duas horas", {})
    assert result is None and failure == FAILURE_PLAN_CONTENT
    provider.generate_plan.assert_called_once()


def test_wrong_types_and_final_break_are_rejected():
    provider = Mock()
    correct = [PlanSection("Estudo" if k == "study" else "Pausa", "Conteúdo", t, k)
               for k, t in plan_blocks(120)]
    swapped = list(correct)
    swapped[5] = PlanSection("Matrizes", "Estudar", 5, "study")
    swapped[6] = PlanSection("Pausa final", "Descansar", 27, "break")
    provider.generate_plan.return_value = PlanContent(sections=swapped)
    assert AICore(provider, []).generate_plan_detailed("Plano de duas horas", {})[1] == "plan_blocks_invalid"
    swapped = list(correct)
    swapped[-1] = PlanSection("Pausa final", "Descansar", 27, "study")
    provider.generate_plan.return_value = PlanContent(sections=swapped)
    assert AICore(provider, []).generate_plan_detailed("Plano de duas horas", {})[1] == "plan_blocks_invalid"
    pause = PlanContent(sections=[PlanSection("Matrizes", "Estudar matrizes", 5, "break")])
    rendered = Orchestrator._render_plan_content(pause)
    assert "Matrizes" not in rendered and "Estudar" not in rendered
    assert "Pausa — 5 minutos" in rendered


PERCENT_REQUEST = (
    "Monte um plano de 60 minutos para estudar porcentagens, em nível iniciante, "
    "incluindo pausas. Trabalhe apenas cálculo de porcentagem de um valor, descontos "
    "e aumentos simples. Em cada bloco de estudo, forneça um exercício com números "
    "concretos e o gabarito explicado. Não inclua juros compostos. O tempo total, "
    "incluindo pausas, deve ser exatamente 60 minutos."
)


def test_repeated_duration_uses_timed_schema_and_rejects_85_minutes(tmp_path):
    assert plan_duration_minutes(PERCENT_REQUEST) == 60
    payload = OllamaProvider()._build_plan_payload(PERCENT_REQUEST, {})
    blocks = payload["format"]["properties"]["sections"]["properties"]
    assert sum(b["properties"]["duration_minutes"]["enum"][0] for b in blocks.values()) == 60
    assert blocks["bloco_6"]["properties"]["block_type"]["enum"] == ["break"]
    provider = Mock()
    provider.generate_plan.return_value = plan(20, 5, 15, 5, 20, 20)
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.ai_core = AICore(provider, [])
    result = orch.process_command(PERCENT_REQUEST)
    assert result.status == "plan_duration_invalid"
    assert result.plan_candidate_id is None
    assert orch._plan_state.candidate is None
    provider.generate.assert_not_called()
    provider.generate_plan.assert_called_once()

