"""Testes unitários isolados para OllamaProvider (A2.5-R)."""

import inspect
import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from therion.core.ai_provider import (
    AIResponse,
    PlanContent,
    PlanSection,
    ProviderResponseError,
)
from therion.core.ai_provider_ollama import (
    ENDPOINT,
    FORMAT_SCHEMA,
    OllamaProvider,
    PLAN_FORMAT_SCHEMA,
    PLAN_SYSTEM_PROMPT,
    PLAN_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
)


class _MockHTTPResponse:
    """Mock para resposta de urllib com suporte a gerenciador de contexto."""

    def __init__(self, body_bytes: bytes, status: int = 200):
        self._body = body_bytes
        self.status = status
        self.code = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def _make_http_response(body_dict: dict, status: int = 200) -> _MockHTTPResponse:
    body_bytes = json.dumps(body_dict).encode("utf-8")
    return _MockHTTPResponse(body_bytes=body_bytes, status=status)


class TestOllamaProviderIsolated(unittest.TestCase):
    """Testes sem chamada de rede para OllamaProvider."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=30)

    def test_endpoint_is_loopback(self):
        """Endpoint deve ser fixo em 127.0.0.1:11434/api/chat."""
        self.assertEqual(ENDPOINT, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(self.provider.ENDPOINT, "http://127.0.0.1:11434/api/chat")

    def test_proxy_explicitly_disabled(self):
        """Proxy deve ser explicitamente desabilitado com ProxyHandler({})."""
        with patch("urllib.request.build_opener") as mock_build_opener:
            OllamaProvider()
            mock_build_opener.assert_called_once()
            args, _ = mock_build_opener.call_args
            proxy_handlers = [arg for arg in args if isinstance(arg, urllib.request.ProxyHandler)]
            self.assertEqual(len(proxy_handlers), 1)
            self.assertEqual(proxy_handlers[0].proxies, {})

    def test_payload_contains_required_fields(self):
        """Payload deve conter stream: false, format, temperature: 0 e num_ctx: 4096."""
        payload = self.provider._build_payload("Olá", {}, ["calendário hoje"])
        self.assertEqual(payload["model"], "qwen3:4b-instruct")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_ctx"], 4096)

        # Verificação do format schema
        fmt = payload["format"]
        self.assertEqual(fmt["type"], "object")
        self.assertFalse(fmt["additionalProperties"])
        self.assertEqual(fmt["required"], ["type", "message", "intent", "arguments"])
        self.assertEqual(
            fmt["properties"]["type"]["enum"],
            ["chat", "clarification", "action", "plan_request", "plan_reference", "context_request"],
        )

    def test_chat_valid_returns_ai_response(self):
        """Chat válido retorna AIResponse correspondente."""
        raw_inner = json.dumps({
            "type": "chat",
            "message": "Olá! Como posso ajudar?",
            "intent": None,
            "arguments": {},
        })
        external_body = {"message": {"content": raw_inner}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            result = self.provider.generate("oi", {}, [])

        self.assertIsInstance(result, AIResponse)
        self.assertEqual(result.type, "chat")
        self.assertEqual(result.message, "Olá! Como posso ajudar?")
        self.assertIsNone(result.intent)
        self.assertEqual(result.arguments, {})

    def test_action_valid_returns_ai_response(self):
        """Action válida retorna AIResponse correspondente."""
        raw_inner = json.dumps({
            "type": "action",
            "message": "Abrindo Obsidian",
            "intent": "abrir aplicativo",
            "arguments": {"target": "Obsidian"},
        })
        external_body = {"message": {"content": raw_inner}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            result = self.provider.generate("abra o obsidian", {}, ["abrir aplicativo"])

        self.assertIsInstance(result, AIResponse)
        self.assertEqual(result.type, "action")
        self.assertEqual(result.message, "Abrindo Obsidian")
        self.assertEqual(result.intent, "abrir aplicativo")
        self.assertEqual(result.arguments, {"target": "Obsidian"})

    def test_plan_request_valid_returns_ai_response(self):
        """Plan request válido retorna AIResponse correspondente."""
        raw_inner = json.dumps({
            "type": "plan_request",
            "message": "Vou montar o plano de estudo.",
            "intent": None,
            "arguments": {},
        })
        external_body = {"message": {"content": raw_inner}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            result = self.provider.generate("monte um plano de estudo", {}, [])

        self.assertIsInstance(result, AIResponse)
        self.assertEqual(result.type, "plan_request")
        self.assertEqual(result.message, "Vou montar o plano de estudo.")
        self.assertIsNone(result.intent)
        self.assertEqual(result.arguments, {})

    def test_plan_reference_valid_returns_ai_response(self):
        """Plan reference válido retorna AIResponse correspondente."""
        raw_inner = json.dumps({
            "type": "plan_reference",
            "message": "Aqui está o primeiro plano gerado:",
            "intent": None,
            "arguments": {"reference": "first"},
        })
        external_body = {"message": {"content": raw_inner}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            result = self.provider.generate("mostre o primeiro plano", {}, [])

        self.assertIsInstance(result, AIResponse)
        self.assertEqual(result.type, "plan_reference")
        self.assertEqual(result.message, "Aqui está o primeiro plano gerado:")
        self.assertIsNone(result.intent)
        self.assertEqual(result.arguments, {"reference": "first"})

    def test_payload_contains_plan_reference_mandatory_reference_instruction(self):
        """Payload deve instruir que arguments para plan_reference nunca pode ser vazio e exige reference."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("plan_reference", system_content)
        self.assertIn("NUNCA pode ser vazio ({})", system_content)
        self.assertIn('"reference"', system_content)

    def test_payload_keeps_second_reference_even_when_unavailable(self):
        """A existência do segundo plano é decidida pelo Orchestrator, não pelo classificador."""
        payload = self.provider._build_payload("Mostre o segundo plano desta sessão", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("Não decida se o plano existe na sessão", system_content)
        self.assertIn("O Orchestrator verifica a existência", system_content)
        example_line = next(
            line for line in system_content.splitlines()
            if 'Usuário: "Mostre o segundo plano desta sessão"' in line
        )
        self.assertIn('"type":"plan_reference"', example_line)
        self.assertIn('"arguments":{"reference":"second"}', example_line)

    def test_raw_json_invalid_rejected(self):
        """JSON bruto inválido deve lançar ValueError."""
        external_body = {"message": {"content": "{ json invalido sem fechar"}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

    def test_markdown_fence_rejected(self):
        """Cerca Markdown não deve ser removida e deve causar ValueError."""
        content_with_fence = '```json\n{"type": "chat", "message": "ola", "intent": null, "arguments": {}}\n```'
        external_body = {"message": {"content": content_with_fence}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

    def test_extra_root_key_rejected(self):
        """Chave raiz extra além das quatro obrigatórias deve lançar ValueError."""
        raw_inner = json.dumps({
            "type": "chat",
            "message": "ola",
            "intent": None,
            "arguments": {},
            "extra_field": "invalido",
        })
        external_body = {"message": {"content": raw_inner}}

        with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

    def test_empty_message_rejected(self):
        """Message vazia ou somente com espaços deve lançar ValueError."""
        for empty in ["", "   "]:
            raw_inner = json.dumps({
                "type": "chat",
                "message": empty,
                "intent": None,
                "arguments": {},
            })
            external_body = {"message": {"content": raw_inner}}

            with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
                with self.assertRaises(ValueError):
                    self.provider.generate("teste", {}, [])

    def test_arguments_null_or_non_object_rejected(self):
        """Arguments null ou que não seja dicionário deve lançar ValueError."""
        for invalid_args in [None, "string", [1, 2], 123]:
            raw_inner = json.dumps({
                "type": "chat",
                "message": "ola",
                "intent": None,
                "arguments": invalid_args,
            })
            external_body = {"message": {"content": raw_inner}}

            with patch.object(self.provider._opener, "open", return_value=_make_http_response(external_body)):
                with self.assertRaises(ValueError):
                    self.provider.generate("teste", {}, [])

    def test_external_response_without_valid_message_content_rejected(self):
        """Resposta externa sem estrutura correta de message.content deve lançar ValueError."""
        # Sem campo message
        with patch.object(self.provider._opener, "open", return_value=_make_http_response({"erro": "sem message"})):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

        # message não é dict
        with patch.object(self.provider._opener, "open", return_value=_make_http_response({"message": "nao dict"})):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

        # message.content não é string
        with patch.object(self.provider._opener, "open", return_value=_make_http_response({"message": {"content": 123}})):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

        # Resposta externa nem é JSON
        bad_json_resp = _MockHTTPResponse(body_bytes=b"{ nao e json valido", status=200)
        with patch.object(self.provider._opener, "open", return_value=bad_json_resp):
            with self.assertRaises(ValueError):
                self.provider.generate("teste", {}, [])

    def test_http_non_200_rejected(self):
        """Resposta HTTP com status diferente de 200 deve lançar RuntimeError."""
        body = {"message": {"content": "{}"}}
        resp = _make_http_response(body, status=500)

        with patch.object(self.provider._opener, "open", return_value=resp):
            with self.assertRaises(RuntimeError):
                self.provider.generate("teste", {}, [])

    def test_transport_or_timeout_error_propagated(self):
        """Erros de conexão ou timeout devem resultar em RuntimeError."""
        # URLError (ex: conexão recusada)
        with patch.object(self.provider._opener, "open", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(RuntimeError):
                self.provider.generate("teste", {}, [])

        # TimeoutError
        with patch.object(self.provider._opener, "open", side_effect=TimeoutError("Timed out")):
            with self.assertRaises(RuntimeError):
                self.provider.generate("teste", {}, [])

    def test_payload_contains_classify_actions_instruction(self):
        """Payload deve conter instrução de classificar actions permitidas."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("classificador central", system_content.lower())
        self.assertIn("action", system_content)
        self.assertIn(" Você é apenas um classificador", system_content)

    def test_payload_contains_orchestrator_executes_instruction(self):
        """Payload deve conter instrução de que o Orchestrator executa."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("Orchestrator", system_content)
        self.assertIn("executa", system_content)

    def test_payload_contains_action_examples(self):
        """Payload deve conter as duas actions de exemplo."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        # Exemplo de busca no Segundo Cérebro
        self.assertIn("buscar segundo cérebro", system_content)
        self.assertIn("tarefas pendentes", system_content)
        # Exemplo de abrir aplicativo
        self.assertIn("abrir aplicativo", system_content)
        self.assertIn("Obsidian", system_content)

    def test_payload_contains_accurate_canonical_strings(self):
        """Payload deve conter strings canônicas com acentos corretos."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("buscar segundo cérebro", system_content)
        self.assertIn("calendário hoje", system_content)
        self.assertIn("criar evento calendário", system_content)
        self.assertIn("abrir aplicativo", system_content)
        self.assertIn("listar aliases", system_content)

    def test_payload_contains_all_five_action_examples(self):
        """Payload deve conter exemplos completos de arguments para todas as cinco actions."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        # abrir aplicativo com target
        self.assertIn('"abrir aplicativo"', system_content)
        self.assertIn('"target":"Obsidian"', system_content)
        # listar aliases sem arguments
        self.assertIn('"listar aliases"', system_content)
        self.assertIn('"arguments":{}', system_content)
        # buscar segundo cérebro com term
        self.assertIn('"buscar segundo cérebro"', system_content)
        self.assertIn('"term":"tarefas pendentes"', system_content)
        # calendário hoje sem arguments
        self.assertIn('"calendário hoje"', system_content)
        # criar evento calendário com campos
        self.assertIn('"criar evento calendário"', system_content)
        self.assertIn('"title":"Reunião"', system_content)
        self.assertIn('"date":"amanhã"', system_content)
        self.assertIn('"start_time":"15:00"', system_content)

    def test_payload_contains_aliases_action(self):
        """Payload deve incluir ação de aliases explicitamente."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("listar aliases", system_content)
        self.assertIn("aliases cadastrados", system_content.lower())

    def test_payload_contains_calendar_today_action(self):
        """Payload deve incluir ação de calendário hoje explicitamente."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("calendário hoje", system_content)
        self.assertIn("o que tenho hoje", system_content.lower())

    def test_payload_contains_clarification_rule(self):
        """Payload deve conter regra de clarification para evento incompleto."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("clarification", system_content)
        self.assertIn("incompleto", system_content.lower())

    def test_payload_contains_prompt_injection_rule(self):
        """Payload deve conter regra de chat para prompt injection."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("prompt injection", system_content.lower())
        self.assertIn("chat", system_content)

    def test_payload_contains_natural_chat_instruction(self):
        """Payload deve instruir resposta conversacional natural para chat."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("resposta conversacional natural", system_content.lower())

    def test_payload_contains_natural_chat_example(self):
        """Payload deve conter exemplo de resposta natural de chat."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("Olá, senhor! Tudo bem, obrigado por perguntar.", system_content)

    def test_payload_prohibits_classification_message(self):
        """Payload deve proibir mensagens classificatórias genéricas."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("Classificado como conversa.", system_content)
        self.assertIn("Nunca descreva a classificação", system_content)

    def test_payload_contains_natural_clarification_instruction(self):
        """Payload deve instruir pergunta natural para clarification."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("pergunta curta e natural", system_content.lower())

    def test_payload_preserves_security_and_actions(self):
        """Payload deve preservar regras de segurança e actions canônicas."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        # Segurança preservada
        self.assertIn("prompt injection", system_content.lower())
        self.assertIn("neutro e seguro", system_content)
        # Actions preservadas
        self.assertIn("abrir aplicativo", system_content)
        self.assertIn("listar aliases", system_content)
        self.assertIn("buscar segundo cérebro", system_content)
        self.assertIn("calendário hoje", system_content)
        self.assertIn("criar evento calendário", system_content)

    def test_payload_empty_context_preserves_system_and_user(self):
        """Context vazio preserva payload com apenas system + user atual."""
        payload = self.provider._build_payload("mensagem atual", {}, [])
        messages = payload["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "mensagem atual")

    def test_payload_recent_turns_converts_therion_without_duplication(self):
        """Histórico user/therion/user atual vira user/assistant/user sem duplicação."""
        context = {
            "recent_turns": [
                {"role": "user", "text": "me dê dicas"},
                {"role": "therion", "text": "De qual área você gostaria de dicas?"},
                {"role": "user", "text": "estudo"},
            ]
        }
        payload = self.provider._build_payload("estudo", context, [])
        messages = payload["messages"]
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1], {"role": "user", "content": "me dê dicas"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "De qual área você gostaria de dicas?"})
        self.assertEqual(messages[3], {"role": "user", "content": "estudo"})

    def test_payload_recent_turns_preserves_different_last_turn(self):
        """Último turn diferente da mensagem atual não é descartado."""
        context = {
            "recent_turns": [
                {"role": "user", "text": "me dê dicas"},
                {"role": "therion", "text": "De qual área você gostaria de dicas?"},
            ]
        }
        payload = self.provider._build_payload("estudo", context, [])
        messages = payload["messages"]
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1], {"role": "user", "content": "me dê dicas"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "De qual área você gostaria de dicas?"})
        self.assertEqual(messages[3], {"role": "user", "content": "estudo"})

    def test_payload_uses_only_passed_context_isolated(self):
        """Provider consome apenas o context recebido sem acessar WorkingMemory."""
        from unittest.mock import patch
        context = {
            "recent_turns": [
                {"role": "user", "text": "olá"},
                {"role": "therion", "text": "olá, como posso ajudar?"},
            ]
        }
        with patch("therion.memory.working_memory.WorkingMemory") as mock_mem:
            payload = self.provider._build_payload("ajuda", context, [])
            mock_mem.assert_not_called()
        self.assertEqual(len(payload["messages"]), 4)
        self.assertEqual(payload["messages"][-1]["content"], "ajuda")


class TestContextualShortResponseRule(unittest.TestCase):
    """Testes estruturais da regra de respostas curtas contextuais no SYSTEM_PROMPT."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=30)

    def test_system_prompt_contains_contextual_short_response_rule(self):
        """SYSTEM_PROMPT contém regra explícita de respostas curtas contextuais."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("sim", system_content.lower())
        self.assertIn("não", system_content.lower())
        self.assertIn("ok", system_content.lower())
        self.assertIn("tudo", system_content.lower())
        self.assertIn("mensagem imediatamente anterior", system_content.lower())

    def test_system_prompt_prohibits_historical_association(self):
        """SYSTEM_PROMPT contém regra proibindo classificação por associação histórica."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("NÃO classifique uma resposta curta como", system_content)
        self.assertIn("associação com palavras ou exemplos do histórico", system_content.lower())

    def test_system_prompt_preserves_calendar_example(self):
        """Exemplo legítimo de calendário continua presente no SYSTEM_PROMPT."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("O que tenho hoje?", system_content)
        self.assertIn("calendário hoje", system_content)

    def test_system_prompt_contains_contextual_example(self):
        """Exemplo contextual 'oferta de plano + sim' é classificado como plan_request."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        example_line = next(
            ln
            for ln in system_content.splitlines()
            if "Deseja que eu gere esse plano completo agora?" in ln
        )
        self.assertIn('Usuário: "sim"', example_line)
        self.assertIn('"type":"plan_request"', example_line)
        self.assertNotIn('"type":"chat"', example_line)
        self.assertNotIn("vou gerar agora", system_content.lower())

    def test_system_prompt_does_not_force_study_example_into_unrelated_topics(self):
        """O exemplo global não deve arrastar melhorias do Therion para estudos."""
        payload = self.provider._build_payload("teste", {}, [])
        sc = payload["messages"][0]["content"]
        self.assertNotIn("tenho 2 horas para estudar circuitos lógicos e quero usar pomodoro", sc)
        self.assertIn('"type":"chat"', sc)
        self.assertIn('"intent":null', sc)
        self.assertIn('"arguments":{}', sc)

    def test_build_payload_places_prompt_in_messages_zero(self):
        """_build_payload() continua colocando SYSTEM_PROMPT em messages[0]['content']."""
        payload = self.provider._build_payload("teste", {}, [])
        messages = payload["messages"]
        self.assertGreater(len(messages), 0)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIsInstance(messages[0]["content"], str)
        self.assertGreater(len(messages[0]["content"]), 100)


class TestPomodoroBudgetTransport(unittest.TestCase):
    """Testes do transporte do pomodoro_budget ao Ollama (Incremento 4B)."""

    BUDGET = {
        "available_minutes": 120,
        "blocks": 4,
        "focus_minutes": 25,
        "break_minutes": 5,
        "planned_minutes": 115,
        "remaining_minutes": 5,
    }

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=30)

    def test_A_budget_present_in_system_content(self) -> None:
        """A) Budget presente: system content contém bloco formatado."""
        context = {"pomodoro_budget": self.BUDGET}
        payload = self.provider._build_payload("teste", context, [])
        sc = payload["messages"][0]["content"]
        self.assertIn("[ORÇAMENTO POMODORO]", sc)
        self.assertIn("120", sc)
        self.assertIn("4", sc)
        self.assertIn("25", sc)
        self.assertIn("5", sc)
        self.assertIn("115", sc)
        self.assertIn("limites factuais", sc.lower())

    def test_B_only_one_system_message(self) -> None:
        """B) Continua existindo somente uma mensagem system em messages[0]."""
        context = {"pomodoro_budget": self.BUDGET}
        payload = self.provider._build_payload("teste", context, [])
        messages = payload["messages"]
        system_msgs = [m for m in messages if m["role"] == "system"]
        self.assertEqual(len(system_msgs), 1)
        self.assertEqual(messages[0]["role"], "system")

    def test_C_without_budget_no_dynamic_block(self) -> None:
        """C) Sem budget: system prompt sem bloco dinâmico."""
        payload = self.provider._build_payload("teste", {}, [])
        sc = payload["messages"][0]["content"]
        self.assertNotIn("[ORÇAMENTO POMODORO]", sc)

    def test_D_recent_turns_preserved(self) -> None:
        """D) recent_turns preservados: ordem, roles, sem duplicação."""
        context = {
            "recent_turns": [
                {"role": "user", "text": "olá"},
                {"role": "therion", "text": "olá!"},
            ],
            "pomodoro_budget": self.BUDGET,
        }
        payload = self.provider._build_payload("teste", context, [])
        messages = payload["messages"]
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[1], {"role": "user", "content": "olá"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "olá!"})
        self.assertEqual(messages[3], {"role": "user", "content": "teste"})

    def test_E_structural_tests_still_pass(self) -> None:
        """E) Testes estruturais anteriores continuam intactos."""
        payload = self.provider._build_payload("teste", {}, [])
        sc = payload["messages"][0]["content"]
        # regra contextual
        self.assertIn("sim", sc.lower())
        self.assertIn("tudo", sc.lower())
        self.assertIn("mensagem imediatamente anterior", sc.lower())
        # exemplo contextual reclassificado como plan_request
        self.assertIn("Deseja que eu gere esse plano completo agora?", sc)
        self.assertIn('"type":"plan_request"', sc)
        # exemplo calendário
        self.assertIn("O que tenho hoje?", sc)
        # message do classificador não contém o plano completo
        self.assertNotIn("vou gerar agora", sc.lower())


class TestGeneratePlan(unittest.TestCase):
    """Testes focados do gerador dirigido generate_plan (E1/M4)."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=30)

    def _generate_with_content(self, content: str) -> PlanContent:
        external_body = {"message": {"content": content}}
        with patch.object(
            self.provider._opener,
            "open",
            return_value=_make_http_response(external_body),
        ):
            return self.provider.generate_plan("monte um plano de estudo", {})

    def test_directed_payload_uses_plan_prompt_schema_and_user_message(self):
        payload = self.provider._build_plan_payload("monte um plano de estudo", {})
        self.assertEqual(payload["format"], PLAN_FORMAT_SCHEMA)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["model"], "qwen3:4b-instruct")
        messages = payload["messages"]
        self.assertEqual(
            messages[0], {"role": "system", "content": PLAN_SYSTEM_PROMPT}
        )
        self.assertEqual(
            messages[1], {"role": "user", "content": "monte um plano de estudo"}
        )

    def test_valid_json_returns_plan_content(self):
        content = json.dumps({
            "title": "Plano de estudo",
            "sections": [
                {"heading": "Bloco 1", "body": "Conteudo integral do bloco 1."},
                {"heading": "Bloco 2", "body": "Conteudo integral do bloco 2."},
            ],
        })
        result = self._generate_with_content(content)
        self.assertIsInstance(result, PlanContent)
        self.assertEqual(result.title, "Plano de estudo")
        self.assertEqual(len(result.sections), 2)
        self.assertIsInstance(result.sections[0], PlanSection)
        self.assertEqual(result.sections[0].heading, "Bloco 1")
        self.assertEqual(result.sections[0].body, "Conteudo integral do bloco 1.")
        self.assertIsInstance(result.sections[1], PlanSection)
        self.assertEqual(result.sections[1].heading, "Bloco 2")
        self.assertEqual(result.sections[1].body, "Conteudo integral do bloco 2.")

    def test_invalid_json_raises_provider_response_error(self):
        with self.assertRaises(ProviderResponseError):
            self._generate_with_content("{ json invalido sem fechar")

    def test_sections_missing_or_not_list_raises_provider_response_error(self):
        with self.assertRaises(ProviderResponseError):
            self._generate_with_content(json.dumps({"title": "Plano"}))
        with self.assertRaises(ProviderResponseError):
            self._generate_with_content(json.dumps({"sections": "nao e lista"}))

    def test_section_missing_fields_or_wrong_types_raises_provider_response_error(
        self,
    ):
        with self.assertRaises(ProviderResponseError):
            self._generate_with_content(
                json.dumps({"sections": [{"heading": "Bloco 1"}]})
            )
        with self.assertRaises(ProviderResponseError):
            self._generate_with_content(
                json.dumps({"sections": [{"heading": 123, "body": "texto"}]})
            )

    def test_generate_plan_reuses_send_request(self):
        content = json.dumps({
            "title": "Plano",
            "sections": [{"heading": "Bloco", "body": "Corpo"}],
        })
        with patch.object(
            self.provider, "_send_request", return_value=content
        ) as mock_send:
            result = self.provider.generate_plan("monte um plano", {})
        mock_send.assert_called_once()
        payload = mock_send.call_args[0][0]
        self.assertEqual(payload["format"], PLAN_FORMAT_SCHEMA)
        self.assertIsInstance(result, PlanContent)


class TestPlanRequestPrecedence(unittest.TestCase):
    """Testes estruturais da precedência de plan_request e das regras de 'sim' (M10d1)."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=30)
        payload = self.provider._build_payload("teste", {}, [])
        self.sc = payload["messages"][0]["content"]

    def test_system_prompt_declares_plan_request_precedence_over_chat(self):
        """SYSTEM_PROMPT declara precedência de plan_request sobre chat para pedido explícito."""
        self.assertIn("PRECEDÊNCIA", self.sc)
        self.assertIn("gerar, criar, montar ou entregar", self.sc)
        self.assertIn('prevalece sobre a classificação como "chat"', self.sc)
        self.assertIn('classifique sempre como "plan_request"', self.sc)

    def test_system_prompt_contains_natural_plan_request_example(self):
        """Exemplo natural 'Gere um plano textual completo...' é classificado como plan_request."""
        example_line = next(
            ln
            for ln in self.sc.splitlines()
            if "Gere um plano textual completo" in ln
            and '"type":"plan_request"' in ln
        )
        self.assertIn('"type":"plan_request"', example_line)

    def test_system_prompt_contextual_sim_after_offer_is_plan_request(self):
        """'sim' aceitando oferta explícita de plano do assistente é plan_request."""
        example_line = next(
            ln
            for ln in self.sc.splitlines()
            if "Deseja que eu gere esse plano completo agora?" in ln
        )
        self.assertIn('Usuário: "sim"', example_line)
        self.assertIn('"type":"plan_request"', example_line)
        self.assertIn(
            "EXCEÇÃO: se a mensagem imediatamente anterior do assistente for uma oferta explícita",
            self.sc,
        )

    def test_system_prompt_isolated_sim_not_promoted_to_plan_request(self):
        """"sim" isolado, sem oferta explícita anterior, não vira plan_request automaticamente."""
        self.assertIn('"Sim" isolado', self.sc)
        self.assertIn("sem oferta explícita de plano", self.sc)
        self.assertIn('NÃO vira "plan_request" automaticamente', self.sc)
        for line in self.sc.splitlines():
            if '"sim"' in line and '"type":"plan_request"' in line:
                self.assertIn("Assistente", line)


class TestPlanGenerationTimeout(unittest.TestCase):
    """Timeout separado da geração dirigida de planos (M10j1)."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=90)

    def test_plan_timeout_constant_is_120(self):
        """Constante de timeout da geração dirigida é 120 s."""
        self.assertEqual(PLAN_TIMEOUT_SECONDS, 120)
        self.assertNotEqual(PLAN_TIMEOUT_SECONDS, self.provider.timeout)

    def test_classification_uses_provider_timeout_90(self):
        """generate() envia timeout=self.timeout (90 s) para o transporte."""
        raw = json.dumps(
            {"type": "chat", "message": "ola", "intent": None, "arguments": {}}
        )
        with patch.object(self.provider, "_send_request", return_value=raw) as mock_send:
            self.provider.generate("oi", {}, [])
        self.assertEqual(mock_send.call_args.kwargs.get("timeout"), 90)

    def test_generate_plan_uses_separate_timeout_120(self):
        """generate_plan() envia o timeout dedicado de 120 s para o transporte."""
        content = json.dumps(
            {"title": "Plano", "sections": [{"heading": "Bloco", "body": "Corpo"}]}
        )
        with patch.object(self.provider, "_send_request", return_value=content) as mock_send:
            self.provider.generate_plan("monte um plano", {})
        self.assertEqual(mock_send.call_args.kwargs.get("timeout"), PLAN_TIMEOUT_SECONDS)
        self.assertEqual(mock_send.call_args.kwargs.get("timeout"), 120)

    def test_generate_plan_does_not_mutate_provider_timeout(self):
        """generate_plan() não altera self.timeout global do provider."""
        content = json.dumps(
            {"title": "Plano", "sections": [{"heading": "Bloco", "body": "Corpo"}]}
        )
        with patch.object(self.provider, "_send_request", return_value=content):
            self.provider.generate_plan("monte um plano", {})
        self.assertEqual(self.provider.timeout, 90)

    def test_payloads_keep_fields_and_num_ctx(self):
        """Payloads preservam campos, options e num_ctx atuais (sem mudança semântica)."""
        cls_payload = self.provider._build_payload("teste", {}, [])
        plan_payload = self.provider._build_plan_payload("monte um plano", {})
        self.assertEqual(
            sorted(cls_payload.keys()), ["format", "messages", "model", "options", "stream"]
        )
        self.assertEqual(cls_payload["options"], {"temperature": 0, "num_ctx": 4096})
        self.assertNotIn("num_predict", cls_payload["options"])
        self.assertIs(cls_payload["format"], FORMAT_SCHEMA)
        self.assertEqual(
            sorted(plan_payload.keys()),
            ["format", "messages", "model", "options", "stream"],
        )
        self.assertEqual(
            plan_payload["options"],
            {"temperature": 0, "num_ctx": 2048, "num_predict": 1536},
        )
        self.assertIs(plan_payload["format"], PLAN_FORMAT_SCHEMA)

    def test_prompts_keep_structural_markers(self):
        """SYSTEM_PROMPT e PLAN_SYSTEM_PROMPT mantêm marcadores estruturais."""
        self.assertIn("PRECEDÊNCIA", SYSTEM_PROMPT)
        self.assertIn('NÃO vira "plan_request" automaticamente', SYSTEM_PROMPT)
        self.assertIn("Entregue o plano completo e imediato", PLAN_SYSTEM_PROMPT)
        self.assertIn('exatamente as chaves: "title"', PLAN_SYSTEM_PROMPT)


class TestPlanConcisenessPrompt(unittest.TestCase):
    """Política de concisão no PLAN_SYSTEM_PROMPT (E1/M10o1)."""

    def test_prompt_asks_for_concise_plan(self):
        """PLAN_SYSTEM_PROMPT pede plano conciso, seções curtas e sem redundância."""
        self.assertIn("conciso", PLAN_SYSTEM_PROMPT)
        self.assertIn("curtas e objetivas", PLAN_SYSTEM_PROMPT)
        self.assertIn("sem explicações redundantes", PLAN_SYSTEM_PROMPT)
        self.assertIn("nem repetição do mesmo conteúdo", PLAN_SYSTEM_PROMPT)

    def test_prompt_requires_covering_all_requested_topics(self):
        """PLAN_SYSTEM_PROMPT exige cobrir todos os tópicos explicitamente pedidos."""
        self.assertIn("todos os tópicos explicitamente pedidos", PLAN_SYSTEM_PROMPT)

    def test_prompt_allows_grouping_related_topics(self):
        """PLAN_SYSTEM_PROMPT permite agrupar tópicos relacionados."""
        self.assertIn("Agrupe tópicos relacionados", PLAN_SYSTEM_PROMPT)

    def test_prompt_has_no_rigid_section_maximum(self):
        """PLAN_SYSTEM_PROMPT declara ausência de máximo rígido de seções."""
        self.assertIn("Não há máximo rígido de seções", PLAN_SYSTEM_PROMPT)
        self.assertNotRegex(PLAN_SYSTEM_PROMPT, r"máximo de \d+ seções")

    def test_prompt_targets_below_5500_chars(self):
        """PLAN_SYSTEM_PROMPT orienta manter o texto abaixo de 5500 caracteres."""
        self.assertIn("claramente abaixo de 5500 caracteres", PLAN_SYSTEM_PROMPT)

    def test_plan_format_schema_unchanged(self):
        """PLAN_FORMAT_SCHEMA permanece intacto, sem campo complete."""
        self.assertEqual(PLAN_FORMAT_SCHEMA["type"], "object")
        self.assertEqual(PLAN_FORMAT_SCHEMA["required"], ["sections"])
        self.assertFalse(PLAN_FORMAT_SCHEMA["additionalProperties"])
        props = PLAN_FORMAT_SCHEMA["properties"]
        self.assertEqual(set(props.keys()), {"title", "sections"})
        self.assertEqual(props["sections"]["minItems"], 1)
        item = props["sections"]["items"]
        self.assertEqual(item["required"], ["heading", "body"])
        self.assertFalse(item["additionalProperties"])
        self.assertNotIn("complete", props)


class TestPlanNumPredictLimit(unittest.TestCase):
    """num_predict restrito ao payload de plano (E1/M10q1 -> M10r1)."""

    def setUp(self):
        self.provider = OllamaProvider(model="qwen3:4b-instruct", timeout=90)

    def test_plan_payload_options(self):
        """Payload de plano mantém temperature 0, num_ctx 2048 e num_predict 1536."""
        payload = self.provider._build_plan_payload("monte um plano", {})
        options = payload["options"]
        self.assertEqual(options["temperature"], 0)
        self.assertEqual(options["num_ctx"], 2048)
        self.assertEqual(options["num_predict"], 1536)

    def test_classification_payload_has_no_num_predict(self):
        """Payload de classificação mantém temperature 0 e num_ctx 4096, sem num_predict."""
        payload = self.provider._build_payload("oi", {}, [])
        options = payload["options"]
        self.assertEqual(options["temperature"], 0)
        self.assertEqual(options["num_ctx"], 4096)
        self.assertNotIn("num_predict", options)

    def test_plan_schema_and_prompt_unchanged(self):
        """PLAN_FORMAT_SCHEMA e PLAN_SYSTEM_PROMPT permanecem intactos."""
        self.assertEqual(PLAN_FORMAT_SCHEMA["required"], ["sections"])
        self.assertFalse(PLAN_FORMAT_SCHEMA["additionalProperties"])
        self.assertEqual(
            set(PLAN_FORMAT_SCHEMA["properties"].keys()), {"title", "sections"}
        )
        self.assertIn("Entregue o plano completo e imediato", PLAN_SYSTEM_PROMPT)

    def test_plan_timeout_still_120(self):
        """Timeout dedicado de geração continua 120 s."""
        self.assertEqual(PLAN_TIMEOUT_SECONDS, 120)

    def test_public_api_signatures_unchanged(self):
        """Assinaturas públicas de generate, generate_plan e _send_request não mudaram."""
        self.assertEqual(
            list(inspect.signature(OllamaProvider.generate).parameters),
            ["self", "message", "context", "available_intents"],
        )
        self.assertEqual(
            list(inspect.signature(OllamaProvider.generate_plan).parameters),
            ["self", "message", "context"],
        )
        self.assertEqual(
            list(inspect.signature(OllamaProvider._send_request).parameters),
            ["self", "payload", "timeout"],
        )


if __name__ == "__main__":
    unittest.main()
