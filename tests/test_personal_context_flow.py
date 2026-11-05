"""Contexto pessoal fictício, isolamento de fontes e continuidade sem executar."""
import json
import time
from unittest.mock import MagicMock, patch
import pytest
from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse, ProviderTimeoutError, ProviderResponseError
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator

PROFILE = '''# Perfil fictício de Luana
## Faculdade
Curso: Engenharia Biomédica
Período letivo atual: 2028.1
## Formação técnica
Curso técnico em Instrumentação
Período: 2020 a 2022
Situação: concluído
## Objetivos
Objetivos pessoais em [[Objetivos]].
'''


def test_course_question_uses_authorized_profile_without_writing(case):
    assistant,provider,adapter,profile=case
    before=profile.read_bytes()
    result=assistant.process_command('Qual faculdade eu estou fazendo?')
    assert result.status=='success' and 'Engenharia Biomédica' in result.message
    assert '01 - Pessoal/Perfil.md' in result.message
    assert profile.read_bytes()==before
    adapter.create_event.assert_not_called()


@pytest.fixture
def case(tmp_path):
    vault = tmp_path/'vault'
    personal = vault/'01 - Pessoal'
    personal.mkdir(parents=True)
    profile = personal/'Perfil.md'
    profile.write_text(PROFILE, encoding='utf-8')
    (personal/'Objetivos.md').write_text('# Objetivos fictícios\nConstruir um sensor de teste para laboratório.', encoding='utf-8')
    provider = MagicMock()
    provider.generate.return_value = AIResponse(type='chat', message='Entendido.')
    provider.describe_result.return_value = 'Você cursa Engenharia Biomédica e já concluiu o técnico em Instrumentação.'
    adapter = MagicMock()
    assistant = Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'),
                             calendar_adapter=adapter, ai_core=AICore(provider, []))
    assistant.second_brain.allowed_roots = [str(vault)]
    yield assistant, provider, adapter, profile
    assistant.close()


@pytest.mark.parametrize('command', [
    'Leia meu perfil e explique minha formação atual e o que já conclui.',
    'Com as informações que você tem, faça um resumo sobre mim.',
    'Quase informações que você tem, faça um resumo sobre mim.',
    'O que você sabe sobre mim?',
])
def test_personal_read_precedes_compound_interpretation_and_uses_real_source(case, command):
    assistant, provider, adapter, profile = case
    original = profile.read_bytes()
    result = assistant.process_command(command)
    assert result.status == 'success', result.message
    assert 'Engenharia Biomédica' in result.message and 'Instrumentação' in result.message
    assert '01 - Pessoal/Perfil.md' in result.message
    assert profile.read_bytes() == original
    evidence = provider.describe_result.call_args.args[1]
    assert evidence['kind'] == 'personal_context'
    assert 'Situação: concluído' in evidence['notes'][0]['formation_context']
    assert all(note['version'] for note in evidence['notes'])
    assert sum(len(note['content']) + len(note['formation_context']) for note in evidence['notes']) <= 12000
    provider.generate.assert_not_called()
    provider.interpret_workflow_commands.assert_not_called()
    adapter.create_event.assert_not_called()
    assert assistant.memory.turns[-1].origin == 'personal_context'


def test_summary_complements_profile_from_relevant_permitted_notes(case):
    assistant, provider, _, _ = case
    assistant.process_command('Faça um resumo sobre mim.')
    evidence = provider.describe_result.call_args.args[1]
    assert len(evidence['notes']) == 2
    assert any('sensor de teste' in note['content'] for note in evidence['notes'])


def test_denied_profile_does_not_become_claim_that_no_personal_data_exists(case):
    assistant, provider, _, _ = case
    assistant.second_brain.allowed_roots = [str(assistant.second_brain.vault_root) + '/90 - Sistema da IA']
    result = assistant.process_command('Leia meu perfil.')
    assert result.status == 'clarification' and 'escopo' in result.message
    assert 'não há dados pessoais' not in result.message.casefold()
    provider.describe_result.assert_not_called()


def test_missing_profile_is_reported_as_source_problem(case):
    assistant, provider, _, profile = case
    profile.unlink()
    result = assistant.process_command('Faça um resumo sobre mim.')
    assert 'Não consegui ler o Perfil' in result.message
    assert 'não existam informações' in result.message
    provider.describe_result.assert_not_called()


def test_ambiguous_profile_requires_source_selection(case):
    assistant, provider, _, profile = case
    profile.unlink()
    for name in ('A', 'B'):
        path = profile.parent/name/'Perfil.md'
        path.parent.mkdir()
        path.write_text('# Perfil fictício', encoding='utf-8')
    result = assistant.process_command('Leia meu perfil.')
    assert result.status == 'clarification' and 'mais de um Perfil' in result.message
    provider.describe_result.assert_not_called()


@pytest.mark.parametrize('change', ['source', 'access', 'expiry'])
def test_changed_source_access_or_expiry_discards_unpublished_answer(case, change):
    assistant, provider, _, profile = case
    clock = [100.0]
    assistant._language_clock = lambda: clock[0]
    def describe(*args):
        if change == 'source':
            profile.write_text('# Fonte alterada durante a resposta', encoding='utf-8')
        elif change == 'access':
            assistant.second_brain.allowed_roots = []
        else:
            clock[0] += 301
        return 'RESPOSTA_QUE_NAO_DEVE_SER_PUBLICADA'
    provider.describe_result.side_effect = describe
    result = assistant.process_command('Leia meu perfil.')
    assert result.status == 'cancelled'
    assert 'RESPOSTA_QUE_NAO_DEVE_SER_PUBLICADA' not in result.message
    assert assistant._personal_snapshot is None


def test_personal_reply_is_not_reused_from_assistant_history_after_revocation(case):
    assistant, provider, _, profile = case
    provider.describe_result.return_value = 'DADO_FICTICIO_RESERVADO. Quer detalhar sua formação?'
    assistant.process_command('Leia meu perfil.')
    assistant.second_brain.allowed_roots = []
    context = assistant._build_ai_context('qual a minha formação?')
    assert context['last_tool_evidence'] is None
    assert context['last_result_summary'] is None
    assert 'DADO_FICTICIO_RESERVADO' not in json.dumps(context, ensure_ascii=False)


def test_read_only_context_contract_handles_natural_unknown_phrase(case):
    assistant, provider, _, _ = case
    provider.generate.return_value = AIResponse(type='context_request', arguments={'purpose': 'personal_summary'}, message='Vou consultar o contexto permitido.')
    result = assistant.process_command('Use o contexto permitido para me apresentar a uma pessoa.')
    assert result.status == 'success' and 'Perfil.md' in result.message
    provider.generate.assert_called_once()
    provider.describe_result.assert_called_once()


@pytest.mark.parametrize('args', [
    {}, {'purpose': 'execute'}, {'purpose': []}, {'purpose': 'profile_read', 'path': '../segredo.md'},
    {'purpose': 'personal_summary', 'query': 123}, {'purpose': 'profile_read', 'query': 'x'*301},
])
def test_context_request_cannot_supply_actions_paths_permissions_or_invalid_fields(args):
    provider = MagicMock()
    provider.generate.return_value = AIResponse(type='context_request', arguments=args, message='leitura')
    assert AICore(provider, []).classify_detailed('pedido', {}).response is None


def test_no_answers_conversational_offer_and_cannot_execute_an_action(case):
    assistant, provider, adapter, _ = case
    provider.describe_result.return_value = 'Posso detalhar melhorias de contexto do Therion?'
    assistant.process_command('Tem alguma dica para você ficar melhor?')
    provider.generate.return_value = AIResponse(type='action', intent='criar evento calendário',
        arguments={'title': 'Evento inventado', 'date': 'amanhã', 'start_time': '15:00'}, message='feito')
    provider.describe_result.return_value = None
    result = assistant.process_command('Não.')
    assert 'proposta pendente' not in result.message
    assert result.status == 'success'
    context = provider.describe_result.call_args.args[2]
    assert context['conversation_frame']['question'] == 'Posso detalhar melhorias de contexto do Therion?'
    assert context['conversation_frame']['reply'] == 'nao'
    provider.generate.assert_not_called()
    adapter.create_event.assert_not_called()


def test_real_calendar_collection_keeps_negative_control(case):
    assistant, provider, adapter, _ = case
    assistant.process_command('marca uma reunião para mim')
    assert assistant._pending_event_draft is not None
    assert assistant.process_command('não').status == 'cancelled'
    assert assistant._pending_event_draft is None
    adapter.create_event.assert_not_called()


def test_clear_removes_personal_snapshot_and_dialogue_question(case):
    assistant, provider, _, _ = case
    provider.describe_result.return_value = 'Resumo fictício. Quer detalhar?'
    assistant.process_command('Faça um resumo sobre mim.')
    assistant.clear_session()
    assert assistant._personal_snapshot is None
    assert assistant._conversation_frame.question is None
    assert assistant._last_tool_evidence is None


def test_assistant_topic_does_not_inherit_old_pomodoro_budget(case):
    assistant, provider, _, _ = case
    assistant.memory.add_turn('user', 'tenho 2 horas para estudar circuitos lógicos')
    context = assistant._build_ai_context('Tem alguma dica que eu posso implementar para você ficar melhor?')
    assert context['conversation_frame']['topic'] == 'assistant'
    assert 'pomodoro_budget' not in context
    assert context['assistant_identity']['creator'] is None
    assert context['assistant_identity']['created_at'] is None


def test_generation_retries_malformed_json_once_with_remaining_total_deadline():
    provider = OllamaProvider(timeout=90)
    valid = '{"type":"context_request","intent":null,"arguments":{"purpose":"profile_read"},"message":"Vou consultar o perfil."}'
    with patch.object(provider, '_send_request', side_effect=['json inválido', valid]) as send, \
            patch('therion.core.ai_provider_ollama.time.monotonic', side_effect=[100, 106]):
        response = provider.generate('leia meu perfil', {'allow_format_repair': True, 'deadline_monotonic': 110}, [])
    assert response.type == 'context_request'
    assert [call.kwargs['timeout'] for call in send.call_args_list] == [10, 4]


def test_expired_total_deadline_never_sends_another_request():
    provider = OllamaProvider()
    with patch.object(provider, '_send_request') as send:
        with pytest.raises(ProviderTimeoutError):
            provider.generate('pedido', {'deadline_monotonic': time.monotonic()-1}, [])
    send.assert_not_called()


def test_read_subset_cannot_reuse_broader_personal_context(case):
    from therion.context.read_scope import ReadScope
    assistant, provider, _, profile = case
    assistant.process_command('Leia meu perfil.')
    narrow = ReadScope('ficticio', (str(profile.parent/'Objetivos.md'),))
    result = assistant._resolve_personal_context('profile_read', 'Leia meu perfil.', narrow)
    assert result.status == 'clarification'
    assert assistant._personal_snapshot is None
    assert assistant._last_tool_evidence is None


def test_complement_links_cannot_read_outside_allowed_roots(case, tmp_path):
    assistant, provider, _, profile = case
    secret = tmp_path/'segredo.md'
    secret.write_text('FORA_DO_ESCOPO_123', encoding='utf-8')
    profile.write_text(PROFILE + '\n## Objetivos\n[[' + str(secret) + ']]', encoding='utf-8')
    assistant.process_command('Faça um resumo sobre mim.')
    evidence = provider.describe_result.call_args.args[1]
    assert 'FORA_DO_ESCOPO_123' not in json.dumps(evidence)
    assert evidence['unavailable_sources']


def test_long_sources_keep_formation_qualifiers_and_signal_partial(case):
    assistant, provider, _, profile = case
    profile.write_text('# Introdução\n' + ('Texto secundário. '*1600) + '\n' + PROFILE, encoding='utf-8')
    result = assistant.process_command('Leia meu perfil e explique minha formação.')
    evidence = provider.describe_result.call_args.args[1]
    assert evidence['partial']
    assert 'conteúdo parcial' in result.message
    assert 'Situação: concluído' in evidence['notes'][0]['formation_context']
    assert sum(len(n['content'])+len(n['formation_context']) for n in evidence['notes']) <= 12000


def test_source_changed_during_followup_discards_generated_answer(case):
    assistant, provider, _, profile = case
    assistant.process_command('Leia meu perfil.')
    def generate(**kwargs):
        profile.write_text('# Outra versão', encoding='utf-8')
        return AIResponse(type='chat', message='RESPOSTA_OBSOLETA')
    provider.generate.side_effect = generate
    result = assistant.process_command('E quais dessas formações já terminei?')
    assert result.status == 'cancelled'
    assert 'RESPOSTA_OBSOLETA' not in result.message


def test_cancel_during_read_does_not_call_model(case):
    assistant, provider, _, _ = case
    original_read = assistant.read_context
    def read(*args, **kwargs):
        value = original_read(*args, **kwargs)
        assistant._workflow_cancel_event.set()
        return value
    with patch.object(assistant, 'read_context', side_effect=read):
        result = assistant.process_command('Leia meu perfil.')
    assert result.status == 'cancelled'
    provider.describe_result.assert_not_called()


def test_assistant_identity_uses_operational_metadata_without_profile(case):
    assistant, provider, _, _ = case
    assistant.process_command('Leia meu perfil.')
    provider.reset_mock()
    assistant.process_command('Quem te criou?')
    evidence = provider.describe_result.call_args.args[1]
    assert evidence['kind'] == 'assistant_context'
    assert evidence['identity']['creator'] is None
    assert 'notes' not in evidence
    assert 'Instrumentação' not in json.dumps(evidence, ensure_ascii=False)
    provider.generate.assert_not_called()


def test_frame_expires_and_recent_conversation_keeps_contiguous_turns():
    from therion.context.conversation_frame import ConversationFrame, conversation_turns
    from therion.memory.working_memory import Turn
    frame = ConversationFrame()
    frame.finish('Como melhorar você?', 'Podemos detalhar?', 100)
    assert frame.reply('sim', 399)
    assert not frame.reply('sim', 401)
    turns = [Turn('user' if i % 2 else 'therion', f'assunto {i} '+('x'*900), i) for i in range(20)]
    result = conversation_turns(turns, 'assunto')
    assert len(result) <= 10
    assert sum(len(t['text']) for t in result) <= 6000
    assert [t['text'].split(' x')[0] for t in result[-6:]] == [f'assunto {i}' for i in range(14, 20)]


def test_description_format_repair_shares_one_budget_with_classification():
    provider = OllamaProvider()
    context = {'allow_format_repair': True, 'format_repair_budget': {'remaining': 1}}
    valid = '{"type":"context_request","intent":null,"arguments":{"purpose":"profile_read"},"message":"leitura"}'
    with patch.object(provider, '_send_request', side_effect=['inválido', valid, 'inválido']) as send:
        assert provider.generate('pedido', context, []).type == 'context_request'
        with pytest.raises(ProviderResponseError):
            provider.describe_result('pedido', {'kind': 'personal_context'}, context)
    assert send.call_count == 3


def test_description_repairs_once_and_rejects_repeated_invalid_shape():
    provider = OllamaProvider()
    context = {'allow_format_repair': True, 'format_repair_budget': {'remaining': 1}}
    with patch.object(provider, '_send_request', side_effect=['inválido', '{"message":"resposta","action":"execute"}']) as send:
        with pytest.raises(ProviderResponseError):
            provider.describe_result('pedido', {'kind': 'assistant_context'}, context)
    assert send.call_count == 2


def test_personal_followup_uses_revalidated_evidence_for_comprehension(case):
    assistant, provider, _, _ = case
    assistant.process_command('Leia meu perfil.')
    provider.generate.return_value = AIResponse(type='chat', message='Classificação não é a interpretação final.')
    provider.describe_result.return_value = 'O tipo sanguíneo não consta nas fontes disponíveis.'
    result = assistant.process_command('Qual é meu tipo sanguíneo?')
    assert 'não consta' in result.message
    assert 'Classificação' not in result.message
    assert provider.describe_result.call_args.args[1]['kind'] == 'personal_context'


def test_refusing_personal_followup_does_not_restart_profile_summary(case):
    assistant, provider, adapter, _ = case
    provider.describe_result.return_value = 'Você cursa Engenharia Biomédica. Quer detalhar seus objetivos?'
    assistant.process_command('Faça um resumo sobre mim.')
    provider.describe_result.return_value = 'Tudo bem.'
    result = assistant.process_command('Não.')
    assert result.message == 'Tudo bem.'
    assert provider.describe_result.call_args.args[1]['dialogue_act'] == 'decline'
    assert 'notes' not in provider.describe_result.call_args.args[1]
    provider.generate.assert_not_called()
    adapter.create_event.assert_not_called()


@pytest.mark.parametrize('command', [
    'Leia meu perfil e crie um evento.',
    'Faça um resumo sobre mim e salvar em uma nota.',
    'Leia meu perfil e enviar por mensagem.',
])
def test_personal_shortcut_does_not_swallow_explicit_write_steps(command):
    from therion.context.conversation_frame import personal_request
    assert personal_request(command) is None
