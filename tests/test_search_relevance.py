"""Ranking e contenção verificados somente em notas fictícias."""
import builtins
import os

import pytest

from therion.context.read_scope import ReadScope
from therion.context.second_brain import SearchTrace, SecondBrainReader


@pytest.fixture
def notes(tmp_path):
    root = tmp_path / 'notas'
    root.mkdir()
    def add(name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path
    return root, add, SecondBrainReader(str(tmp_path), [str(root)])


def test_exact_title_beats_filename_and_content_regardless_of_scan_order(notes):
    root, add, reader = notes
    add('a/conteudo.md', '# Introdução\nPreparar a prova amanhã.')
    add('b/prova.md', '# Exercícios\nRevisão para prova.')
    add('z/titulo.md', '# PROVA ###\nRevisão final.')
    for _ in range(3):
        found = reader.search_notes('prova', max_results=2)
        assert [r.path for r in found] == ['notas/z/titulo.md', 'notas/b/prova.md']
        assert 'PROVA' in found[0].snippet


def test_overlapping_roots_deduplicate_and_order_is_independent_of_roots(notes):
    root, add, reader = notes
    add('b.md', 'prova')
    add('a.md', 'prova')
    add('sub/c.md', 'prova')
    expected = ['notas/a.md', 'notas/b.md', 'notas/sub/c.md']
    for roots in ([str(root), str(root / 'sub')], [str(root / 'sub'), str(root), str(root)]):
        reader.allowed_roots = roots
        trace = SearchTrace()
        assert [r.path for r in reader.search_notes('prova', trace=trace)] == expected
        assert trace.used_roots == roots


@pytest.mark.parametrize('prefix', [
    '---\ntitle: Prova\n---\n',
    '```md\n# Prova\n```\n',
    '~~~\n# Prova\n~~~\n',
])
def test_metadata_and_code_headings_do_not_outrank_real_title(notes, prefix):
    _, add, reader = notes
    add('a.md', prefix + '# Outra nota\nprova')
    add('z.md', '# Prova\nExercício')
    assert reader.search_notes('prova')[0].path == 'notas/z.md'


def test_whole_words_limits_and_snippet_length_are_preserved(notes):
    _, add, reader = notes
    add('aprovação.md', 'aprovação, comprovado e provas')
    add('exato.md', ('palavra ' * 70) + 'prova' + (' trecho' * 70))
    short = reader.search_notes('prova', snippet_length=40)
    long = reader.search_notes('prova', snippet_length=200)
    assert len(short) == len(long) == 1
    assert 'prova' in short[0].snippet
    assert len(short[0].snippet) < len(long[0].snippet)
    assert reader.search_notes('prova', max_results=0) == []
    assert reader.search_notes('prova', max_results=-1) == []


@pytest.mark.parametrize('scoped', [False, True])
@pytest.mark.parametrize('operation', ['search', 'read'])
def test_file_link_escape_is_rejected_before_open(notes, tmp_path, monkeypatch, scoped, operation):
    root, add, reader = notes
    link = add('link.md', 'placeholder')
    outside = tmp_path / 'privado.md'
    outside.write_text('prova confidencial fictícia', encoding='utf-8')
    realpath, original_open = os.path.realpath, builtins.open
    def resolve(path, *args, **kwargs):
        return str(outside) if os.path.abspath(path) == str(link) else realpath(path, *args, **kwargs)
    def guarded_open(path, *args, **kwargs):
        assert os.path.abspath(path) not in {str(link), str(outside)}, 'tentativa de ler destino proibido'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(os.path, 'realpath', resolve)
    monkeypatch.setattr(builtins, 'open', guarded_open)
    scope = ReadScope('teste', (str(root),)) if scoped else None
    if operation == 'search':
        assert reader.search_notes('prova', scope=scope) == []
    else:
        assert not reader.read_note(str(link), scope=scope).success


def test_directory_escape_is_pruned_before_traversal(notes, tmp_path, monkeypatch):
    root, add, reader = notes
    link = root / 'link'
    link.mkdir()
    outside = tmp_path / 'externo'
    outside.mkdir()
    realpath = os.path.realpath
    monkeypatch.setattr(os.path, 'realpath', lambda path, *a, **kw:
                        str(outside) if os.path.abspath(path) == str(link) else realpath(path, *a, **kw))
    def walk(path, **kwargs):
        directories = ['link']
        yield str(root), directories, []
        assert directories == [], 'diretório fora da raiz deveria ser podado'
    monkeypatch.setattr(os, 'walk', walk)
    assert reader.search_notes('prova') == []


def test_scope_only_narrows_and_does_not_mutate_authorization(notes):
    root, add, reader = notes
    add('outra.md', '# Prova')
    add('sub/nota.md', 'prova')
    original = list(reader.allowed_roots)
    trace = SearchTrace()
    scoped = ReadScope('restrito', (str(root / 'sub'),))
    assert [r.path for r in reader.search_notes('prova', scope=scoped, trace=trace)] == ['notas/sub/nota.md']
    assert trace.used_roots == [os.path.normcase(str(root / 'sub'))]
    assert reader.allowed_roots == original
    assert reader.search_notes('prova', scope=ReadScope('negado', ())) == []


def test_multiple_file_links_to_same_authorized_note_are_not_repeated(notes, monkeypatch):
    _, add, reader = notes
    target = add('original.md', '# Prova\nNota fictícia')
    alias = add('alias.md', 'placeholder')
    realpath = os.path.realpath
    monkeypatch.setattr(os.path, 'realpath', lambda path, *a, **kw:
                        str(target) if os.path.abspath(path) == str(alias) else realpath(path, *a, **kw))
    found = reader.search_notes('prova')
    assert [r.path for r in found] == ['notas/original.md']


def test_root_redirected_outside_authorization_is_not_traversed(notes, tmp_path, monkeypatch):
    root, _, reader = notes
    realpath = os.path.realpath
    monkeypatch.setattr(os.path, 'realpath', lambda path, *a, **kw:
                        str(tmp_path / 'fora') if os.path.abspath(path) == str(root) else realpath(path, *a, **kw))
    monkeypatch.setattr(os, 'walk', lambda *a, **kw: pytest.fail('raiz proibida percorrida'))
    trace = SearchTrace()
    assert reader.search_notes('prova', trace=trace) == []
    assert trace.used_roots == []
