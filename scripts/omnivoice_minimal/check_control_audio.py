"""Verifica inteligibilidade das amostras sintéticas com o STT já instalado."""
import json
from pathlib import Path
import sys
import time
import wave

import numpy as np
from faster_whisper import WhisperModel

runtime = Path(sys.argv[1])
model = WhisperModel('F:/Therion/models/faster-whisper-small', device='cpu', compute_type='int8',
                     cpu_threads=2, num_workers=1, local_files_only=True)
results = []
for source in sorted(runtime.glob('jarvis-control-*.wav')):
    with wave.open(str(source)) as audio:
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32)/32768
    if rate != 16000:
        samples = np.interp(np.arange(round(len(samples)*16000/rate))*rate/16000,
                            np.arange(len(samples)), samples).astype(np.float32)
    started = time.perf_counter()
    segments, _ = model.transcribe(samples, language='pt', beam_size=5, vad_filter=True,
                                    temperature=0, condition_on_previous_text=False)
    text = ' '.join(segment.text.strip() for segment in segments)
    results.append({'file': source.name, 'synthetic_transcript': text,
                    'stt_seconds':round(time.perf_counter()-started,3)})
(runtime/'audio-check.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(results, ensure_ascii=True, indent=2))
