"""Fontes de outros turnos exigem proveniência e revalidação atuais."""
import asyncio
import pytest

from therion.agent import AgentDecision, AgentRuntime, ToolCall
from therion.agent.registry import ToolRegistry
from therion.agent.store import SessionStore
from therion.core.orchestrator import Orchestrator
from tests.test_agent_runtime import ScriptedProvider


def host_with_read_note(tmp_path, followup):
    note = tmp_path / 'Aurora.md'
    note.write_text('# Aurora\nO código é PONTE-42. Revisar o relatório.\n', encoding='utf-8')
    provider = ScriptedProvider(
        AgentDecision('tools', calls=(ToolCall('search_notes', {'query': 'Aurora'}),)),
        AgentDecision('tools', calls=(ToolCall('read_source', {'source_id': 'note:1'}),)),
        AgentDecision('final', 'PONTE-42. Revisar o relatório. Fonte: note:1.'),
        followup)
    host = Orchestrator(simulate=True, vault_root=str(tmp_path), log_dir=str(tmp_path / 'logs'),
        agent_config={'enabled': True}, agent_state_root=tmp_path / 'state', agent_provider=provider)
    host.second_brain.allowed_roots = [str(tmp_path)]
    first = host.process_command('Busque nas notas Aurora e leia a fonte original.')
    assert first.status == 'success', first.message
    assert any(row['tool'] == 'read_source' and row['verified'] for row in host._get_agent_store().operations())
    return host, note


def test_followup_can_cite_original_read_without_repeating_tools(tmp_path):
    host, _ = host_with_read_note(tmp_path, AgentDecision('final',
        'O código de conferência é PONTE-42. Fonte: note:1.'))
    try:
        count = len(host._get_agent_store().operations())
        result = host.process_command('Qual era o código de conferência do projeto Aurora?')
        assert result.status == 'success' and 'PONTE-42' in result.message
        assert 'Fontes consultadas:' in result.message and 'Aurora.md' in result.message
        assert len(host._get_agent_store().operations()) == count
    finally:
        host.close()


def test_absence_cannot_be_claimed_from_history_by_omitting_word_source(tmp_path):
    decision=AgentDecision('final','Não há senha registrada. note:1.')
    host,_=host_with_read_note(tmp_path,decision)
    host._agent_provider.decisions=iter([decision,decision])
    try:
        previous={row['call_id'] for row in host._get_agent_store().operations()}
        result=host.process_command('Qual é a senha do projeto Aurora?')
        assert result.status=='partial' and 'leitura integral verificada' in result.message
        assert not any(row['tool']=='read_source' and row['call_id'] not in previous for row in host._get_agent_store().operations())
    finally:host.close()


def test_new_field_requires_read_even_without_an_absence_phrase(tmp_path):
    decision=AgentDecision('final','O prazo é amanhã. Fonte: note:1.')
    host,_=host_with_read_note(tmp_path,decision)
    host._agent_provider.decisions=iter([decision,decision])
    try:
        result=host.process_command('Qual é o prazo do projeto Aurora?')
        assert result.status=='partial' and 'leitura integral verificada' in result.message
    finally:host.close()


@pytest.mark.parametrize('invalidate', ['changed', 'deleted', 'revoked', 'new_session'])
def test_stale_or_revoked_history_never_confirms_a_citation(tmp_path, invalidate):
    host, note = host_with_read_note(tmp_path, AgentDecision('final', 'A senha não consta. Fonte: note:1.'))
    try:
        if invalidate == 'changed':
            note.write_text('# Aurora\nConteúdo substituído.\n', encoding='utf-8')
        elif invalidate == 'deleted':
            note.unlink()
        elif invalidate == 'revoked':
            host.second_brain.allowed_roots = [str(tmp_path / 'other')]
        else:
            host.clear_session()
        result = host.process_command('Qual é a senha de acesso do projeto Aurora?')
        assert result.status == 'partial' and 'fonte que não foi confirmada' in result.message
    finally:
        host.close()


def test_real_history_source_does_not_allow_an_invented_id(tmp_path):
    host, _ = host_with_read_note(tmp_path, AgentDecision('final', 'Fonte: note:999.'))
    try:
        result = host.process_command('Qual é a senha do projeto Aurora?')
        assert result.status == 'partial' and 'fonte que não foi confirmada' in result.message
    finally:
        host.close()


def test_greeting_does_not_publish_unrelated_historical_sources(tmp_path):
    host, _ = host_with_read_note(tmp_path, AgentDecision('final', 'Olá! Como posso ajudar?'))
    try:
        result = host.process_command('Olá')
        assert result.status == 'success'
        assert result.message == 'Olá! Como posso ajudar?'
    finally:
        host.close()


def test_history_is_revalidated_after_model_returns(tmp_path):
    store = SessionStore(tmp_path / 'state.sqlite3')
    valid = [True]
    store.source_validator = lambda rows: valid[0]
    class Provider:
        async def decide(self, *args):
            valid[0] = False
            return AgentDecision('final', 'Fonte: note:1.')
    result = asyncio.run(AgentRuntime(Provider(), ToolRegistry(), store=store).run(
        'Consulte o assunto anterior.', session_id='s',
        history_sources=({'id': 'note:1', 'source': 'fixture', 'version': 'v1'},)))
    assert result.status == 'partial' and 'perdeu autorização' in result.message


def test_citation_without_history_validator_stays_blocked():
    runtime = AgentRuntime(ScriptedProvider(AgentDecision('final', 'Fonte: note:1.')), ToolRegistry())
    result = asyncio.run(runtime.run('Consulte o assunto anterior.', session_id='s',
        history_sources=({'id': 'note:1', 'source': 'fixture'},)))
    assert result.status == 'partial'


def test_history_receipt_never_proves_a_new_effect(tmp_path):
    store = SessionStore(tmp_path / 'state.sqlite3')
    store.source_validator = lambda rows: True
    runtime = AgentRuntime(ScriptedProvider(AgentDecision('final',
        'Enviei a mensagem. Fonte: receipt:old.')), ToolRegistry(), store=store)
    result = asyncio.run(runtime.run('Prepare uma resposta.', session_id='s',
        history_sources=({'id': 'receipt:old', 'source': 'registro operacional local',
                          'operation': 'gmail.send_draft'},)))
    assert result.status == 'partial' and 'Não há recibo verificado' in result.message
