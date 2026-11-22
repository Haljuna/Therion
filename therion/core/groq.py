"""Cliente Groq (nuvem). A chave vem só de GROQ_API_KEY: nunca é gravada, registrada nem mostrada."""
import json
import os
import time
import urllib.error
import urllib.request

BASE = 'https://api.groq.com/openai/v1/'
STT_MODEL = 'whisper-large-v3-turbo'
CHAT_MODEL = 'qwen/qwen3.8-27b'
MAX_OUTPUT = 1000  # plano grátis: no máximo 1000 tokens de saída por minuto
_blocked_until = {}  # modelo -> instante em que a Groq volta a aceitar


class GroqUnavailable(RuntimeError):
    """Sem chave, sem rede, limite do plano grátis ou recusa: o chamador usa o modelo local."""


def api_key():
    key = os.environ.get('GROQ_API_KEY', '').strip()
    if not key and os.name == 'nt':
        # O Therion pode ter sido aberto antes da chave existir; o registro do usuário já a tem.
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as reg:
                key = str(winreg.QueryValueEx(reg, 'GROQ_API_KEY')[0]).strip()
        except OSError:
            key = ''
    return key if key.startswith('gsk_') else None


def check(model):
    if time.monotonic() < _blocked_until.get(model, 0):
        raise GroqUnavailable('Limite da Groq: esperando liberar.')


def block(model, retry_after):
    # No limite do plano grátis, ir direto ao local evita uma tentativa perdida a cada fala.
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        seconds = 30.0
    _blocked_until[model] = time.monotonic() + min(max(seconds, 1.0), 120.0)


def post(path, body, content_type, timeout, model):
    check(model)
    key = api_key()
    if not key:
        raise GroqUnavailable('Sem chave da Groq.')
    request = urllib.request.Request(BASE + path, data=body, method='POST', headers={
        # Sem User-Agent próprio a Groq recusa o urllib com HTTP 403.
        'Authorization': 'Bearer ' + key, 'Content-Type': content_type, 'User-Agent': 'Therion/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as error:
        if error.code in (413, 429):
            block(model, error.headers.get('retry-after'))
        raise GroqUnavailable(f'Groq recusou: HTTP {error.code}.') from None
    except (OSError, ValueError) as error:  # rede, DNS, TLS, timeout
        raise GroqUnavailable(f'Groq inacessível: {type(error).__name__}.') from None
    if len(raw) > 2_000_000:
        raise GroqUnavailable('Resposta da Groq acima do limite.')
    try:
        result = json.loads(raw)
    except ValueError:
        raise GroqUnavailable('Resposta da Groq inválida.') from None
    if not isinstance(result, dict):
        raise GroqUnavailable('Resposta da Groq inválida.')
    return result


def chat_body(payload):
    """Converte o pedido no formato do Ollama para o da Groq (OpenAI)."""
    messages = payload.get('messages') or []
    if any(not isinstance(row, dict) or row.get('images') for row in messages):
        raise GroqUnavailable('Pedido com imagem fica no modelo local.')
    options = payload.get('options') or {}
    body = {'model': CHAT_MODEL, 'messages': [{'role': row['role'], 'content': row.get('content', '')} for row in messages],
            'temperature': options.get('temperature', 0),
            'reasoning_effort': 'default' if payload.get('think') is True else 'none'}
    body['max_completion_tokens'] = min(options.get('num_predict') or MAX_OUTPUT, MAX_OUTPUT)
    schema = payload.get('format')
    if isinstance(schema, dict):
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'resposta', 'schema': schema}}
    elif schema == 'json':
        body['response_format'] = {'type': 'json_object'}
    return body


def chat(payload, timeout):
    result = post('chat/completions', json.dumps(chat_body(payload)).encode('utf-8'), 'application/json', timeout, CHAT_MODEL)
    try:
        content = result['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise GroqUnavailable('Resposta da Groq sem texto.') from None
    if not isinstance(content, str):
        raise GroqUnavailable('Resposta da Groq sem texto.')
    return content
