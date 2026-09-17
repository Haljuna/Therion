"""Testes da IA central A1 - AICore + AIProvider + AIResponse."""

import unittest
from typing import Optional

from therion.core.ai_core import AICore
from therion.core.ai_provider import AIProvider, AIResponse
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
        result = orch.process_command("Abre aquilo.")
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
        self.assertEqual(result.status, "unknown_intent")

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
