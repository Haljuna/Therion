"""Runtime completo em cofres fictícios, sem configuração ou notas pessoais."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from therion.core.ai_core import AICore
from therion.core.orchestrator import Orchestrator
from therion.memory.knowledge import RAS_ROOT
from therion.memory.runtime import KnowledgeRuntime


NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


@pytest.fixture
def host(tmp_path):
    vault = tmp_path/'vault'; state = tmp_path/'state'
    settings = {'knowledge_access':dict(read_all=True, supervised_memory=True,
        authorization='ficticio-v3', expires_at=(NOW+timedelta(days=30)).isoformat(), revision=1)}
    time = [NOW]
    def make():
        runtime = KnowledgeRuntime(vault, state, lambda: settings, clock=lambda: time[0])
        return Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'), knowledge_runtime=runtime)
    return make, settings, time, vault, state


def save(orch):
    orch.process_command('lembre que prefiro explicações com exemplos fictícios')
    proposal = orch.process_command('salve')
    assert proposal.status == 'awaiting_confirmation'
    result = orch.confirm_session_proposal(proposal.plan, True, orch.session_id, proposal.confirmation_id)
    assert result.status == 'success', result.message
    return proposal


def test_runtime_read_is_selective_and_all_vault_is_available(host):
    make, _, _, vault, _ = host
    note = vault/'01 - Pessoal'/'Exemplo fictício.md'; note.parent.mkdir(parents=True)
    note.write_text('CONTEUDO FICTICIO AUTORIZADO', encoding='utf-8')
    other = vault/'03 - Estudos'/'Não solicitada.md'; other.parent.mkdir(parents=True)
    other.write_text('NAO DEVE SER LIDA', encoding='utf-8')
    orch = make()
    assert orch.second_brain.allowed_roots == [str(vault.resolve())]
    result = orch.process_command('leia no segundo cérebro 01 - Pessoal/Exemplo fictício.md')
    assert result.status == 'success' and 'CONTEUDO FICTICIO AUTORIZADO' in result.message
    assert 'NAO DEVE SER LIDA' not in str(orch.memory.turns)
    orch.close()


def test_saved_memory_recovers_with_runtime_after_restart(host):
    make, _, _, vault, state = host
    orch = make(); save(orch); orch.close()
    assert len(list((vault/RAS_ROOT).glob('RAS-*.md'))) == 1
    assert (state/'evidence'/'evidence.sqlite3').exists()
    restarted = make()
    assert 'prefiro explicações' in str(restarted._build_ai_context('explicações exemplos')['knowledge_context'])
    assert 'RAS-' in restarted.process_command('o que você guardou?').message
    restarted.close()


@pytest.mark.parametrize('change', [dict(read_all=False), dict(supervised_memory=False),
    dict(authorization='revogada'), dict(revision=2), dict(expires_at=NOW.isoformat())])
def test_policy_change_invalidates_session_and_pending_confirmation(host, change):
    make, settings, _, vault, _ = host
    orch = make()
    orch.process_command('lembre que prefiro explicações curtas')
    proposal = orch.process_command('salve'); session = orch.session_id
    settings['knowledge_access'].update(change)
    result = orch.confirm_session_proposal(proposal.plan, True, session, proposal.confirmation_id)
    assert result.status == 'cancelled' and orch.session_id != session
    assert not list((vault/RAS_ROOT).glob('RAS-*.md'))
    assert not orch.knowledge.snapshot() and not orch.memory.turns
    orch.close()


def test_expiry_removes_external_read_scope_on_next_command(host):
    make, _, time, vault, _ = host
    orch = make(); session = orch.session_id
    time[0] = NOW + timedelta(days=31)
    orch.process_command('Status da memória')
    assert orch.session_id != session
    assert str(vault.resolve()) not in orch.second_brain.allowed_roots
    assert not orch.knowledge.policy.allows_write(time[0])
    orch.close()


def test_revoked_read_does_not_expose_generated_summary(host):
    make, settings, _, vault, _ = host
    path = vault/'01 - Pessoal'/'Ficticio.md'; path.parent.mkdir(parents=True)
    path.write_text('Conteúdo fictício da consulta', encoding='utf-8')
    orch = make(); provider = MagicMock()
    def revoke(*args):
        settings['knowledge_access']['read_all'] = False
        return 'CONTEUDO QUE DEVE SER BLOQUEADO'
    provider.describe_result.side_effect = revoke
    orch.ai_core = AICore(provider, [])
    result = orch.process_command('leia no segundo cérebro 01 - Pessoal/Ficticio.md')
    assert result.status == 'cancelled' and 'CONTEUDO QUE DEVE SER BLOQUEADO' not in result.message
    assert orch._last_tool_evidence is None
    orch.close()


def test_revocation_during_store_prevents_publication(host):
    make, settings, _, vault, _ = host
    orch = make()
    orch.process_command('lembre que prefiro exemplos fictícios')
    proposal = orch.process_command('salve')
    original = orch._knowledge_repository._records
    def revoke():
        settings['knowledge_access']['supervised_memory'] = False
        return original()
    with patch.object(orch._knowledge_repository, '_records', side_effect=revoke):
        result = orch.confirm_and_execute(proposal.plan, True)
    assert result.status == 'execution_failed' and not list((vault/RAS_ROOT).glob('RAS-*.md'))
    orch.close()


def test_pause_is_not_undone_by_next_runtime_refresh(host):
    make, _, _, _, _ = host
    orch = make()
    orch.process_command('pause a captura')
    assert orch.process_command('lembre que prefiro exemplos fictícios').status == 'clarification'
    assert orch.knowledge.policy.mode == 'off'
    orch.close()


@pytest.mark.parametrize('command,full', [('revogue a gravação de memória',False), ('revogue a leitura ampliada',True)])
def test_revocation_is_persistent_and_preserves_other_settings(host, command, full):
    make, settings, _, vault, _ = host
    settings['ai'] = {'model':'modelo-ficticio-inalterado'}
    orch = make()
    def write(new):
        settings.clear(); settings.update(new)
    orch._knowledge_runtime.config_writer = write
    result = orch.process_command(command)
    assert result.status == 'success' and 'Revoguei' in result.message
    assert settings['ai']['model'] == 'modelo-ficticio-inalterado'
    assert settings['knowledge_access']['supervised_memory'] is False
    assert settings['knowledge_access']['read_all'] is (not full)
    assert orch._knowledge_repository is None
    orch.close()
    restarted = make()
    assert restarted._knowledge_repository is None
    assert (str(vault.resolve()) in restarted.second_brain.allowed_roots) is (not full)
    restarted.close()


def test_failed_revocation_does_not_claim_persistence(host):
    make, _, _, _, _ = host
    orch = make()
    orch._knowledge_runtime.config_writer = MagicMock(side_effect=OSError('fictício'))
    result = orch.process_command('revogue a gravação de memória')
    assert result.status == 'clarification' and 'Não confirmei' in result.message
    assert 'Revoguei' not in result.message
    orch.close()
