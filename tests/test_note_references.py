"""Seleção de notas fictícias, com permissões reavaliadas por chamada."""
from unittest.mock import MagicMock

import pytest

from therion.context.note_references import reference_request
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def notes(tmp_path):
    root = tmp_path / 'vault' / '10 - Projetos' / 'Therion'
    root.mkdir(parents=True)
    for name, content in [('A.md', 'Alpha conteúdo primeiro'), ('B.md', 'Alpha conteúdo segundo')]:
        (root / name).write_text(content, encoding='utf-8')
    orch = Orchestrator(vault_root=str(tmp_path / 'vault'), log_dir=str(tmp_path / 'logs'))
    return orch, root


@pytest.mark.parametrize('command,index', [('leia a segunda nota', 2), ('resuma a primeira', 1),
    ('leia o resultado 2', 2), ('abra esse resultado', None), ('mostre a última nota', -1)])
def test_reference_grammar(command, index):
    assert reference_request(command)[1] == index


@pytest.mark.parametrize('command', ['abra o Obsidian', 'resuma o primeiro plano', 'li a segunda nota', 'abrir arquivo pessoal.md'])
def test_unrelated_requests_are_not_note_selection(command):
    assert reference_request(command) is None


def test_selected_note_is_shown_and_app_executor_is_never_called(notes):
    orch, root = notes
    orch.executor = MagicMock()
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('leia a segunda nota')
    assert result.status == 'success'
    assert 'conteúdo segundo' in result.message and 'Fonte:' in result.message
    assert 'B.md' in result.message
    result = orch.process_command('leia a primeira nota')
    assert 'conteúdo primeiro' in result.message
    orch.executor.execute.assert_not_called()


def test_ambiguous_selection_and_invalid_number_do_not_read(notes):
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    assert orch.process_command('abra esse resultado').status == 'clarification'
    assert orch.process_command('99').status == 'clarification'
    result = orch.process_command('2')
    assert 'conteúdo segundo' in result.message


def test_summary_fallback_honesty_and_partial_source(notes):
    orch, root = notes
    (root / 'A.md').write_text('Alpha ' + 'x' * 5500, encoding='utf-8')
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('resuma a primeira')
    assert 'Não consegui gerar um resumo' in result.message
    assert 'Fonte:' in result.message and 'Conteúdo parcial' in result.message
    assert orch._last_tool_evidence['partial'] is True
    assert len(orch._last_tool_evidence['content']) == 5000


@pytest.mark.parametrize('mode', ['empty', 'failed', 'clear'])
def test_new_search_or_clear_invalidates_previous_results(notes, mode):
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    if mode == 'clear':
        orch.clear_session()
    else:
        if mode == 'failed':
            orch.second_brain.search_notes = MagicMock(side_effect=OSError('falha simulada'))
        orch.process_command('busque no segundo cérebro inexistente')
    result = orch.process_command('leia a primeira nota')
    assert 'conteúdo primeiro' not in result.message
    assert result.status == 'clarification'


def test_current_permissions_can_revoke_reference(notes):
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    orch.second_brain.allowed_roots = []
    assert orch.process_command('leia a primeira nota').status == 'execution_failed'


def test_original_search_restriction_is_not_widened(notes):
    orch, root = notes
    inner = root / 'restrito'
    inner.mkdir()
    (inner / 'nota.md').write_text('Alpha privado', encoding='utf-8')
    orch.process_command('raízes: 10 - Projetos/Therion/restrito :: busque no segundo cérebro Alpha')
    # Substituir o resultado por um caminho fora da restrição não concede leitura.
    from therion.context.note_references import NoteResults
    original = orch._note_results
    orch._note_results = NoteResults(('10 - Projetos/Therion/A.md',), original.roots)
    assert orch.process_command('leia a primeira nota').status == 'execution_failed'


def test_followup_scope_can_narrow_and_audit_used_root(notes):
    orch, root = notes
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('raízes: 90 - Sistema da IA :: leia a primeira nota')
    assert result.status == 'execution_failed'
    result = orch.process_command('leia a primeira nota')
    assert result.status == 'success'
    import json
    from pathlib import Path
    record = json.loads(Path(orch.audit_logger.log_path).read_text(encoding='utf-8').splitlines()[-1])
    assert [r.casefold() for r in record['used_roots']] == ['10 - projetos/therion']


def test_followup_preserves_declared_scope_audit(notes):
    import json
    from pathlib import Path
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('raízes: 10 - Projetos/Therion :: leia a primeira nota')
    assert result.status == 'success'
    record = json.loads(Path(orch.audit_logger.log_path).read_text(encoding='utf-8').splitlines()[-1])
    assert record['declared_roots'] == ['10 - Projetos/Therion']
    assert record['accepted_roots'] and record['effective_roots'] and record['used_roots']


def test_failed_scope_on_new_search_discards_old_list_and_evidence(notes):
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('raízes: ../fora :: busque no segundo cérebro Alpha')
    assert result.status == 'invalid_scope'
    assert not orch._note_results.paths and not orch._last_tool_evidence['matches']
    assert orch.process_command('leia a primeira nota').status == 'clarification'


def test_missing_note_is_controlled_and_new_explicit_request_still_works(notes):
    orch, root = notes
    orch.process_command('busque no segundo cérebro Alpha')
    (root / 'A.md').unlink()
    assert orch.process_command('leia a primeira nota').status == 'execution_failed'
    assert 'conteúdo segundo' in orch.process_command('leia a segunda nota').message


def test_reference_replaces_calendar_proposal_without_writing(notes):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    orch, _ = notes
    orch.calendar_adapter = MagicMock()
    orch._now_func = lambda: datetime(2026, 10, 9, 10, tzinfo=ZoneInfo('America/Sao_Paulo'))
    orch.process_command('busque no segundo cérebro Alpha')
    orch.process_command('marque reunião hoje às 15h')
    assert orch.process_command('leia a segunda nota').status == 'success'
    orch.process_command('sim')
    orch.calendar_adapter.create_event.assert_not_called()


def test_changed_link_destination_cannot_escape_current_roots(notes, monkeypatch, tmp_path):
    import os
    orch, root = notes
    orch.process_command('busque no segundo cérebro Alpha')
    outside = tmp_path / 'fora.md'
    outside.write_text('SEGREDO FORA', encoding='utf-8')
    realpath = os.path.realpath
    target = os.path.normcase(str(root / 'A.md'))
    def moved_link(path, *args, **kwargs):
        if os.path.normcase(str(path)) == target:
            return str(outside)
        return realpath(path, *args, **kwargs)
    monkeypatch.setattr(os.path, 'realpath', moved_link)
    result = orch.process_command('leia a primeira nota')
    assert result.status == 'execution_failed'
    assert 'SEGREDO FORA' not in result.message


def test_pending_selection_is_not_applied_after_an_unrelated_command(notes):
    orch, _ = notes
    orch.process_command('busque no segundo cérebro Alpha')
    orch.process_command('resuma esse resultado')
    orch.process_command('olá')
    result = orch.process_command('2')
    assert 'conteúdo segundo' not in result.message


def test_summary_provider_gets_selected_note_only(notes):
    from therion.core.ai_core import AICore
    orch, _ = notes
    provider = MagicMock()
    provider.describe_result.return_value = 'Resumo simulado.'
    orch.ai_core = AICore(provider, [])
    orch.process_command('busque no segundo cérebro Alpha')
    result = orch.process_command('resuma a segunda nota')
    evidence = provider.describe_result.call_args.args[1]
    assert evidence['path'].endswith('B.md')
    assert evidence['content'] == 'Alpha conteúdo segundo'
    assert result.message.startswith('Resumo simulado.')
    assert 'Fonte:' in result.message
