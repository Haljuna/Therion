from unittest.mock import MagicMock, patch
import asyncio
import json

import httpx

import pytest

from therion.core.ai_provider_ollama import OllamaProvider
from therion.interface.desktop import MainWindow
from therion.agent.ollama import OllamaAgentProvider
from therion.agent.contracts import CancellationToken, TurnBudget


def test_warmup_and_core_requests_use_the_agent_context():
    provider = OllamaProvider(think=False, context_tokens=8192)
    with patch.object(provider, '_send_request', return_value='') as send:
        provider.warmup()
    warm = send.call_args.args[0]
    assert warm['options']['num_ctx'] == 8192
    assert warm['messages'] == [] and 'format' not in warm
    assert warm['keep_alive'] == '5m'
    assert provider._build_payload('teste', {}, [])['options']['num_ctx'] == 8192
    assert OllamaProvider(think=False)._build_payload('teste', {}, [])['options']['num_ctx'] == 4096


def test_plan_generation_keeps_the_configured_context_and_voice_residency():
    provider = OllamaProvider(think=False, context_tokens=8192)
    payload = provider._build_plan_payload('Monte um plano de estudos.', {'voice_conversation': True})
    assert payload['options']['num_ctx'] == 8192
    assert payload['keep_alive'] == '5m'
    assert OllamaProvider(think=False)._build_plan_payload('Monte um plano.', {})['options']['num_ctx'] == 2048


@pytest.mark.parametrize('value', [True, 0, 32768, '8192'])
def test_invalid_context_rejected(value):
    with pytest.raises(ValueError):
        OllamaProvider(context_tokens=value)


@pytest.mark.parametrize('enabled,expected', [(True, 8192), (False, None)])
def test_desktop_aligns_context_only_with_enabled_agent(enabled, expected):
    window = MagicMock()
    window._config = {'ai': {'enabled': True, 'model': 'qwen3:4b-instruct', 'think': False},
                      'agent': {'enabled': enabled, 'context_tokens': 8192}}
    core = MainWindow._build_ai_core(window)
    assert core._provider.context_tokens == expected


@pytest.mark.parametrize('background', [False, True])
def test_only_foreground_keeps_model_resident(background):
    received = []
    def respond(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, content=b'{"message":{"content":"OK"},"done":true}\n')
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    provider = OllamaAgentProvider('http://127.0.0.1:11435/api/chat', 'fixture',
        protocol='native', think=False, background=background, client_factory=factory)
    async def run():
        try:
            return await provider.decide([{'role': 'user', 'content': 'Teste'}], [],
                TurnBudget(), CancellationToken(), lambda *args, **kwargs: None)
        finally:
            await provider.aclose()
    assert asyncio.run(run()).message == 'OK'
    assert received[0].get('keep_alive') == (None if background else '5m')
