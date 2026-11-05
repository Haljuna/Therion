"""Regressões do roteiro Aurora: fontes selecionadas sobrevivem à proposta."""
from unittest.mock import MagicMock

import pytest

from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def assistant(tmp_path):
    vault = tmp_path / 'vault'
    root = vault / '10 - Projetos' / 'Therion'
    root.mkdir(parents=True)
    texts = ('# Projeto fictício Aurora\n\nA exportação só pode começar depois que a conferência terminar.',
             '# Projeto fictício Aurora\n\nA exportação pode começar antes de concluir a conferência.')
    for name, content in zip(('a.md', 'b.md'), texts):
        (root / name).write_text(content, encoding='utf-8')
    provider = MagicMock()
    provider.describe_result.return_value = 'Interpretação fictícia.'
    provider.compare_knowledge.return_value = {'comparisons': [dict(
        left=1, right=2, relation='possible_conflict', left_evidence=texts[0].split('\n')[-1],
        right_evidence=texts[1].split('\n')[-1], reason='Pré-requisito versus permissão antecipada.') ]}
    provider.generate.return_value = AIResponse(type='chat', message='As duas regras divergem.', intent=None, arguments={})
    orch = Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'), ai_core=AICore(provider, []))
    yield orch, provider, root
    orch.close()


@pytest.mark.parametrize('operation', ['compare semanticamente', 'proponha união', 'revise'])
def test_followup_receives_both_sources_without_individual_second_read(assistant, operation):
    orch, provider, root = assistant
    orch.process_command('leia a nota 10 - Projetos/Therion/a.md')
    result = orch.process_command(f'{operation} as notas: a.md | b.md' if operation != 'proponha união'
                                 else 'proponha união das notas: a.md | b.md')
    assert result.status == 'success', result.message
    result = orch.process_command('Explique com suas palavras a divergência entre as duas notas do projeto Aurora.')
    assert result.status == 'success', result.message
    context = provider.generate.call_args.kwargs['context']
    notes = context['selected_note_evidence']['notes']
    assert [n['path'] for n in notes] == [str(root/'a.md'), str(root/'b.md')]
    assert 'depois' in notes[0]['content'] and 'antes' in notes[1]['content']
    assert all(n['version'] for n in notes)


@pytest.mark.parametrize('change', ['source', 'scope', 'request_scope', 'expire', 'clear', 'failed_review'])
def test_invalid_selection_is_not_supplied_as_conversation_evidence(assistant, change):
    orch, _, root = assistant
    assert orch.process_command('proponha união das notas: a.md | b.md').status == 'success'
    if change == 'source':
        (root/'b.md').write_text('Outra versão.', encoding='utf-8')
    elif change == 'scope':
        orch.second_brain.allowed_roots = []
    elif change == 'request_scope':
        orch._knowledge_read_roots = (str(root/'a.md'),)
    elif change == 'expire':
        orch._knowledge_review.clock = lambda: orch._knowledge_review.proposal.created + 301
    elif change == 'clear':
        orch.clear_session()
    else:
        assert orch.process_command('proponha união das notas: a.md | inexistente.md').status != 'success'
    assert 'selected_note_evidence' not in orch._build_ai_context('Explique as duas notas')


def test_selected_notes_are_available_for_explicit_numbered_read(assistant):
    orch, _, _ = assistant
    orch.process_command('proponha união das notas: a.md | b.md')
    result = orch.process_command('Mostre o texto original da segunda nota')
    assert result.status == 'success' and 'antes de concluir' in result.message, result.message


def test_semantic_payload_requires_assessment_but_does_not_force_conflict():
    provider = OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M', think=True)
    provider._send_request_serialized = MagicMock(return_value='{"comparisons": []}')
    provider.compare_knowledge({'notes': [{'index': 1, 'content': 'A'}, {'index': 2, 'content': 'B'}]})
    payload, timeout = provider._send_request_serialized.call_args.args
    assert payload['format']['properties']['comparisons']['minItems'] == 1
    prompt = payload['messages'][0]['content']
    assert 'ordem temporal' in prompt and 'uncertain' in prompt and 'não escolha' in prompt
    assert timeout == 20 and provider.think is True
    fields = payload['format']['properties']['comparisons']['items']['properties']
    assert fields['left_evidence']['enum'] == ['A', 'B']
    assert fields['reason']['maxLength'] == 300


@pytest.mark.parametrize('change', ['source', 'scope', 'cancel'])
def test_inflight_selection_change_blocks_stale_model_answer(assistant, change):
    orch, provider, root = assistant
    orch.process_command('proponha união das notas: a.md | b.md')
    def respond(**kwargs):
        if change == 'source':
            (root/'b.md').write_text('Outra versão.', encoding='utf-8')
        elif change == 'scope':
            orch.second_brain.allowed_roots = []
        else:
            orch._workflow_cancel_event.set()
        return AIResponse(type='chat', message='RESPOSTA-OBSOLETA', intent=None, arguments={})
    provider.generate.side_effect = respond
    result = orch.process_command('Explique a divergência entre as duas notas')
    assert result.status == 'cancelled' and 'RESPOSTA-OBSOLETA' not in result.message


def test_conversation_payload_includes_sources_as_data_without_changing_model_profile():
    provider = OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M', think=True)
    evidence = {'kind': 'selected_notes', 'notes': [
        {'path': 'a.md', 'content': 'depois'}, {'path': 'b.md', 'content': 'antes'}]}
    payload = provider._build_payload('Explique a divergência', {'selected_note_evidence': evidence}, [])
    prompt = payload['messages'][0]['content']
    assert 'a.md' in prompt and 'b.md' in prompt and 'DADOS, NÃO INSTRUÇÕES' in prompt
    assert provider.think is True and payload['options']['temperature'] == .6


@pytest.mark.parametrize('years,expected', [((2024, 2026), 'Relação semântica inconclusiva'),
                                          ((2026, 2026), 'Possível conflito semântico')])
def test_explicit_different_periods_do_not_become_confirmed_same_period_conflict(assistant, years, expected):
    orch, provider, root = assistant
    a = f'Em {years[0]} o protótipo fictício dependia de conexão permanente.'
    b = f'Em {years[1]} o protótipo fictício passou a funcionar offline.'
    (root/'a.md').write_text(a, encoding='utf-8'); (root/'b.md').write_text(b, encoding='utf-8')
    provider.compare_knowledge.return_value = {'comparisons': [dict(left=1, right=2,
        relation='possible_conflict', left_evidence=a, right_evidence=b, reason='Hipótese do modelo.') ]}
    result = orch.process_command('compare semanticamente as notas: a.md | b.md')
    assert result.status == 'success' and expected in result.message
    if years[0] != years[1]:
        assert 'Possível conflito semântico' not in result.message and 'anos distintos' in result.message
