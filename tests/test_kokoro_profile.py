"""Identidade da receita aprovada e preservação do áudio/protocolo antigo."""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

pytest.importorskip('scipy.signal', reason='O perfil C é processado no ambiente opcional Kokoro.')

from therion.voice.kokoro_profile import PROFILE_C, prepare_profile, process_profile, equalizer


def test_mix_is_approved_80_20_without_mutating_styles():
    alex = np.ones((510, 1, 256), dtype=np.float32)
    santa = np.load(Path(__file__).parents[1] / 'therion/voice/voices/pm_santa.npy', allow_pickle=False)
    original = alex.copy()
    engine = SimpleNamespace(get_voice_style=lambda name: alex)
    prepare_profile(engine, PROFILE_C)
    np.testing.assert_array_equal(engine._therion_voice_style, .8 * alex + .2 * santa)
    np.testing.assert_array_equal(alex, original)


def test_c_has_no_pitch_or_time_processing_and_filters_are_stable():
    pytest.importorskip('scipy.signal')
    rate = 24000
    t = np.arange(rate) / rate
    audio = (.12 * np.sin(2 * np.pi * 150 * t) + .02 * np.sin(2 * np.pi * 4800 * t))
    original = audio.copy()
    output = process_profile(audio, rate, PROFILE_C)
    assert output.shape == audio.shape and np.isfinite(output).all()
    assert abs(np.sqrt(np.mean(output ** 2)) - .08) < 1e-10
    assert np.max(np.abs(output)) <= .98
    np.testing.assert_array_equal(audio, original)
    for row in equalizer(rate):
        assert np.all(np.abs(np.roots(row[3:])) < 1)
    # Frequency and sample locations survive, independently of gain/EQ.
    assert np.argmax(np.abs(np.fft.rfft(output))[1:]) + 1 == 150


def test_legacy_alex_is_not_processed():
    audio = object()
    assert process_profile(audio, 24000, 'pm_alex') is audio


@pytest.mark.parametrize('invalid', [np.zeros(50), np.array([np.nan]), np.ones((2, 2))])
def test_bad_audio_fails_instead_of_playing_invalid_samples(invalid):
    pytest.importorskip('scipy.signal')
    with pytest.raises(ValueError):
        process_profile(invalid, 24000, PROFILE_C)


def test_unknown_profile_is_not_silently_replaced_with_alex():
    with pytest.raises(ValueError):
        prepare_profile(SimpleNamespace(), 'unapproved')
