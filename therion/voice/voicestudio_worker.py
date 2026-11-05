"""Cliente VoiceStudio local isolado; apenas biblioteca padrão, sem carregar modelos.

Usa um perfil salvo por ID, sem proxies, redirecionamentos ou fallback de voz.
Encerrar este cliente cancela a reprodução local; o servidor pode terminar a síntese.
"""
import argparse
import io
import json
from pathlib import Path
from urllib.error import HTTPError
import sys
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import wave

try:
    from .kokoro_worker import chunk_speech
    from .providers import is_voicestudio_endpoint, is_voicestudio_voice
except ImportError:
    from kokoro_worker import chunk_speech
    from providers import is_voicestudio_endpoint, is_voicestudio_voice

MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_PROFILE_BYTES = 2 * 1024 * 1024
MAX_SECONDS = 120


class VoiceStudioError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


def local_client():
    return build_opener(ProxyHandler({}), NoRedirect())


def read_limited(response, limit):
    content = bytearray()
    while True:
        chunk = response.read(min(65536, limit + 1 - len(content)))
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > limit:
            raise VoiceStudioError('invalid_audio')


def verify_profile(endpoint, voice, client):
    if not is_voicestudio_endpoint(endpoint) or not is_voicestudio_voice(voice):
        raise VoiceStudioError('invalid_configuration')
    # Listar /v1/audio/voices enumera motores e presets e pode levar segundos.
    # A rota de perfil faz a mesma validação de existência por ID diretamente.
    url = endpoint[:-len('/v1/audio/speech')] + '/profiles/' + voice
    request = Request(url, headers={'Accept': 'application/json'})
    try:
        with client.open(request, timeout=10) as response:
            profile = json.loads(read_limited(response, MAX_PROFILE_BYTES))
    except HTTPError as error:
        if error.code == 404:
            error.close()
            raise VoiceStudioError('profile_unavailable') from error
        error.close()
        raise
    if not isinstance(profile, dict) or profile.get('id') != voice:
        raise VoiceStudioError('profile_unavailable')


def write_wav(content, output):
    """Aceita apenas PCM válido e completo; publica atomicamente para o Qt."""
    temporary = output.with_suffix('.wav.partial')
    try:
        with wave.open(io.BytesIO(content), 'rb') as source:
            channels, width, rate, frames = (source.getnchannels(), source.getsampwidth(),
                                             source.getframerate(), source.getnframes())
            if (channels not in (1, 2) or width != 2 or not 8000 <= rate <= 48000
                    or not 0 < frames <= rate * MAX_SECONDS or source.getcomptype() != 'NONE'):
                raise VoiceStudioError('invalid_audio')
            pcm = source.readframes(frames)
            if len(pcm) != frames * channels * width:
                raise VoiceStudioError('invalid_audio')
        with wave.open(str(temporary), 'wb') as target:
            target.setnchannels(channels)
            target.setsampwidth(width)
            target.setframerate(rate)
            target.writeframes(pcm)
        temporary.replace(output)
        return round(frames / rate, 3)
    except (wave.Error, EOFError) as error:
        raise VoiceStudioError('invalid_audio') from error
    finally:
        temporary.unlink(missing_ok=True)


def synthesize(request, endpoint, voice, emit, client=None):
    text = request.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise VoiceStudioError('invalid_configuration')
    base = Path(request['output'])
    if not base.is_absolute() or not base.parent.is_dir() or base.suffix != '.wav':
        raise VoiceStudioError('invalid_configuration')
    client = client or local_client()
    request_started = time.perf_counter()
    # O servidor aceita aliases genéricos: exigir perfil real evita troca silenciosa.
    verify_profile(endpoint, voice, client)
    profile_seconds = time.perf_counter() - request_started
    parts = chunk_speech(text) if request.get('stream') else [text]
    for index, part in enumerate(parts):
        started = time.perf_counter()
        payload = json.dumps({'model': 'tts-1', 'voice': voice, 'input': part,
                              'language': 'pt', 'response_format': 'wav'}, ensure_ascii=True).encode('utf-8')
        query = Request(endpoint, data=payload,
                        headers={'Content-Type': 'application/json', 'Accept': 'audio/wav'}, method='POST')
        with client.open(query, timeout=90) as response:
            if response.headers.get('Content-Type', '').split(';')[0].lower() not in (
                'audio/wav', 'audio/x-wav', 'audio/wave'
            ):
                raise VoiceStudioError('invalid_audio')
            content = read_limited(response, MAX_AUDIO_BYTES)
        received = time.perf_counter()
        output = base if index == 0 else base.with_name(f'{base.stem}-{index}{base.suffix}')
        duration = write_wav(content, output)
        finished = time.perf_counter()
        emit({'event': 'audio', 'id': request.get('id'), 'part': index,
              'last': index == len(parts) - 1, 'seconds': round(finished - started, 3),
              'audio_seconds': duration, 'profile_seconds': round(profile_seconds, 4) if index == 0 else 0.0,
              'http_seconds': round(received - started, 4), 'wav_seconds': round(finished - received, 4),
              'request_seconds': round(finished - request_started, 4)})


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--endpoint', required=True)
    parser.add_argument('--voice', required=True)
    args = parser.parse_args()
    if not is_voicestudio_endpoint(args.endpoint) or not is_voicestudio_voice(args.voice):
        emit({'event': 'startup_error', 'code': 'invalid_configuration'})
        return 2
    client = local_client()
    emit({'event': 'ready', 'provider': 'voicestudio', 'seconds': 0.0})
    for line in sys.stdin:
        request = None
        try:
            if len(line) > 20000:
                raise VoiceStudioError('invalid_configuration')
            request = json.loads(line)
            if not isinstance(request, dict):
                raise VoiceStudioError('invalid_configuration')
            synthesize(request, args.endpoint, args.voice, emit, client)
        except Exception as error:
            # Não repetir POST em erro/timeout nem registrar texto ou corpo da resposta.
            code = error.code if isinstance(error, VoiceStudioError) else 'service_unavailable'
            emit({'event': 'error', 'id': request.get('id') if isinstance(request, dict) else None,
                  'code': code, 'failure_type': type(error).__name__})
    return 0


if __name__ == '__main__':
    sys.exit(main())
