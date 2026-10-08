"""Pedidos explícitos não dependem da classificação probabilística do modelo."""
from unittest.mock import Mock

import pytest

from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse, PlanContent, PlanSection, plan_blocks
from therion.core.orchestrator import Orchestrator

REQUEST = ("Monte um plano de duas horas para estudar Circuitos Lógicos e Álgebra Linear, "
           "em nível iniciante, incluindo pausas. Trate as disciplinas separadamente, "
           "sem criar conexões entre elas. Indique atividade, exercício e objetivo.")


def test_explicit_request_generates_content_instead_of_promise(tmp_path):
    provider = Mock()
    provider.generate.return_value = AIResponse(type="chat", message="Vou montar um plano.")
    provider.generate_plan.return_value = PlanContent(sections=[
        PlanSection("Estudo" if k == "study" else "Pausa", "Exercícios", t, k)
        for k, t in plan_blocks(120)
    ])
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.ai_core = AICore(provider, [])
    orch.executor = Mock()
    result = orch.process_command(REQUEST)
    assert result.plan_candidate_id is not None
    assert "27 minutos" in result.message and "Exercícios" in result.message
    provider.generate.assert_not_called()
    assert provider.generate_plan.call_args.kwargs["message"] == REQUEST
    assert orch.executor.mock_calls == []


def test_continuation_preserves_request_and_duration():
    provider = Mock()
    provider.generate_plan.return_value = PlanContent(sections=[PlanSection("Estudo", "Exercícios", 150)])
    context = {"recent_turns": [
        {"role": "user", "text": REQUEST},
        {"role": "therion", "text": "Entendido! Vou montar um plano detalhado."},
    ]}
    core = AICore(provider, [])
    assert core.classify_detailed("pode mandar", context).response.type == "plan_request"
    plan, failure = core.generate_plan_detailed("pode mandar", context)
    assert plan is None and failure == "plan_duration_invalid"
    assert provider.generate_plan.call_args.kwargs["message"] == REQUEST
    provider.generate.assert_not_called()


@pytest.mark.parametrize("message", [
    "pode mandar", "sim", "Mostre o último plano", "Não monte um plano",
    'Explique a frase: monte um plano', 'Monte um plano e envie por email',
])
def test_other_messages_continue_through_normal_classification(message):
    provider = Mock()
    provider.generate.return_value = AIResponse(type="chat", message="Resposta normal.")
    AICore(provider, []).classify_detailed(message, {})
    provider.generate.assert_called_once()


def test_interactive_flow_precedes_explicit_plan(tmp_path):
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.ai_core = Mock()
    orch._alias_flow_step = "awaiting_keyword"
    result = orch.process_command(REQUEST)
    assert result.plan_candidate_id is None
    orch.ai_core.assert_not_called()
    assert not orch.ai_core.mock_calls


def test_action_still_requires_confirmation_and_can_be_cancelled(tmp_path):
    orch = Orchestrator(simulate=True, log_dir=str(tmp_path))
    orch.ai_core = Mock()
    result = orch.process_command("Abra o Obsidian.")
    assert result.status == "awaiting_confirmation"
    assert orch.confirm_and_execute(result.plan, False).status == "cancelled"
    assert not orch.ai_core.mock_calls
