"""Diagnóstico de falhas da IA auxiliar — Microfrente A."""

import unittest
import urllib.error
from unittest.mock import patch

from therion.core.ai_core import (
    FAILURE_INVALID_RESPONSE,
    FAILURE_PROVIDER_TIMEOUT,
    FAILURE_PROVIDER_UNAVAILABLE,
    FAILURE_REJECTED_BY_POLICY,
    AICore,
    ClassifyOutcome,
)
from therion.core.ai_provider import (
    AIProvider,
    AIResponse,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator

_FORBIDDEN = (
    "127.0.0.1", "11434", "WinError", "URLError", "Traceback",
    "Ollama", "http://", "Erro de transporte", "Timeout na requisição",
    "Connection refused", "bad json",
)
CMD = "Therion, toque uma música"
NO_AI_MSG = "Não consegui identificar a intenção no comando recebido."


class _FakeProvider(AIProvider):
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def generate(self, message, context, available_intents):
        if self._error is not None:
            raise self._error
        return self._response

    def generate_plan(self, message, context):
        raise NotImplementedError


class _FakeHTTP:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
        self.code = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _nontech(tc, message):
    tc.assertTrue(message)
    for frag in _FORBIDDEN:
        tc.assertNotIn(frag, message)


def _rejected_provider():
    return _FakeProvider(
        response=AIResponse(
            type="action",
            intent="executar powershell",
            arguments={"cmd": "x"},
            message="Executando",
        )
    )


class TestProviderTypedExceptions(unittest.TestCase):
    def setUp(self):
        self.p = OllamaProvider(model="qwen3:4b-instruct", timeout=30)

    def test_transport_refused(self):
        with patch.object(self.p._opener, "open",
                          side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(ProviderTransportError):
                self.p.generate("t", {}, [])

    def test_transport_is_runtime_error(self):
        with patch.object(self.p._opener, "open",
                          side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(RuntimeError):
                self.p.generate("t", {}, [])

    def test_urlerror_timeout_reason(self):
        with patch.object(self.p._opener, "open",
                          side_effect=urllib.error.URLError(TimeoutError("x"))):
            with self.assertRaises(ProviderTimeoutError):
                self.p.generate("t", {}, [])

    def test_direct_timeout(self):
        with patch.object(self.p._opener, "open", side_effect=TimeoutError("x")):
            with self.assertRaises(ProviderTimeoutError):
                self.p.generate("t", {}, [])

    def test_timeout_is_runtime_error(self):
        with patch.object(self.p._opener, "open", side_effect=TimeoutError("x")):
            with self.assertRaises(RuntimeError):
                self.p.generate("t", {}, [])

    def test_malformed_is_response_error_and_value_error(self):
        resp = _FakeHTTP(b"{ invalido")
        with patch.object(self.p._opener, "open", return_value=resp):
            with self.assertRaises(ProviderResponseError):
                self.p.generate("t", {}, [])
        with patch.object(self.p._opener, "open", return_value=resp):
            with self.assertRaises(ValueError):
                self.p.generate("t", {}, [])

    def test_http_500_is_transport_error(self):
        with patch.object(self.p._opener, "open", return_value=_FakeHTTP(b"{}", 500)):
            with self.assertRaises(ProviderTransportError):
                self.p.generate("t", {}, [])


class TestClassifyDetailed(unittest.TestCase):
    def _core(self, provider):
        return AICore(provider=provider, available_intents=["calendário hoje"])

    def test_transport_maps_to_provider_unavailable(self):
        out = self._core(_FakeProvider(error=ProviderTransportError("x"))
                         ).classify_detailed("t", {})
        self.assertIsInstance(out, ClassifyOutcome)
        self.assertIsNone(out.response)
        self.assertEqual(out.failure, FAILURE_PROVIDER_UNAVAILABLE)

    def test_timeout_maps_to_provider_timeout(self):
        out = self._core(_FakeProvider(error=ProviderTimeoutError("x"))
                         ).classify_detailed("t", {})
        self.assertIsNone(out.response)
        self.assertEqual(out.failure, FAILURE_PROVIDER_TIMEOUT)

    def test_malformed_maps_to_invalid_response(self):
        out = self._core(_FakeProvider(error=ProviderResponseError("x"))
                         ).classify_detailed("t", {})
        self.assertIsNone(out.response)
        self.assertEqual(out.failure, FAILURE_INVALID_RESPONSE)

    def test_allowlist_reject_maps_to_rejected_by_policy(self):
        out = self._core(_rejected_provider()).classify_detailed("t", {})
        self.assertIsNone(out.response)
        self.assertEqual(out.failure, FAILURE_REJECTED_BY_POLICY)

    def test_generic_exception_maps_to_provider_unavailable(self):
        out = self._core(_FakeProvider(error=RuntimeError("boom"))
                         ).classify_detailed("t", {})
        self.assertIsNone(out.response)
        self.assertEqual(out.failure, FAILURE_PROVIDER_UNAVAILABLE)

    def test_valid_response_no_failure(self):
        core = self._core(_FakeProvider(response=AIResponse(type="chat", message="Ola!")))
        out = core.classify_detailed("t", {})
        self.assertIsNone(out.failure)
        self.assertEqual(out.response.message, "Ola!")


class TestClassifyWrapperCompat(unittest.TestCase):
    def test_failure_returns_none(self):
        core = AICore(provider=_FakeProvider(error=ProviderTimeoutError("x")),
                       available_intents=[])
        self.assertIsNone(core.classify("t", {}))

    def test_success_returns_response(self):
        core = AICore(
            provider=_FakeProvider(response=AIResponse(type="chat", message="Ola!")),
            available_intents=[],
        )
        result = core.classify("t", {})
        self.assertEqual(result.message, "Ola!")


class TestOrchestratorAIStatuses(unittest.TestCase):
    def _orch(self, provider):
        core = AICore(provider=provider, available_intents=["calendário hoje"])
        return Orchestrator(simulate=True, ai_core=core)

    def test_transport_returns_ai_unavailable(self):
        r = self._orch(_FakeProvider(error=ProviderTransportError("refused"))
                       ).process_command(CMD)
        self.assertEqual(r.status, "ai_unavailable")
        _nontech(self, r.message)

    def test_timeout_returns_ai_timeout(self):
        r = self._orch(_FakeProvider(error=ProviderTimeoutError("timed out"))
                       ).process_command(CMD)
        self.assertEqual(r.status, "ai_timeout")
        _nontech(self, r.message)

    def test_malformed_returns_ai_invalid_response(self):
        r = self._orch(_FakeProvider(error=ProviderResponseError("bad json"))
                       ).process_command(CMD)
        self.assertEqual(r.status, "ai_invalid_response")
        _nontech(self, r.message)

    def test_rejected_returns_ai_invalid_response(self):
        r = self._orch(_rejected_provider()).process_command(CMD)
        self.assertEqual(r.status, "ai_invalid_response")
        _nontech(self, r.message)

    def test_no_ai_preserves_unknown_intent(self):
        r = Orchestrator(simulate=True).process_command(CMD)
        self.assertEqual(r.status, "unknown_intent")
        self.assertEqual(r.message, NO_AI_MSG)


class TestDesktopStatusMap(unittest.TestCase):
    def test_new_statuses_map_to_error(self):
        from therion.interface.desktop import _ORBE_STATUS_MAP
        for status in ("ai_unavailable", "ai_timeout", "ai_invalid_response"):
            self.assertEqual(_ORBE_STATUS_MAP[status], "error")

    def test_unknown_intent_still_idle(self):
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["unknown_intent"], "idle")


if __name__ == "__main__":
    unittest.main()
