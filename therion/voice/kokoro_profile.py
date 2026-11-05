"""Perfil C aprovado: mistura nativa Alex/Santa e equalização discreta."""
import hashlib
from functools import lru_cache
from pathlib import Path

PROFILE_C = 'alex_santa_c'
SUPPORTED_PROFILES = ('pm_alex', PROFILE_C)
C3_BANDS = ((280., -.5, .75), (1800., .6, .8), (4800., .7, .8))


def prepare_profile(engine, profile):
    if profile not in SUPPORTED_PROFILES:
        raise ValueError('Perfil de voz Kokoro desconhecido.')
    engine._therion_voice_profile = profile
    if profile == 'pm_alex':
        engine._therion_voice_style = 'pm_alex'
        return
    import numpy as np
    # Validar a dependência antes de anunciar que o worker está pronto.
    from scipy.signal import sosfilt  # noqa: F401
    asset = Path(__file__).with_name('voices') / 'pm_santa.npy'
    if hashlib.sha256(asset.read_bytes()).hexdigest() != '036e409b2e99ca9ee391a98bc659b5c0e1a8097adc61ca779fe176dc54580a13':
        raise ValueError('O estilo Santa difere do arquivo aprovado.')
    santa = np.load(asset, allow_pickle=False)
    alex = engine.get_voice_style('pm_alex')
    if (santa.shape != (510, 1, 256) or santa.dtype != np.float32
            or alex.shape != santa.shape or not np.isfinite(santa).all()
            or not np.isfinite(alex).all()):
        raise ValueError('Os estilos Alex/Santa são inválidos ou incompatíveis.')
    engine._therion_voice_style = .8 * alex + .2 * santa


@lru_cache(maxsize=4)
def equalizer(rate):
    import numpy as np
    rows = []
    for hz, db, q in C3_BANDS:
        if rate <= 2 * hz:
            raise ValueError('Taxa de áudio incompatível com a equalização C3.')
        amplitude = 10 ** (db / 40)
        omega = 2 * np.pi * hz / rate
        alpha = np.sin(omega) / (2 * q)
        numerator = np.array([1 + alpha * amplitude, -2 * np.cos(omega), 1 - alpha * amplitude])
        denominator = np.array([1 + alpha / amplitude, -2 * np.cos(omega), 1 - alpha / amplitude])
        rows.append(np.r_[numerator / denominator[0], denominator / denominator[0]])
    return np.array(rows)


def normalize(audio):
    import numpy as np
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError('Áudio inválido para a voz C.')
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < 1e-5:
        raise ValueError('Áudio sem sinal suficiente para a voz C.')
    return audio * min(.08 / rms, .98 / np.max(np.abs(audio)))


def process_profile(audio, rate, profile):
    if profile == 'pm_alex':
        return audio
    if profile != PROFILE_C:
        raise ValueError('Perfil de voz Kokoro desconhecido.')
    from scipy.signal import sosfilt
    # Mesma receita da amostra C: normalizar, equalizar, normalizar.
    # Preserva todos os samples e a velocidade nativa; não usa PSOLA.
    return normalize(sosfilt(equalizer(rate), normalize(audio)))
