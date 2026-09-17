"""Testes unitários isolados para OllamaProvider (A2.5-R)."""

import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from therion.core.ai_provider import AIResponse
from therion.core.ai_provider_ollama import (
    ENDPOINT,
    OllamaProvider,
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
        self.assertEqual(fmt["properties"]["type"]["enum"], ["chat", "clarification", "action"])

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


if __name__ == "__main__":
    unittest.main()
