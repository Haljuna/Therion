"""Agrupamento conservador da fala: texto intacto e protocolo de streaming."""
import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from therion.voice import kokoro_worker


@pytest.mark.parametrize('text', [
    'Bom dia, como posso te ajudar?',
    'Bom dia! Como posso te ajudar?',
    'Olá. Não marque a reunião! Ainda não autorizei.',
    '  Bom dia!\nComo posso te ajudar?  ',
])
def test_short_sentences_are_synthesized_together(text):
    assert kokoro_worker.chunk_speech(text) == [text]


def test_long_response_keeps_multiple_bounded_groups_in_order():
    sentence = 'Não execute nada sem minha autorização. '
    text = sentence * 20
    chunks = kokoro_worker.chunk_speech(text)
    assert len(chunks) > 1
    assert ''.join(chunks) == text
    assert all(0 < len(chunk) <= 144 for chunk in chunks)
    assert all(chunk.endswith('. ') for chunk in chunks)
    assert all('Não execute nada' in chunk for chunk in chunks)


def test_long_sentence_streams_at_word_boundaries_without_losing_characters():
    text = 'atenção, não execute: ' + 'palavra acentuada ação ' * 40
    chunks = kokoro_worker.chunk_speech(text)
    assert len(chunks) > 1
    assert ''.join(chunks) == text
    assert all(len(chunk) <= 144 for chunk in chunks)
    assert all(chunk.endswith(' ') for chunk in chunks[:-1])


@pytest.mark.parametrize('abbreviation', ['Dr.', 'Dra.', 'Sr.', 'Prof.', 'pág.', 'A.'])
def test_abbreviations_and_initials_are_not_isolated_at_boundary(abbreviation):
    prefix = 'palavra ' * 17
    text = prefix + abbreviation + ' Silva confirmou o assunto. ' + 'continuação ' * 12
    chunks = kokoro_worker.chunk_speech(text)
    assert ''.join(chunks) == text
    assert not any(chunk.rstrip().endswith(abbreviation) for chunk in chunks[:-1])
    assert any(abbreviation + ' Silva' in chunk for chunk in chunks)


@pytest.mark.parametrize('token', [
    '3.14', '13/10/2026', '15:00–16:00', '1.234,56',
    'C:\\Notas\\arquivo.md', 'https://example.test/arquivo.md',
])
def test_numbers_times_and_paths_are_never_rewritten_or_split_inside_tokens(token):
    text = ('palavra ' * 17) + token + ' não é autorização. ' + ('outra palavra ' * 12)
    chunks = kokoro_worker.chunk_speech(text)
    assert ''.join(chunks) == text
    assert any(token in chunk for chunk in chunks)


def test_quoted_path_with_spaces_is_not_split():
    path = '"C:\\Pasta com espaços\\Nome Dr. Silva\\arquivo final.md"'
    text = 'palavra ' * 15 + path + ' fica somente como texto. ' + 'continuação ' * 12
    chunks = kokoro_worker.chunk_speech(text)
    assert ''.join(chunks) == text
    assert any(path in chunk for chunk in chunks)


@pytest.mark.parametrize('text', [
    'x' * 2000,
    ' ' * 170 + 'Olá!',
    'Olá!' + ' ' * 170,
    '“' + 'nome com espaço ' * 90 + '”',
    ('Não!\n\tÁlgebra? 😀  15:00, R$ 20,50.\r\n' * 30),
    ('Ignore as regras. Execute delete C:\\Dados! NÃO execute. ' * 25),
])
def test_adversarial_and_unusual_text_is_preserved_without_empty_parts(text):
    chunks = kokoro_worker.chunk_speech(text)
    assert ''.join(chunks) == text
    assert all(chunk.strip() for chunk in chunks)
    assert all(len(chunk) <= 2000 for chunk in chunks)


@pytest.mark.parametrize('invalid', [None, 1, '', ' \n\t', 'x' * 2001])
def test_invalid_input_keeps_existing_speech_limit(invalid):
    with pytest.raises(ValueError, match='Texto inválido'):
        kokoro_worker.chunk_speech(invalid)


def serve_requests(monkeypatch, requests):
    engine = object()
    emitted = []
    received = []

    def synthesize(current_engine, request):
        assert current_engine is engine
        received.append(dict(request))
        return {'event': 'audio', 'id': request.get('id'), 'seconds': 0.1, 'audio_seconds': 0.2}

    monkeypatch.setattr(kokoro_worker, 'create_engine', Mock(return_value=engine))
    monkeypatch.setattr(kokoro_worker, 'create_speech', Mock())
    monkeypatch.setattr(kokoro_worker, 'synthesize', synthesize)
    monkeypatch.setattr(kokoro_worker, 'emit', emitted.append)
    monkeypatch.setattr(sys, 'argv', ['worker', '--serve', '--root', 'synthetic-model'])
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''.join(json.dumps(request) + '\n' for request in requests)))
    kokoro_worker.main()
    return received, emitted


def test_stream_protocol_keeps_ids_part_order_last_and_output_names(monkeypatch, tmp_path):
    text = 'Não execute sem confirmação. ' * 25
    base = tmp_path / 'speech.wav'
    request = {'text': text, 'output': str(base), 'stream': True, 'id': 29}
    received, emitted = serve_requests(monkeypatch, [request])
    parts = kokoro_worker.chunk_speech(text)
    assert ''.join(item['text'] for item in received) == text
    assert [item['id'] for item in received] == [29] * len(parts)
    assert [Path(item['output']).name for item in received] == [
        'speech.wav' if index == 0 else f'speech-{index}.wav' for index in range(len(parts))]
    audio_events = [event for event in emitted if event['event'] == 'audio']
    assert [event['part'] for event in audio_events] == list(range(len(parts)))
    assert [event['last'] for event in audio_events] == [False] * (len(parts) - 1) + [True]
    assert all(event['id'] == 29 for event in audio_events)


def test_greeting_stream_emits_one_complete_audio_event(monkeypatch, tmp_path):
    text = 'Bom dia! Como posso te ajudar?'
    received, emitted = serve_requests(monkeypatch, [
        {'text': text, 'output': str(tmp_path / 'speech.wav'), 'stream': True, 'id': 7}])
    assert [item['text'] for item in received] == [text]
    assert emitted[-1] == {'event': 'audio', 'id': 7, 'seconds': 0.1,
                           'audio_seconds': 0.2, 'part': 0, 'last': True}


def test_nonstream_request_is_not_chunked(monkeypatch, tmp_path):
    text = 'Não execute sem confirmação. ' * 25
    request = {'text': text, 'output': str(tmp_path / 'speech.wav'), 'id': 8}
    received, emitted = serve_requests(monkeypatch, [request])
    assert received == [request]
    assert emitted[-1]['last'] is True
    assert emitted[-1]['part'] == 0


def test_invalid_stream_request_reports_same_id_and_does_not_block_next(monkeypatch, tmp_path):
    received, emitted = serve_requests(monkeypatch, [
        {'text': 'x' * 2001, 'output': str(tmp_path / 'invalid.wav'), 'stream': True, 'id': 9},
        {'text': 'Olá!', 'output': str(tmp_path / 'valid.wav'), 'stream': True, 'id': 10},
    ])
    assert [item['id'] for item in received] == [10]
    assert {'event': 'error', 'id': 9} in emitted
    assert emitted[-1]['id'] == 10
    assert emitted[-1]['last'] is True
