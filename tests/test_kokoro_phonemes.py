"""Compatibilidade fonética local; não valida reconhecimento ou conforto acústico."""
import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from therion.voice import kokoro_worker


@pytest.fixture
def engine_and_backend(monkeypatch):
    backend = SimpleNamespace(phonemize=Mock(return_value=['oˈla.']))
    factory = Mock(return_value=backend)
    module = SimpleNamespace(EspeakBackend=factory)
    monkeypatch.setitem(sys.modules, 'phonemizer.backend', module)
    engine = SimpleNamespace(create=Mock(return_value=('synthetic-audio', 24000)))
    return engine, backend, factory


def test_reported_greeting_uses_v1_affricates(engine_and_backend):
    engine, backend, factory = engine_and_backend
    phrase = 'Bom dia, como posso te ajudar?'
    backend.phonemize.return_value = ['bˈoŋ d^ʒˈiæ, kˌomʊ pˌɔsʊ t^ʃj ˌaʒudˈar? ']
    assert kokoro_worker.create_speech(engine, phrase) == ('synthetic-audio', 24000)
    backend.phonemize.assert_called_once_with([phrase])
    engine.create.assert_called_once_with(
        'bˈoŋ ʤˈiæ, kˌomʊ pˌɔsʊ ʧj ˌaʒudˈar?',
        voice='pm_alex', speed=1.0, lang='pt-br', is_phonemes=True)
    factory.assert_called_once_with(
        language='pt-br', preserve_punctuation=True, with_stress=True,
        tie='^', language_switch='remove-flags')


@pytest.mark.parametrize('phrase', [
    'Não marque a reunião. Não autorizei!',
    'Olá, Marcus! Tudo bem?',
    'Às 15:00, dia 13/10/2026; título: Reunião de João.',
    'Prefiro “respostas curtas”, com acentos e vírgulas.',
    '  Não altere (o título) nem <nomes> ou caminhos C:\\Notas.  ',
])
def test_source_text_reaches_backend_unchanged(engine_and_backend, phrase):
    engine, backend, _ = engine_and_backend
    kokoro_worker.create_speech(engine, phrase)
    backend.phonemize.assert_called_once_with([phrase])


def test_backend_is_reused_for_same_engine_and_separate_for_another(engine_and_backend):
    engine, backend, factory = engine_and_backend
    kokoro_worker.create_speech(engine, 'Olá.')
    kokoro_worker.create_speech(engine, 'Como vai?')
    assert factory.call_count == 1
    assert backend.phonemize.call_args_list[1].args == (['Como vai?'],)
    other = SimpleNamespace(create=Mock(return_value=('audio', 24000)))
    kokoro_worker.create_speech(other, 'Bom dia.')
    assert factory.call_count == 2


def test_v1_diphthongs_and_remaining_ties_are_compatible(engine_and_backend):
    engine, backend, _ = engine_and_backend
    backend.phonemize.return_value = [' a^ɪ a^ʊ d^z d^ʒ e^ɪ o^ʊ s^s t^s t^ʃ ɔ^ɪ ə^ʊ k^a-ŋ, ˈɐ̃? ']
    kokoro_worker.create_speech(engine, 'Texto público sintético.')
    assert engine.create.call_args.args == ('I W ʣ ʤ A O S ʦ ʧ Y Q kaŋ, ˈɐ̃?',)


@pytest.mark.parametrize('invalid', [None, '', ' ', 123, 'x' * 2001])
def test_invalid_input_does_not_initialize_or_call_backend(engine_and_backend, invalid):
    engine, backend, factory = engine_and_backend
    with pytest.raises(ValueError, match='Texto inválido'):
        kokoro_worker.create_speech(engine, invalid)
    factory.assert_not_called()
    backend.phonemize.assert_not_called()
    engine.create.assert_not_called()


@pytest.mark.parametrize('invalid', [[], None, [''], ['  '], ['^--'], [None], ['a', 'b'], 'phonemes'])
def test_empty_or_invalid_phonemes_fail_without_legacy_fallback(engine_and_backend, invalid):
    engine, backend, _ = engine_and_backend
    backend.phonemize.return_value = invalid
    with pytest.raises(ValueError, match='fonemas'):
        kokoro_worker.create_speech(engine, 'Olá.')
    engine.create.assert_not_called()


def test_backend_failure_propagates_without_synthesis(engine_and_backend):
    engine, backend, _ = engine_and_backend
    backend.phonemize.side_effect = RuntimeError('synthetic backend failure')
    with pytest.raises(RuntimeError, match='synthetic backend failure'):
        kokoro_worker.create_speech(engine, 'Olá.')
    engine.create.assert_not_called()


def test_backend_initialization_failure_is_not_cached(engine_and_backend):
    engine, _, factory = engine_and_backend
    factory.side_effect = RuntimeError('synthetic initialization failure')
    with pytest.raises(RuntimeError, match='synthetic initialization failure'):
        kokoro_worker.create_speech(engine, 'Olá.')
    assert not hasattr(engine, '_therion_ptbr_backend')
    engine.create.assert_not_called()


def test_synthesis_failure_is_not_retried_with_raw_text(engine_and_backend):
    engine, backend, _ = engine_and_backend
    engine.create.side_effect = RuntimeError('synthetic synthesis failure')
    with pytest.raises(RuntimeError, match='synthetic synthesis failure'):
        kokoro_worker.create_speech(engine, 'Olá.')
    backend.phonemize.assert_called_once()
    engine.create.assert_called_once()


def test_warmup_and_requested_speech_share_the_helper(monkeypatch):
    engine = object()
    helper = Mock()
    synthesis = Mock(return_value={'event': 'audio'})
    request = {'text': 'Bom dia, como posso te ajudar?', 'output': 'synthetic.wav', 'id': 1}
    monkeypatch.setattr(kokoro_worker, 'create_engine', Mock(return_value=engine))
    monkeypatch.setattr(kokoro_worker, 'create_speech', helper)
    monkeypatch.setattr(kokoro_worker, 'synthesize', synthesis)
    monkeypatch.setattr(kokoro_worker, 'emit', Mock())
    monkeypatch.setattr(sys, 'argv', ['worker', '--serve', '--root', 'synthetic-model'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(request) + '\n'))
    kokoro_worker.main()
    helper.assert_called_once_with(engine, 'Olá.')
    synthesis.assert_called_once_with(engine, request)


def test_wav_synthesis_uses_compatible_helper(monkeypatch, tmp_path):
    engine = object()
    # Substitutos de arrays e escrita: não carrega modelo nem reproduz áudio.
    audio = [0.1, -0.1]
    numpy = SimpleNamespace(isfinite=lambda value: SimpleNamespace(all=lambda: True),
                            max=lambda value: 0.1, abs=lambda value: value)
    soundfile = SimpleNamespace(write=Mock())
    monkeypatch.setitem(sys.modules, 'numpy', numpy)
    monkeypatch.setitem(sys.modules, 'soundfile', soundfile)
    helper = Mock(return_value=(audio, 24000))
    monkeypatch.setattr(kokoro_worker, 'create_speech', helper)
    request = {'text': 'Bom dia, como posso te ajudar?', 'output': str(tmp_path / 'synthetic.wav'), 'id': 3}
    result = kokoro_worker.synthesize(engine, request)
    helper.assert_called_once_with(engine, request['text'])
    soundfile.write.assert_called_once_with(request['output'], audio, 24000, subtype='PCM_16')
    assert result['event'] == 'audio'
    assert result['id'] == 3
