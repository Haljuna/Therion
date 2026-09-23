"""Testes do ReadScope — Incremento 1, Etapa 3A.1 (DEC-033)."""

from pathlib import Path

from therion.context.read_scope import ReadScope, effective_roots
from therion.context.second_brain import SearchTrace, SecondBrainReader


def _make_reader(tmp_path: Path) -> tuple[SecondBrainReader, Path, Path]:
    vault = tmp_path / "vault"
    allowed = vault / "10 - Projetos" / "Therion"
    protected = vault / "01 - Pessoal"
    allowed.mkdir(parents=True)
    protected.mkdir(parents=True)
    (allowed / "nota.md").write_text("termo_dentro aqui", encoding="utf-8")
    (protected / "privada.md").write_text("termo_privado aqui", encoding="utf-8")
    reader = SecondBrainReader(vault_root=str(vault), allowed_roots=[str(allowed)])
    return reader, allowed, protected


def test_scope_none_preserves_current_access(tmp_path: Path) -> None:
    reader, allowed, protected = _make_reader(tmp_path)
    inside = str(allowed / "nota.md")
    outside = str(protected / "privada.md")

    default = reader.read_note(inside)
    explicit_none = reader.read_note(inside, scope=None)
    denied = reader.read_note(outside, scope=None)
    found = reader.search_notes("termo_dentro", scope=None)

    assert default.success is True
    assert explicit_none.success is True
    assert explicit_none.content == default.content
    assert denied.success is False
    assert any("nota.md" in r.path for r in found)


def test_empty_scope_denies_read_and_search(tmp_path: Path) -> None:
    reader, allowed, _protected = _make_reader(tmp_path)
    inside = str(allowed / "nota.md")
    empty = ReadScope(task_id="task-empty", roots=())

    result = reader.read_note(inside, scope=empty)
    search = reader.search_notes("termo_dentro", scope=empty)

    assert result.success is False
    assert search == []


def test_intersection_restricts_to_scope_root(tmp_path: Path) -> None:
    reader, allowed, _protected = _make_reader(tmp_path)
    docs = allowed / "docs"
    docs.mkdir()
    (docs / "inside.md").write_text("termo_subpasta aqui", encoding="utf-8")
    scoped = ReadScope(task_id="task-restrict", roots=(str(docs),))

    in_scope = reader.read_note(str(docs / "inside.md"), scope=scoped)
    out_of_scope = reader.read_note(str(allowed / "nota.md"), scope=scoped)

    assert in_scope.success is True
    assert in_scope.matched_root == effective_roots(scoped, reader.allowed_roots)[0]
    assert out_of_scope.success is False
    assert out_of_scope.matched_root is None


def test_overlapping_roots_report_first_match(tmp_path: Path) -> None:
    reader, allowed, _protected = _make_reader(tmp_path)
    docs = allowed / "docs"
    docs.mkdir()
    note = docs / "inside.md"
    note.write_text("conteúdo", encoding="utf-8")
    reader.allowed_roots = [str(allowed), str(docs)]

    parent_first = reader.read_note(str(note))
    reader.allowed_roots = [str(docs), str(allowed)]
    child_first = reader.read_note(str(note))

    assert parent_first.success is True
    assert parent_first.matched_root == str(allowed)
    assert child_first.success is True
    assert child_first.matched_root == str(docs)


def test_root_outside_allowed_does_not_amplify(tmp_path: Path) -> None:
    reader, _allowed, protected = _make_reader(tmp_path)
    outside_root = ReadScope(task_id="task-outside", roots=(str(protected),))

    read = reader.read_note(str(protected / "privada.md"), scope=outside_root)
    search = reader.search_notes("termo_privado", scope=outside_root)

    assert read.success is False
    assert read.matched_root is None
    assert search == []


def test_search_trace_records_only_started_roots(tmp_path: Path) -> None:
    reader, allowed, protected = _make_reader(tmp_path)
    reader.allowed_roots = [str(allowed), str(protected)]
    trace = SearchTrace()

    results = reader.search_notes("termo_", trace=trace)

    assert len(results) == 2
    assert trace.used_roots == [str(allowed), str(protected)]


def test_allowed_roots_not_mutated_by_scope(tmp_path: Path) -> None:
    reader, allowed, _protected = _make_reader(tmp_path)
    docs = allowed / "docs"
    docs.mkdir()
    (docs / "inside.md").write_text("termo_imutavel aqui", encoding="utf-8")
    snapshot = list(reader.allowed_roots)
    scoped = ReadScope(task_id="task-immutable", roots=(str(docs),))

    read_in = reader.read_note(str(docs / "inside.md"), scope=scoped)
    read_out = reader.read_note(str(allowed / "nota.md"), scope=scoped)
    search = reader.search_notes("termo_imutavel", scope=scoped)

    assert read_in.success is True
    assert read_out.success is False
    assert search
    assert reader.allowed_roots == snapshot
    assert reader.allowed_roots is not snapshot


def test_sequential_scopes_do_not_leak(tmp_path: Path) -> None:
    reader, allowed, _protected = _make_reader(tmp_path)
    docs = allowed / "docs"
    docs.mkdir()
    (docs / "inside.md").write_text("termo_sequencial aqui", encoding="utf-8")
    snapshot = list(reader.allowed_roots)
    scope_a = ReadScope(task_id="task-a", roots=(str(docs),))
    scope_b = ReadScope(task_id="task-b", roots=())

    a_read = reader.read_note(str(docs / "inside.md"), scope=scope_a)
    b_read = reader.read_note(str(docs / "inside.md"), scope=scope_b)
    default_after = reader.read_note(str(allowed / "nota.md"))

    assert a_read.success is True
    assert b_read.success is False
    assert default_after.success is True
    assert reader.allowed_roots == snapshot
