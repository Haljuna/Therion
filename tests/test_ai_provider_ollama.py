"""Testes unitários isolados para OllamaProvider (A2.5-R)."""

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
    OllamaProvider,
    PLAN_FORMAT_SCHEMA,
    PLAN_SYSTEM_PROMPT,
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
        """Payload deve conter stream: false, format, temperature: 0 e num_ctx: 2048."""
        payload = self.provider._build_payload("Olá", {}, ["calendário hoje"])
        self.assertEqual(payload["model"], "qwen3:4b-instruct")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["num_ctx"], 2048)

        # Verificação do format schema
        fmt = payload["format"]
        self.assertEqual(fmt["type"], "object")
        self.assertFalse(fmt["additionalProperties"])
        self.assertEqual(fmt["required"], ["type", "message", "intent", "arguments"])
        self.assertEqual(
            fmt["properties"]["type"]["enum"],
            ["chat", "clarification", "action", "plan_request", "plan_reference"],
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
        self.assertIn("Olá! Tudo bem sim. Como posso ajudar?", system_content)

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
        """SYSTEM_PROMPT contém exemplo de continuação contextual (sim como confirmação)."""
        payload = self.provider._build_payload("teste", {}, [])
        system_content = payload["messages"][0]["content"]
        self.assertIn("Deseja que eu gere esse plano completo agora?", system_content)
        self.assertIn("sim", system_content)
        self.assertIn("Revisão de conceitos", system_content)
        self.assertIn("Prática de exercícios", system_content)
        self.assertNotIn("vou gerar agora", system_content.lower())

    def test_system_prompt_contains_study_pomodoro_example(self):
        """SYSTEM_PROMPT contém exemplo de frase de estudo/Pomodoro como chat."""
        payload = self.provider._build_payload("teste", {}, [])
        sc = payload["messages"][0]["content"]
        self.assertIn("tenho 2 horas para estudar circuitos lógicos e quero usar pomodoro", sc)
        self.assertIn('"type":"chat"', sc)
        self.assertIn('"intent":null', sc)
        self.assertIn('"arguments":{}', sc)
        self.assertIn("Pomodoro", sc)

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
        # exemplo contextual
        self.assertIn("Deseja que eu gere esse plano completo agora?", sc)
        # exemplo calendário
        self.assertIn("O que tenho hoje?", sc)
        # entrega imediata
        self.assertIn("Revisão de conceitos", sc)
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


if __name__ == "__main__":
    unittest.main()
