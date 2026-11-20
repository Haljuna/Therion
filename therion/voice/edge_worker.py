"""Síntese Edge TTS opcional, isolada; sem chave, cobrança ou fallback pago.

O texto é enviado ao serviço online somente com --allow-online.
Não importa dependências de rede/áudio no processo da interface.
"""
import argparse
import array
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import time
import tempfile
import uuid
import wave

try:
    from .kokoro_worker import chunk_speech
    from .providers import EDGE_VOICES
except ImportError:
    from kokoro_worker import chunk_speech
    from providers import EDGE_VOICES

VOICES = EDGE_VOICES
MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_SECONDS = 120
RATE = '+12%'  # escolhida pelo usuário em 2026-11-16: fala menos pausada
PITCH = '-8Hz'  # amostra "E" escolhida em 2026-11-16 (F:\Therion\tts-tests\edge\amostras)


def trim_silence(pcm, threshold=300, before=0.05, after=0.30):
    """Encurta o silêncio que o Edge põe nas bordas (~0,15 s e ~0,77 s) para uma pausa natural."""
    samples = array.array('h');samples.frombytes(pcm)
    start, end = 0, len(samples)
    while start < end and abs(samples[start]) <= threshold:start += 1
    if start == end:return pcm
    while abs(samples[end - 1]) <= threshold:end -= 1
    return samples[max(0, start - int(before * 24000)):min(len(samples), end + int(after * 24000))].tobytes()


async def download_audio(text, voice, communicate):
    if not isinstance(text, str) or not text.strip() or len(text) > 2000 or voice not in VOICES:
        raise ValueError('Entrada de síntese inválida.')
    content = bytearray()
    client = communicate(text, voice=voice, rate=RATE, pitch=PITCH, proxy=None, connect_timeout=8, receive_timeout=20)
    async for chunk in client.stream():
        if chunk.get('type') == 'audio':
            audio = chunk.get('data')
            if not isinstance(audio, bytes) or len(content) + len(audio) > MAX_AUDIO_BYTES:
                raise ValueError('Resposta de áudio acima do limite.')
            content.extend(audio)
    if not content:
        raise ValueError('O serviço não retornou áudio.')
    return bytes(content)


def decode_wav(content, output):
    import av
    output = Path(output)
    temporary = output.with_suffix('.wav.partial')
    pcm = bytearray()
    resampler = av.AudioResampler(format='s16', layout='mono', rate=24000)
    try:
        with av.open(io.BytesIO(content), format='mp3') as source:
            def write(frame):
                if len(pcm) // 2 + frame.samples > 24000 * MAX_SECONDS:
                    raise ValueError('Duração de áudio acima do limite.')
                # s16 mono tem dois bytes por amostra; o plano pode incluir
                # padding de alinhamento. Não exigir NumPy no ambiente de voz.
                pcm.extend(bytes(frame.planes[0])[:frame.samples * 2])
            for frame in source.decode(audio=0):
                for converted in resampler.resample(frame):write(converted)
            for converted in resampler.resample(None):write(converted)
        if not pcm:
            raise ValueError('Áudio vazio.')
        trimmed = trim_silence(bytes(pcm))
        with wave.open(str(temporary), 'wb') as target:
            target.setnchannels(1);target.setsampwidth(2);target.setframerate(24000)
            target.writeframes(trimmed)
        temporary.replace(output)
        return round(len(trimmed) / 2 / 24000, 3)
    finally:
        temporary.unlink(missing_ok=True)


async def synthesize(request, voice, communicate, emit):
    text = request.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Texto inválido.')
    base = Path(request['output'])
    if not base.is_absolute() or not base.parent.is_dir() or base.suffix != '.wav':
        raise ValueError('Destino de áudio inválido.')
    parts = chunk_speech(text) if request.get('stream') else [text]
    for index, part in enumerate(parts):
        started = time.perf_counter()
        content = await asyncio.wait_for(download_audio(part, voice, communicate), timeout=40)
        output = base if index == 0 else base.with_name(f'{base.stem}-{index}{base.suffix}')
        duration = decode_wav(content, output)
        emit({'event': 'audio', 'id': request.get('id'), 'part': index,
              'last': index == len(parts)-1, 'seconds': round(time.perf_counter()-started, 3),
              'audio_seconds': duration})


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--allow-online', action='store_true')
    parser.add_argument('--voice', choices=VOICES, default=VOICES[0])
    args = parser.parse_args()
    if not args.allow_online:
        emit({'event': 'startup_error', 'code': 'online_not_allowed'})
        return 2
    # O cliente usa trust_env=True internamente. Este processo não herda
    # proxies nem autenticação netrc da conta do usuário.
    for key in list(os.environ):
        if key.casefold().endswith('_proxy'):os.environ.pop(key,None)
    os.environ['NETRC']=str(Path(tempfile.gettempdir())/('therion-no-netrc-'+uuid.uuid4().hex))
    started = time.perf_counter()
    try:
        import edge_tts
        import av
    except ImportError:
        emit({'event': 'startup_error', 'code': 'dependencies_unavailable'})
        return 2
    # Preparar o processo não faz uma solicitação de rede.
    emit({'event': 'ready', 'seconds': round(time.perf_counter()-started, 3), 'provider': 'edge'})
    with asyncio.Runner() as runner:
        for line in sys.stdin:
            request = None
            try:
                if len(line) > 20000:raise ValueError('Pedido acima do limite.')
                request = json.loads(line)
                if not isinstance(request, dict):raise ValueError('Pedido inválido.')
                runner.run(synthesize(request, args.voice, edge_tts.Communicate, emit))
            except Exception as error:
                # Não incluir texto, credenciais ou resposta remota nos logs.
                emit({'event': 'error', 'id': request.get('id') if isinstance(request, dict) else None,
                      'code': 'online_synthesis_unavailable','failure_type':type(error).__name__})
    return 0


if __name__ == '__main__':
    sys.exit(main())
