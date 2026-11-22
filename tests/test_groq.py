"""Groq na nuvem com reserva local: sem rede real, sem chave real."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from therion.core import groq
from therion.core.ai_provider_groq import GroqProvider
from therion.voice.groq_model import GroqVoiceModel


@pytest.fixture(autouse=True)
def no_cooldown(monkeypatch):
    monkeypatch.setattr(groq, '_blocked_until', {})


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(groq, 'api_key', lambda: 'gsk_fixture')


def test_chat_body_translates_ollama_payload():
    body = groq.chat_body({'messages': [{'role': 'user', 'content': 'oi'}], 'think': False,
                           'options': {'temperature': 0, 'num_ctx': 2048, 'num_predict': 300},
                           'format': {'type': 'object'}})
    assert body['model'] == groq.CHAT_MODEL and body['reasoning_effort'] == 'none'
    assert groq.chat_body({'messages': [], 'options': {'num_predict': 1536}})['max_completion_tokens'] == groq.MAX_OUTPUT
    assert body['max_completion_tokens'] == 300 and 'num_ctx' not in json.dumps(body)
    assert body['response_format']['json_schema']['schema'] == {'type': 'object'}
    with pytest.raises(groq.GroqUnavailable):
        groq.chat_body({'messages': [{'role': 'user', 'content': 'x', 'images': ['abc']}]})


def test_post_without_key_never_touches_network(monkeypatch):
    monkeypatch.setattr(groq, 'api_key', lambda: None)
    monkeypatch.setattr(groq.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('rede'))
    with pytest.raises(groq.GroqUnavailable):
        groq.post('chat/completions', b'{}', 'application/json', 1, 'fixture')


def test_provider_uses_groq_then_local_only_on_failure(monkeypatch):
    local = []
    monkeypatch.setattr('therion.core.ai_provider_ollama.OllamaProvider._send_request_serialized',
                        lambda self, payload, timeout: local.append(payload) or 'local')
    provider = GroqProvider(endpoint='http://127.0.0.1:11435/api/chat')
    monkeypatch.setattr(groq, 'chat', lambda payload, timeout: 'nuvem')
    assert provider._send_request_serialized({'messages': [{'role': 'user', 'content': 'oi'}]}, 30) == 'nuvem'
    provider.warmup()
    assert local == []  # aquecer não carrega o modelo local

    def down(payload, timeout):
        raise groq.GroqUnavailable('HTTP 429')
    monkeypatch.setattr(groq, 'chat', down)
    assert provider._send_request_serialized({'messages': [{'role': 'user', 'content': 'oi'}]}, 30) == 'local'
    assert len(local) == 1


def _tone(amplitude, seconds=1):
    return (amplitude * np.sin(np.arange(16000 * seconds) * 0.3)).astype(np.float32)


def _voice_with(monkeypatch, text, audio):
    sent, loads = [], []

    class Local:
        def transcribe(self, audio, **options):
            return [SimpleNamespace(text='local')], None
    monkeypatch.setattr(groq, 'post', lambda *a: sent.append(1) or {'segments': [{'text': text}]})
    segments, _ = GroqVoiceModel(lambda: loads.append(1) or Local()).transcribe(audio)
    return segments, sent, loads


def test_silence_never_reaches_groq_nor_local_fallback(monkeypatch):
    segments, sent, loads = _voice_with(monkeypatch, 'Tchau.', np.zeros(16000, dtype=np.float32))
    assert segments == [] and not sent and not loads


def test_quiet_request_followed_by_trailing_silence_still_reaches_groq(monkeypatch):
    # 0,3 s de fala baixa (RMS ~0.003) + 0,7 s de silêncio: o RMS do trecho inteiro seria ~0.0017.
    audio = np.concatenate([_tone(0.0042, 1)[:4800], np.full(11200, 0.001, dtype=np.float32)])
    segments, sent, _ = _voice_with(monkeypatch, ' Que horas são?', audio)
    assert sent == [1] and segments[0].text.strip() == 'Que horas são?'


def test_silence_line_boundary(monkeypatch):
    below = _voice_with(monkeypatch, 'oi', _tone(0.0025))  # RMS ~0.0018
    above = _voice_with(monkeypatch, 'oi', _tone(0.003))   # RMS ~0.0021
    assert not below[1] and above[1] == [1]


def test_classic_hallucination_on_weak_audio_is_dropped_without_local(monkeypatch):
    segments, sent, loads = _voice_with(monkeypatch, ' Tchau.', _tone(0.006))
    assert segments == [] and sent == [1] and not loads


def test_spoken_goodbye_with_normal_energy_passes(monkeypatch):
    segments, _, _ = _voice_with(monkeypatch, ' Tchau.', _tone(0.1))
    assert segments[0].text.strip() == 'Tchau.'


def test_normal_phrase_on_weak_audio_passes(monkeypatch):
    segments, _, _ = _voice_with(monkeypatch, ' Que horas são?', _tone(0.01))
    assert segments[0].text.strip() == 'Que horas são?'


def test_voice_uses_groq_metrics_and_loads_local_only_when_needed(monkeypatch):
    now = [0.0]
    loads = []

    class Local:
        def transcribe(self, audio, **options):
            return [SimpleNamespace(text='local')], None

    model = GroqVoiceModel(lambda: loads.append(1) or Local(), clock=lambda: now[0])
    sent = {}

    def ok(path, body, content_type, timeout, model):
        sent['body'] = body
        return {'segments': [{'text': ' Que horas são?', 'avg_logprob': -0.2, 'no_speech_prob': 0.01, 'compression_ratio': 1.1}]}
    monkeypatch.setattr(groq, 'post', ok)
    audio = _tone(0.1)
    segments, _ = model.transcribe(audio, language='pt', initial_prompt='Conversa', hotwords='Therion')
    assert segments[0].text.strip() == 'Que horas são?' and segments[0].avg_logprob == -0.2
    assert b'Conversa Therion' in sent['body'] and b'whisper-large-v3-turbo' in sent['body'] and not loads

    def down(*args, **kwargs):
        raise groq.GroqUnavailable('offline')
    monkeypatch.setattr(groq, 'post', down)
    assert model.transcribe(audio)[0][0].text == 'local'
    assert model.transcribe(audio)[0][0].text == 'local' and loads == [1]  # carrega uma vez só

    monkeypatch.setattr(groq, 'post', ok)
    now[0] = 400.0
    model.transcribe(audio)
    assert model._local is None  # Groq voltou e o local ficou parado: memória liberada
    with pytest.raises(ValueError):
        model.transcribe(np.zeros(0, dtype=np.float32))


def _sse(*chunks):
    return ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'


def _agent(handler):
    from therion.agent.ollama import OllamaAgentProvider
    factory = lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    return OllamaAgentProvider('http://127.0.0.1:11435/api/chat', 'fixture', protocol='native',
                               client_factory=factory, online=True)


def _decide(provider, events=None):
    from therion.agent.contracts import CancellationToken, TurnBudget
    rows = [{'role': 'user', 'content': 'Consulte Aurora'}]
    schemas = [{'type': 'function', 'function': {'name': 'lookup', 'parameters': {'type': 'object'}}}]
    return asyncio.run(provider.decide(rows, schemas, TurnBudget(), CancellationToken(),
                                       lambda name, **kw: (events if events is not None else []).append((name, kw))))


def test_agent_streams_tool_call_from_groq(key):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.host == 'api.groq.com' and request.headers['authorization'] == 'Bearer gsk_fixture'
        return httpx.Response(200, text=_sse(
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c1', 'function': {'name': 'lookup', 'arguments': '{"query":'}}]}}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"Aurora"}'}}]}, 'finish_reason': 'tool_calls'}]}))
    decision = _decide(_agent(handler))
    assert decision.kind == 'tools' and decision.calls[0].name == 'lookup' and decision.calls[0].arguments == {'query': 'Aurora'}
    assert len(seen) == 1 and json.loads(seen[0].content)['tools'][0]['function']['name'] == 'lookup'


def test_agent_falls_back_to_local_ollama_when_groq_refuses(key):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.host == 'api.groq.com':
            return httpx.Response(429)
        return httpx.Response(200, content=(json.dumps({'message': {'content': 'Resposta local.'}, 'done': True}) + '\n').encode())
    decision = _decide(_agent(handler))
    assert hosts == ['api.groq.com', '127.0.0.1'] and decision.message == 'Resposta local.'


def test_agent_does_not_repeat_locally_after_speaking(key):
    from therion.agent.contracts import ProviderUnavailable

    def handler(request):
        if request.url.host != 'api.groq.com':
            pytest.fail('não pode repetir no local depois de falar')
        # A conexão cai depois da primeira frase já ter ido para a voz.
        text = 'Encontrei sua nota de portas lógicas. ' + 'A informação seguinte continua aqui. ' * 8
        return httpx.Response(200, text='data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\n')
    events = []
    with pytest.raises(ProviderUnavailable):
        _decide(_agent(handler), events)
    assert [kw['text'] for name, kw in events if name == 'response_prefix'][0].startswith('Encontrei sua nota')


def test_rate_limit_pauses_groq_and_goes_local(key, monkeypatch):
    import email.message
    import urllib.error
    calls = []

    def refuse(request, timeout):
        calls.append(request)
        headers = email.message.Message()
        headers['retry-after'] = '20'
        raise urllib.error.HTTPError(request.full_url, 429, 'limite', headers, None)
    monkeypatch.setattr(groq.urllib.request, 'urlopen', refuse)
    for _ in range(2):
        with pytest.raises(groq.GroqUnavailable):
            groq.post('chat/completions', b'{}', 'application/json', 1, 'm')
    assert len(calls) == 1  # durante a pausa nem tenta a rede
    groq._blocked_until['m'] = 0
    with pytest.raises(groq.GroqUnavailable):
        groq.post('chat/completions', b'{}', 'application/json', 1, 'm')
    assert len(calls) == 2


def test_long_conversation_audio_goes_to_groq_and_huge_audio_to_local(monkeypatch):
    from therion.voice import groq_model
    sent = []
    monkeypatch.setattr(groq, 'post', lambda *a: sent.append(1) or {'segments': [{'text': 'longo'}]})

    class Local:
        def transcribe(self, audio, **options):
            return [SimpleNamespace(text='local')], None
    model = GroqVoiceModel(Local)
    # 40 s: a conversa contínua juntou várias falas (falhava com o limite de 30 s do Parakeet).
    assert model.transcribe(_tone(0.1, 40))[0][0].text == 'longo'
    assert model.transcribe(_tone(0.1, 601))[0][0].text == 'local'
    assert sent == [1]
