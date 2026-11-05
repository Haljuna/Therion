"""Envoltória de PCM local. Falha visual nunca impede a reprodução."""
import wave
from pathlib import Path
import numpy as np


def wav_envelope(path, step_seconds=0.025):
    """Lê no máximo 120 s de PCM inteiro, em blocos; retorna níveis a 40 Hz."""
    levels = []
    with wave.open(str(Path(path)), 'rb') as audio:
        width, channels, rate = audio.getsampwidth(), audio.getnchannels(), audio.getframerate()
        if width not in (1, 2, 3, 4) or not 1 <= channels <= 8 or not 8000 <= rate <= 192000:
            return ()
        frames = max(1, round(rate * step_seconds))
        for _ in range(int(120 / step_seconds)):
            raw = audio.readframes(frames)
            if not raw:
                break
            if width == 1:
                values = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
            elif width == 3:
                b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
                values = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
                values = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
            else:
                values = np.frombuffer(raw, '<i2' if width == 2 else '<i4').astype(np.float64) / (2 ** (width * 8 - 1))
            rms = float(np.sqrt(np.mean(values * values)))
            levels.append(min(1.0, max(0.0, (rms - 0.003) * 5)))
    return tuple(levels)
