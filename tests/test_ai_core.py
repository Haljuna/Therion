"""Testes da IA central A1 - AICore + AIProvider + AIResponse."""

import unittest
from typing import Optional

from therion.core.ai_core import (
    AICore,
    FAILURE_INVALID_RESPONSE,
    FAILURE_PROVIDER_TIMEOUT,
    FAILURE_PROVIDER_UNAVAILABLE,
    FAILURE_REJECTED_BY_POLICY,
    validate_plan_content,
)
from therion.core.ai_provider import (
    AIProvider,
    AIResponse,
    NON_EXECUTABLE_TYPES,
    PLAN_REFERENCE,
    PLAN_REFERENCE_SELECTORS,
    PLAN_REQUEST,
    PlanContent,
    PlanSection,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from therion.core.orchestrator import Orchestrator


class FakeAIProvider(AIProvider):

    def __init__(self, response=None, error=False):
        self._response = response
        self._error = error
        self.call_count = 0
        self.last_message = None
        self.last_context = None

    def generate(self, message, context, available_intents):
        self.call_count += 1
        self.last_message = message
        self.last_context = context
        if self._error:
            raise RuntimeError("Provider indisponivel")
        if self._response is None:
            raise RuntimeError("Sem resposta configurada")
        return self._response

    def generate_plan(self, message, context):
        raise NotImplementedError


class TestAICoreValidation(unittest.TestCase):

    def setUp(self):
        self.intents = [
            "abrir aplicativo",
            "listar aliases",
            "buscar segundo cérebro",
            "calendário hoje",
            "criar evento calendário",
        ]
        self.provider = FakeAIProvider()
        self.core = AICore(provider=self.provider, available_intents=self.intents)

    def test_chat_valid(self):
        self.provider._response = AIResponse(type="chat", message="Ola!")
        result = self.core.classify("oi", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.type, "chat")
        self.assertEqual(result.message, "Ola!")

    def test_action_valid(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments={}, message="Consultando agenda")
        result = self.core.classify("o que tenho hoje?", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.type, "action")
        self.assertEqual(result.intent, "calendário hoje")
        self.assertEqual(result.message, "Consultando agenda")

    def test_clarification_valid(self):
        self.provider._response = AIResponse(type="clarification", message="Qual aplicativo?")
        result = self.core.classify("abre aquilo", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.type, "clarification")

    def test_invalid_type_rejected(self):
        self.provider._response = AIResponse(type="invalido")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_without_intent_rejected(self):
        self.provider._response = AIResponse(type="action")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_unknown_intent_rejected(self):
        self.provider._response = AIResponse(type="action", intent="executar powershell", arguments={})
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_chat_without_message_rejected(self):
        self.provider._response = AIResponse(type="chat")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_chat_empty_message_rejected(self):
        self.provider._response = AIResponse(type="chat", message="  ")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_provider_exception_returns_none(self):
        core = AICore(provider=FakeAIProvider(error=True), available_intents=[])
        result = core.classify("teste", {})
        self.assertIsNone(result)

    def test_none_response_returns_none(self):
        core = AICore(provider=FakeAIProvider(response=None), available_intents=[])
        result = core.classify("teste", {})
        self.assertIsNone(result)

    def test_clarification_without_message_rejected(self):
        self.provider._response = AIResponse(type="clarification")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_arguments_must_be_dict(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments="invalido")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_chat_with_nonnull_intent_rejected(self):
        self.provider._response = AIResponse(type="chat", message="Ola!", intent="abrir aplicativo")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_clarification_with_nonnull_intent_rejected(self):
        self.provider._response = AIResponse(type="clarification", message="Qual aplicativo?", intent="abrir aplicativo")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_chat_with_nonempty_arguments_rejected(self):
        self.provider._response = AIResponse(type="chat", message="Ola!", arguments={"app": "Obsidian"})
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_clarification_with_nonempty_arguments_rejected(self):
        self.provider._response = AIResponse(type="clarification", message="Qual aplicativo?", arguments={"app": "Obsidian"})
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_abrir_aplicativo_valid(self):
        self.provider._response = AIResponse(type="action", intent="abrir aplicativo", arguments={"target": "Obsidian"}, message="Abrindo")
        result = self.core.classify("abra o Obsidian", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments, {"target": "Obsidian"})

    def test_action_listar_aliases_valid(self):
        self.provider._response = AIResponse(type="action", intent="listar aliases", arguments={}, message="Listando")
        result = self.core.classify("liste os aliases", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments, {})

    def test_action_buscar_segundo_cerebro_valid(self):
        self.provider._response = AIResponse(type="action", intent="buscar segundo cérebro", arguments={"term": "arquitetura"}, message="Buscando")
        result = self.core.classify("procure notas", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments, {"term": "arquitetura"})

    def test_action_calendario_hoje_valid(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments={}, message="Consultando")
        result = self.core.classify("agenda hoje", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments, {})

    def test_action_criar_evento_calendario_valid(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Reunião", "date": "2026-09-17", "start_time": "14:00"},
            message="Criando evento",
        )
        result = self.core.classify("novo evento", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments["title"], "Reunião")

    def test_action_extra_key_rejected(self):
        self.provider._response = AIResponse(type="action", intent="abrir aplicativo", arguments={"target": "Obsidian", "extra": 1}, message="Abrindo")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(type="action", intent="listar aliases", arguments={"extra": 1}, message="Listando")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "R", "date": "2026-09-17", "start_time": "14:00", "extra": 1},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_missing_required_key_rejected(self):
        self.provider._response = AIResponse(type="action", intent="abrir aplicativo", arguments={}, message="Abrindo")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(type="action", intent="buscar segundo cérebro", arguments={}, message="Buscando")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "R", "date": "2026-09-17"},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_empty_string_rejected(self):
        self.provider._response = AIResponse(type="action", intent="abrir aplicativo", arguments={"target": "   "}, message="Abrindo")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(type="action", intent="buscar segundo cérebro", arguments={"term": ""}, message="Buscando")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "", "date": "2026-09-17", "start_time": "14:00"},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "R", "date": "  ", "start_time": "14:00"},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "R", "date": "2026-09-17", "start_time": ""},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_duration_minutes_valid_accepted(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Aula", "date": "2026-09-17", "start_time": "14:00", "duration_minutes": 45},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.arguments["duration_minutes"], 45)

    def test_action_duration_minutes_zero_rejected(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Aula", "date": "2026-09-17", "start_time": "14:00", "duration_minutes": 0},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_duration_minutes_negative_rejected(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Aula", "date": "2026-09-17", "start_time": "14:00", "duration_minutes": -15},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_duration_minutes_string_rejected(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Aula", "date": "2026-09-17", "start_time": "14:00", "duration_minutes": "45"},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_duration_minutes_bool_rejected(self):
        self.provider._response = AIResponse(
            type="action",
            intent="criar evento calendário",
            arguments={"title": "Aula", "date": "2026-09-17", "start_time": "14:00", "duration_minutes": True},
            message="Criando",
        )
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_intent_outside_allowlist_rejected(self):
        custom_core = AICore(provider=self.provider, available_intents=["executar powershell"])
        self.provider._response = AIResponse(type="action", intent="executar powershell", arguments={}, message="Executando")
        result = custom_core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_empty_message_rejected(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments={}, message="")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_whitespace_message_rejected(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments={}, message="   ")
        result = self.core.classify("teste", {})
        self.assertIsNone(result)

    def test_action_valid_message_accepted(self):
        self.provider._response = AIResponse(type="action", intent="calendário hoje", arguments={}, message="Consultando agenda")
        result = self.core.classify("teste", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.message, "Consultando agenda")


class TestAICoreOrchestratorIntegration(unittest.TestCase):

    def test_A_chat_returns_direct_response(self):
        provider = FakeAIProvider(AIResponse(type="chat", message="Um transformador e um dispositivo..."))
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        orch = Orchestrator(simulate=True, ai_core=core)
        result = orch.process_command("Me explica o que e um transformador.")
        self.assertEqual(result.status, "success")
        self.assertIn("transformador", result.message)
        self.assertIsNone(orch.memory.last_intent)
        self.assertEqual(provider.call_count, 1)

    def test_B_action_calendar_today(self):
        provider = FakeAIProvider(AIResponse(type="action", intent="calendário hoje", arguments={}, message="Consultando hoje"))
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        orch = Orchestrator(simulate=True, ai_core=core)
        result = orch.process_command("Tenho algum compromisso hoje?")
        self.assertEqual(result.status, "success")
        self.assertIn("Calendário não disponível", result.message)
        self.assertEqual(orch.memory.last_intent, "calendário hoje")

    def test_C_clarification_returns_success(self):
        provider = FakeAIProvider(AIResponse(type="clarification", message="Qual aplicativo voce gostaria de abrir?"))
        core = AICore(provider=provider, available_intents=["abrir aplicativo"])
        orch = Orchestrator(simulate=True, ai_core=core)
        result = orch.process_command("quero comer algo")
        self.assertEqual(result.status, "success")
        self.assertIn("Qual aplicativo", result.message)
        self.assertIsNone(orch.memory.last_intent)

    def test_D_provider_failure_falls_back(self):
        provider = FakeAIProvider(error=True)
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        orch = Orchestrator(simulate=True, ai_core=core)
        result = orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Obsidian", result.message)

    def test_E_invalid_intent_falls_back(self):
        provider = FakeAIProvider(AIResponse(type="action", intent="executar powershell", arguments={"cmd": "x"}, message="Executando"))
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        orch = Orchestrator(simulate=True, ai_core=core)
        result = orch.process_command("some texto qualquer")
        self.assertEqual(result.status, "ai_invalid_response")

    def test_F_pending_flow_priority(self):
        orch_no_ai = Orchestrator(simulate=True, ai_core=None)
        orch_no_ai.process_command("crie um evento")
        provider = FakeAIProvider(AIResponse(type="action", intent="calendário hoje", arguments={}, message="Consultando hoje"))
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        orch_no_ai.ai_core = core
        provider.call_count = 0
        result = orch_no_ai.process_command("sim")
        self.assertEqual(provider.call_count, 0)
        self.assertIn(result.status, ("success", "execution_failed", "awaiting_confirmation"))

    def test_G_no_ai_core_uses_legacy(self):
        orch = Orchestrator(simulate=True, ai_core=None)
        result = orch.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Obsidian", result.message)

    def test_H_context_sent_to_provider(self):
        provider = FakeAIProvider(AIResponse(type="chat", message="ok"))
        core = AICore(provider=provider, available_intents=[])
        orch = Orchestrator(simulate=True, ai_core=core)
        orch.process_command("Therion, abra o Obsidian")
        orch.process_command("teste de contexto")
        ctx = provider.last_context
        self.assertIsNotNone(ctx)
        self.assertIn("recent_turns", ctx)
        self.assertIn("last_intent", ctx)
        self.assertIn("last_target", ctx)
        self.assertIn("last_status", ctx)
        self.assertIn("last_result_summary", ctx)
        self.assertLessEqual(len(ctx["recent_turns"]), 5)


class TestValidatePlanContent(unittest.TestCase):

    def test_valid_without_title(self):
        plan = PlanContent(
            sections=[PlanSection(heading="Bloco 1", body="Conteudo do bloco.")],
        )
        self.assertTrue(validate_plan_content(plan))

    def test_valid_with_title(self):
        plan = PlanContent(
            sections=[PlanSection(heading="Bloco 1", body="Conteudo do bloco.")],
            title="Plano de estudo",
        )
        self.assertTrue(validate_plan_content(plan))

    def test_non_plancontent_rejected(self):
        self.assertFalse(validate_plan_content("não é plano"))
        self.assertFalse(validate_plan_content(None))
        self.assertFalse(validate_plan_content({}))

    def test_empty_sections_rejected(self):
        plan = PlanContent(sections=[])
        self.assertFalse(validate_plan_content(plan))

    def test_tuple_sections_rejected(self):
        plan = PlanContent(
            sections=(PlanSection(heading="Bloco 1", body="Conteudo"),)
        )
        self.assertFalse(validate_plan_content(plan))

    def test_non_plansection_item_rejected(self):
        plan = PlanContent(sections=["não é seção"])
        self.assertFalse(validate_plan_content(plan))

    def test_blank_heading_rejected(self):
        plan = PlanContent(
            sections=[PlanSection(heading="   ", body="Conteudo")],
        )
        self.assertFalse(validate_plan_content(plan))

    def test_non_string_heading_rejected(self):
        plan = PlanContent(
            sections=[PlanSection(heading=123, body="Conteudo")],
        )
        self.assertFalse(validate_plan_content(plan))

    def test_blank_body_rejected(self):
        plan = PlanContent(
            sections=[PlanSection(heading="Bloco 1", body="  \n ")],
        )
        self.assertFalse(validate_plan_content(plan))

    def test_non_string_body_rejected(self):
        plan = PlanContent(
            sections=[PlanSection(heading="Bloco 1", body=42)],
        )
        self.assertFalse(validate_plan_content(plan))

    def test_non_string_title_rejected(self):
        plan = PlanContent(
            sections=[PlanSection(heading="Bloco 1", body="Conteudo")],
            title=123,
        )
        self.assertFalse(validate_plan_content(plan))

class TestPlanRouteClassification(unittest.TestCase):

    def setUp(self):
        self.intents = [
            "abrir aplicativo",
            "listar aliases",
            "buscar segundo cérebro",
            "calendário hoje",
            "criar evento calendário",
        ]
        self.provider = FakeAIProvider()
        self.core = AICore(provider=self.provider, available_intents=self.intents)

    def test_non_executable_types_constant(self):
        self.assertEqual(NON_EXECUTABLE_TYPES, {PLAN_REQUEST, PLAN_REFERENCE})
        self.assertIn(PLAN_REQUEST, AICore.VALID_TYPES)
        self.assertIn(PLAN_REFERENCE, AICore.VALID_TYPES)

    def test_closed_reference_set(self):
        self.assertEqual(
            PLAN_REFERENCE_SELECTORS,
            {"first", "second", "last", "previous", "same"},
        )

    def test_plan_request_valid(self):
        self.provider._response = AIResponse(
            type=PLAN_REQUEST, message="Vou montar um plano."
        )
        result = self.core.classify("monte um plano de estudo", {})
        self.assertIsNotNone(result)
        self.assertEqual(result.type, PLAN_REQUEST)
        self.assertIsNone(result.intent)
        self.assertEqual(result.arguments, {})

    def test_plan_request_with_intent_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REQUEST,
            intent="abrir aplicativo",
            arguments={"target": "Obsidian"},
            message="Plano.",
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_request_with_nonempty_arguments_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REQUEST, arguments={"reference": "first"}, message="Plano."
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_request_with_nondict_arguments_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REQUEST, arguments="first", message="Plano."
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_request_without_message_rejected(self):
        self.provider._response = AIResponse(type=PLAN_REQUEST)
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_valid_for_each_selector(self):
        for selector in PLAN_REFERENCE_SELECTORS:
            with self.subTest(selector=selector):
                self.provider._response = AIResponse(
                    type=PLAN_REFERENCE,
                    arguments={"reference": selector},
                    message="Aqui esta o plano.",
                )
                result = self.core.classify("mostre o plano", {})
                self.assertIsNotNone(result)
                self.assertEqual(result.type, PLAN_REFERENCE)
                self.assertIsNone(result.intent)
                self.assertEqual(result.arguments, {"reference": selector})

    def test_plan_reference_invalid_selector_rejected(self):
        for selector in ("third", "1", "FIRST", "previous plan", "", "all"):
            with self.subTest(selector=selector):
                self.provider._response = AIResponse(
                    type=PLAN_REFERENCE,
                    arguments={"reference": selector},
                    message="Plano.",
                )
                self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_missing_key_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE, arguments={}, message="Plano."
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_missing_key_uses_explicit_current_message(self):
        cases = {
            "Mostre o primeiro plano desta sessão.": "first",
            "Mostre o segundo plano desta sessão.": "second",
            "Exiba o último plano.": "last",
            "Mostre o plano anterior desta sessão.": "previous",
            "Mande esse mesmo plano inteiro novamente.": "same",
        }
        for message, selector in cases.items():
            with self.subTest(message=message):
                original = AIResponse(
                    type=PLAN_REFERENCE, arguments={}, message="Vou consultar o plano."
                )
                self.provider._response = original
                result = self.core.classify(message, {})
                self.assertIsNotNone(result)
                self.assertEqual(result.arguments, {"reference": selector})
                self.assertEqual(original.arguments, {})

    def test_plan_reference_missing_key_does_not_guess_from_history(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE, arguments={}, message="Vou consultar o plano."
        )
        context = {"recent_turns": [{"role": "user", "text": "segundo plano"}]}
        self.assertIsNone(self.core.classify("Mostre o plano.", context))

    def test_plan_reference_missing_key_rejects_multiple_selectors(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE, arguments={}, message="Vou consultar o plano."
        )
        self.assertIsNone(self.core.classify("Mostre o primeiro e o segundo plano.", {}))

    def test_plan_reference_extra_key_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE,
            arguments={"reference": "first", "extra": 1},
            message="Plano.",
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_non_string_selector_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE, arguments={"reference": 1}, message="Plano."
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_nondict_arguments_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE, arguments="first", message="Plano."
        )
        self.assertIsNone(self.core.classify("plano", {}))

    def test_plan_reference_with_intent_rejected(self):
        self.provider._response = AIResponse(
            type=PLAN_REFERENCE,
            intent="criar evento calendário",
            arguments={"reference": "last"},
            message="Plano.",
        )
        self.assertIsNone(self.core.classify("plano", {}))


class _PlanProvider(AIProvider):
    """Fake de provider para testar generate_plan_detailed."""

    def __init__(self, plan=None, error=None):
        self._plan = plan
        self._error = error

    def generate(self, message, context, available_intents):
        raise AssertionError("generate nao deve ser chamado aqui")

    def generate_plan(self, message, context):
        if self._error is not None:
            raise self._error
        return self._plan


def _valid_plan() -> PlanContent:
    return PlanContent(
        sections=[PlanSection(heading="Bloco 1", body="Conteudo do bloco.")]
    )


class TestGeneratePlanDetailed(unittest.TestCase):

    def _core(self, provider: _PlanProvider) -> AICore:
        return AICore(provider=provider, available_intents=[])

    def test_valid_plan_returns_plan_and_none(self):
        plan = _valid_plan()
        result, failure = self._core(_PlanProvider(plan=plan)).generate_plan_detailed(
            "monte um plano", {}
        )
        self.assertIs(result, plan)
        self.assertIsNone(failure)

    def test_timeout_maps_to_provider_timeout(self):
        provider = _PlanProvider(error=ProviderTimeoutError())
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_PROVIDER_TIMEOUT)

    def test_transport_maps_to_provider_unavailable(self):
        provider = _PlanProvider(error=ProviderTransportError())
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_PROVIDER_UNAVAILABLE)

    def test_response_error_maps_to_invalid_response(self):
        provider = _PlanProvider(error=ProviderResponseError())
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_INVALID_RESPONSE)

    def test_none_response_maps_to_invalid_response(self):
        provider = _PlanProvider(plan=None)
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_INVALID_RESPONSE)

    def test_invalid_structure_maps_to_rejected_by_policy(self):
        provider = _PlanProvider(plan=PlanContent(sections=[]))
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_REJECTED_BY_POLICY)

    def test_generic_exception_maps_to_provider_unavailable(self):
        provider = _PlanProvider(error=RuntimeError("boom"))
        result, failure = self._core(provider).generate_plan_detailed("plano", {})
        self.assertIsNone(result)
        self.assertEqual(failure, FAILURE_PROVIDER_UNAVAILABLE)
