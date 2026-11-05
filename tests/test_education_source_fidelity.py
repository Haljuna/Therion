"""Contexto literal sustenta interpretação; não filtra respostas por palavras."""
import json
from unittest.mock import MagicMock, patch
from therion.context.source_education import formation_context
from therion.context.second_brain import SecondBrainReader
from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator

PROFILE = '''# Perfil fictício
## Formação
### Faculdade
- Curso: Engenharia Biomédica
- Período letivo atual: 2028.1
- Disciplinas: Geometria Descritiva
### Formação técnica
- Curso técnico em Instrumentação no Instituto Fictício
- Período: 2020 a 2022
- Situação: concluído
### Outros assuntos
Dados que não são necessários ao contexto de formação.
'''


def test_search_preserves_section_and_retains_formation_qualifiers_from_same_source(tmp_path):
    (tmp_path/'Perfil.md').write_text(PROFILE, encoding='utf-8')
    reader = SecondBrainReader(str(tmp_path), [str(tmp_path)])
    result = reader.search_notes('Geometria Descritiva')[0]
    assert 'Faculdade' in result.context and 'Engenharia Biomédica' in result.context
    assert 'Instrumentação' not in result.context
    assert 'Formação técnica' in result.formation_context
    assert 'Situação: concluído' in result.formation_context
    assert 'Período letivo atual: 2028.1' in result.formation_context
    assert 'Outros assuntos' not in result.formation_context
    assert len(result.context) <= 700 and len(result.formation_context) <= 1400
    assert result.version


def test_context_does_not_infer_missing_status_or_read_fields_from_code():
    text = '# Formação\nCurso: Engenharia Biomédica\n```text\nCurso: Curso inventado\nSituação: concluído\n```'
    context = formation_context(text)
    assert 'Engenharia Biomédica' in context
    assert 'concluído' not in context and 'inventado' not in context


def test_context_keeps_same_section_courses_and_periods_in_source_order():
    text = '# Cursos\nCurso: Engenharia Biomédica\nPeríodo letivo atual: 2028.1\nCurso técnico em Instrumentação\nSituação: concluído\nPeríodo: 2020 a 2022'
    assert formation_context(text) == text


def test_context_limit_is_explicit_and_does_not_make_up_status():
    text = '\n'.join(f'## Curso {i}\nCurso: Formação fictícia {i}\nSituação: em andamento' for i in range(40))
    context = formation_context(text)
    assert len(context) <= 1400
    assert context.endswith('[Contexto de formação parcial]')


def test_reasoning_uses_configured_model_source_fields_and_user_correction():
    provider = OllamaProvider(model='modelo-configurado', think=True)
    evidence = {'kind': 'search', 'matches': [{'path': 'Perfil.md', 'snippet': 'Geometria Descritiva',
                 'formation_context': formation_context(PROFILE)}]}
    answer = 'Você cursa Engenharia Biomédica e já concluiu o técnico em Instrumentação.'
    with patch.object(provider, '_send_request', return_value=json.dumps({'message': answer})) as send:
        assert provider.describe_result('qual formação?', evidence, {'recent_turns': [
            {'role': 'user', 'text': 'Já terminei o técnico.'},
            {'role': 'therion', 'text': 'Resposta anterior incorreta.'}]}) == answer
    payload = send.call_args.args[0]
    assert payload['model'] == 'modelo-configurado' and payload['think'] is True
    assert payload['options']['num_predict'] == 2048
    assert send.call_args.kwargs['timeout'] <= 45
    data = json.loads(payload['messages'][1]['content'])
    assert data['declaracoes_recentes_do_usuario'] == ['Já terminei o técnico.']
    assert data['evidencias'] == evidence


def test_source_description_respects_reasoning_disabled_configuration():
    provider = OllamaProvider(think=False)
    with patch.object(provider, '_send_request', return_value='{"message":"Formação descrita."}') as send:
        provider.describe_result('leia', {'kind': 'note', 'formation_context': formation_context(PROFILE)}, {})
    assert send.call_args.args[0]['think'] is False


def test_search_sends_source_context_and_preserves_natural_interpretation(tmp_path):
    vault = tmp_path/'vault'
    project = vault/'10 - Projetos'/'Therion'
    project.mkdir(parents=True)
    note = project/'Perfil fictício.md'
    note.write_text(PROFILE, encoding='utf-8')
    original = note.read_bytes()
    provider = MagicMock()
    answer = 'Geometria Descritiva integra sua graduação atual; seu técnico em Instrumentação já foi concluído.'
    provider.describe_result.return_value = answer
    assistant = Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'), ai_core=AICore(provider, []))
    try:
        result = assistant.process_command('busque no Segundo Cérebro Geometria Descritiva')
        assert result.status == 'success' and result.speech_message == answer
        assert result.message.startswith(answer) and 'Perfil fictício.md' in result.message
        assert note.read_bytes() == original
        evidence = provider.describe_result.call_args.args[1]
        assert 'Situação: concluído' in evidence['matches'][0]['formation_context']
        assert evidence['partial'] is True
        provider.generate.assert_not_called()
    finally:
        assistant.close()


def test_followup_preserves_model_reasoning_without_status_word_filter():
    provider = MagicMock()
    answer = 'Você concluiu o técnico. Atualmente cursa Engenharia Biomédica.'
    provider.generate.return_value = AIResponse(type='chat', message=answer)
    outcome = AICore(provider, []).classify_detailed('qual é o curso atual?', {'last_tool_evidence': {'kind': 'note', 'content': PROFILE}})
    assert outcome.response.message == answer


def test_natural_uncertainty_is_not_blocked_by_status_words():
    provider = MagicMock()
    answer = 'A nota cita Engenharia Biomédica, mas não informa se você está cursando ou se já concluiu o curso.'
    provider.describe_result.return_value = answer
    evidence = {'kind': 'note', 'content': '# Formação\nCurso: Engenharia Biomédica'}
    assert AICore(provider, []).describe_result('qual é a situação?', evidence, {}) == answer
