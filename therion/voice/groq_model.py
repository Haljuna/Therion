"""Transcrição na Groq; o faster-whisper local só carrega quando a Groq falha e sai da memória depois."""
import json
import threading
import time
from types import SimpleNamespace

import numpy as np

from therion.core import groq
from therion.voice.http_model import wav_bytes

LOCAL_IDLE_SECONDS = 300
# A Groq aceita até 25 MB; 10 min de WAV 16 kHz dão ~19 MB. A conversa contínua pode passar de 30 s.
GROQ_MAX_SAMPLES = 16000 * 600


class GroqVoiceModel:
    def __init__(self, local_factory, *, clock=time.monotonic):
        self._local_factory = local_factory
        self._clock = clock
        self._local = None
        self._local_used = 0.0
        self._lock = threading.Lock()

    def transcribe(self, audio, **options):
        data = np.asarray(audio)
        if data.ndim != 1 or not len(data) or not np.isfinite(data).all():
            raise ValueError('Áudio inválido: esperado mono 16 kHz')
        try:
            if len(data) > GROQ_MAX_SAMPLES:
                raise groq.GroqUnavailable('Áudio longo demais para a Groq.')
            result = self._groq(data, options)
        except groq.GroqUnavailable as error:
            print(f'[Therion] Groq indisponível ({error}); transcrevendo no PC.')
            with self._lock:
                if self._local is None:
                    self._local = self._local_factory()
                self._local_used = self._clock()
                local = self._local
            return local.transcribe(audio, **options)
        with self._lock:
            if self._local is not None and self._clock() - self._local_used > LOCAL_IDLE_SECONDS:
                self._local = None  # a Groq voltou: libera a memória do modelo local
        return result

    @staticmethod
    def _groq(data, options):
        prompt = ' '.join(filter(None, (options.get('initial_prompt'), options.get('hotwords'))))[:600]
        fields = {'model': groq.STT_MODEL, 'language': options.get('language', 'pt'), 'temperature': '0',
                  'response_format': 'verbose_json', 'prompt': prompt}
        body = b''.join(b'--therion\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                        % (name.encode(), str(value).encode('utf-8')) for name, value in fields.items() if value)
        body += (b'--therion\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                 b'Content-Type: audio/wav\r\n\r\n' + wav_bytes(data) + b'\r\n--therion--\r\n')
        # Timeout curto: com a internet lenta é mais rápido transcrever no PC.
        result = groq.post('audio/transcriptions', body, 'multipart/form-data; boundary=therion', 6, groq.STT_MODEL)
        segments = result.get('segments')
        if not isinstance(segments, list) or len(json.dumps(result)) > 100000:
            raise groq.GroqUnavailable('Resposta de transcrição inválida.')
        # As métricas de confiança seguem para o mesmo filtro do Whisper local.
        out = [SimpleNamespace(text=str(s.get('text', '')), **{k: float(s[k]) for k in
               ('avg_logprob', 'no_speech_prob', 'compression_ratio') if isinstance(s.get(k), (int, float))})
               for s in segments if isinstance(s, dict) and str(s.get('text', '')).strip()]
        return out, SimpleNamespace(language='pt')
