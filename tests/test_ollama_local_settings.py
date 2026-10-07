"""Configuração local e transmissão do modo de raciocínio, sem rede."""
from unittest.mock import patch
from types import SimpleNamespace

import pytest

from therion.config.local import _validate_config
from therion.core.ai_provider_ollama import ENDPOINT, OllamaProvider


def test_compatibilidade_config_antiga():
    ai = _validate_config({"ai": {"model": "antigo"}})["ai"]
    assert ai["endpoint"] == ENDPOINT
    assert ai["think"] is None


@pytest.mark.parametrize("endpoint", ["https://example.com/api/chat", "http://127.0.0.1:0/api/chat", "http://user@127.0.0.1:11435/api/chat", "http://127.0.0.1:11435/api/chat?x=1"])
def test_endpoint_externo_ou_invalido_nao_e_usado(endpoint):
    assert _validate_config({"ai": {"endpoint": endpoint}})["ai"]["endpoint"] == ENDPOINT
    with pytest.raises(ValueError):
        OllamaProvider(endpoint=endpoint)


def test_config_candidato_preserva_chaves():
    ai = _validate_config({"ai": {"endpoint": "http://127.0.0.1:11435/api/chat", "think": False, "extra": 7}})["ai"]
    assert ai["endpoint"].endswith("11435/api/chat")
    assert ai["think"] is False
    assert ai["extra"] == 7


@pytest.mark.parametrize("think", [None, False, True])
def test_think_transmitido_em_conversa_e_plano(think):
    provider = OllamaProvider(endpoint="http://127.0.0.1:11435/api/chat", think=think)
    with patch.object(provider, "_send_request", return_value='{}') as send, patch.object(provider, "_parse_and_validate"), patch.object(provider, "_parse_plan_content"):
        provider.generate("Olá", {}, [])
        provider.generate_plan("Plano", {})
    for call in send.call_args_list:
        payload = call.args[0]
        assert ("think" in payload) == (think is not None)
        if think is not None:
            assert payload["think"] is think


def test_think_invalido_retorna_padrao():
    assert _validate_config({"ai": {"think": "false"}})["ai"]["think"] is None


@pytest.mark.parametrize("extra", [{}, {"endpoint": "http://127.0.0.1:11435/api/chat", "think": False}])
def test_interface_encaminha_apenas_config_opcional_presente(extra):
    from therion.interface.desktop import MainWindow
    window = SimpleNamespace(_config={"ai": {"enabled": True, "model": "teste", "timeout_seconds": 90, **extra}})
    with patch("therion.interface.desktop.OllamaProvider") as provider, patch("therion.interface.desktop.AICore"):
        MainWindow._build_ai_core(window)
    provider.assert_called_once_with(model="teste", timeout=90, **extra)
