"""Correção/desconsideração duradouras, sem sobrescrever notas originais."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from therion.core.orchestrator import Orchestrator
from therion.memory.knowledge import RAS_ROOT
from therion.memory.repository import deserialize
from therion.memory.runtime import KnowledgeRuntime


NOW = datetime(2026,10,13,12,tzinfo=timezone.utc)


@pytest.fixture
def host(tmp_path):
    config = {'knowledge_access':dict(read_all=True, supervised_memory=True,
        authorization='ficticio-lifecycle', expires_at=(NOW+timedelta(days=30)).isoformat(), revision=1)}
    vault = tmp_path/'vault'; state = tmp_path/'state'
    def make():
        runtime = KnowledgeRuntime(vault, state, lambda:config, clock=lambda:NOW)
        return Orchestrator(vault_root=str(vault), log_dir=str(tmp_path/'logs'), knowledge_runtime=runtime)
    return make, config, vault/RAS_ROOT


def confirm(orch, result, answer=True):
    return orch.confirm_session_proposal(result.plan, answer, orch.session_id, result.confirmation_id)


def save(orch, root, text='prefiro exemplos curtos'):
    orch.process_command('lembre que '+text)
    assert confirm(orch,orch.process_command('salve')).status=='success'
    paths = list(root.glob('RAS-*.md'))
    path = max(paths, key=lambda p:p.name)
    return deserialize(path.read_text(encoding='utf-8'))[0], path


def test_correction_survives_restart_and_preserves_original_bytes(host):
    make, _, root = host
    orch=make(); identifier,path=save(orch,root); original=path.read_bytes()
    proposal=orch.process_command(f'corrija a memória {identifier}: prefiro exemplos detalhados')
    assert proposal.status=='awaiting_confirmation'
    assert 'Conteúdo anterior: prefiro exemplos curtos' in proposal.message
    assert 'prefiro exemplos detalhados' in proposal.message
    assert len(list(root.glob('RAS-*.md')))==1
    result=confirm(orch,proposal)
    assert result.status=='success' and 'Correção registrada' in result.message
    assert path.read_bytes()==original and len(list(root.glob('RAS-*.md')))==2
    context=orch._build_ai_context('exemplos')
    assert 'detalhados' in str(context['knowledge_context']) and 'curtos' not in str(context['knowledge_context'])
    orch.close()
    other=make(); context=other._build_ai_context('exemplos')
    assert 'detalhados' in str(context['knowledge_context']) and 'curtos' not in str(context['knowledge_context'])
    other.close()


def test_retirement_requires_confirmation_and_survives_restart_without_deleting(host):
    make, _, root=host
    orch=make(); identifier,path=save(orch,root); original=path.read_bytes()
    proposal=orch.process_command(f'desconsidere a memória {identifier}')
    assert proposal.status=='awaiting_confirmation' and 'nenhuma nota será apagada' in proposal.message
    assert 'exemplos curtos' in str(orch._build_ai_context('exemplos')['knowledge_context'])
    assert confirm(orch,proposal).status=='success'
    assert path.read_bytes()==original and len(list(root.glob('RAS-*.md')))==1
    assert 'knowledge_context' not in orch._build_ai_context('exemplos')
    orch.close(); other=make()
    assert 'knowledge_context' not in other._build_ai_context('exemplos')
    other.close()


@pytest.mark.parametrize('operation', ['corrija a memória {id}: prefiro exemplos detalhados', 'desconsidere a memória {id}'])
def test_negative_confirmation_leaves_persistent_state_unchanged(host,operation):
    make, _, root=host
    orch=make(); identifier,path=save(orch,root); original=path.read_bytes()
    proposal=orch.process_command(operation.format(id=identifier))
    assert confirm(orch,proposal,False).status=='cancelled'
    assert path.read_bytes()==original and len(list(root.glob('RAS-*.md')))==1
    orch.close(); other=make()
    assert 'curtos' in str(other._build_ai_context('exemplos')['knowledge_context'])
    other.close()


@pytest.mark.parametrize('change',['file','policy','session','expiry','replay'])
def test_changed_target_or_confirmation_never_silently_corrects(host,change):
    make,config,root=host
    orch=make(); identifier,path=save(orch,root)
    proposal=orch.process_command(f'corrija a memória {identifier}: prefiro exemplos detalhados')
    session,token=orch.session_id,proposal.confirmation_id
    if change=='file': path.write_text(path.read_text(encoding='utf-8')+'\nMudança externa',encoding='utf-8')
    if change=='policy': config['knowledge_access']['revision']=2
    if change=='session': orch.clear_session()
    if change=='expiry': orch._supervised_memory.monotonic=lambda:float('inf')
    if change=='replay':
        assert confirm(orch,proposal).status=='success'
    result=orch.confirm_session_proposal(proposal.plan,True,session,token)
    assert result.status in {'cancelled','execution_failed'}
    assert len(list(root.glob('RAS-*.md')))==(2 if change=='replay' else 1)
    orch.close()


def test_missing_or_inactive_target_and_equal_content_are_clarified(host):
    make,_,root=host
    orch=make(); identifier,_=save(orch,root)
    assert orch.process_command('corrija a memória RAS-20261013-999: outra declaração').status=='clarification'
    assert orch.process_command(f'corrija a memória {identifier}: prefiro exemplos curtos').status=='clarification'
    assert orch.process_command('corrija a memória').status=='clarification'
    assert confirm(orch,orch.process_command(f'desconsidere a memória {identifier}')).status=='success'
    assert orch.process_command(f'corrija a memória {identifier}: prefiro exemplos detalhados').status=='clarification'
    orch.close()


def test_failed_correction_receipt_preserves_old_memory_without_retry(host):
    make,_,root=host
    orch=make(); identifier,path=save(orch,root)
    proposal=orch.process_command(f'corrija a memória {identifier}: prefiro exemplos detalhados')
    with patch.object(orch._supervised_memory.evidence,'_transition',side_effect=OSError('falha fictícia')):
        assert confirm(orch,proposal).status=='execution_failed'
    assert len(list(root.glob('RAS-*.md')))==2
    orch.close(); other=make()
    context=other._build_ai_context('exemplos')
    assert 'curtos' in str(context['knowledge_context']) and 'detalhados' not in str(context['knowledge_context'])
    other.close()


def test_second_correction_retires_only_the_current_version(host):
    make,_,root=host
    orch=make(); first,_=save(orch,root)
    assert confirm(orch,orch.process_command(f'corrija a memória {first}: prefiro exemplos detalhados')).status=='success'
    second=deserialize(max(root.glob('RAS-*.md'),key=lambda p:p.name).read_text(encoding='utf-8'))[0]
    assert confirm(orch,orch.process_command(f'corrija a memória {second}: prefiro exemplos com diagramas')).status=='success'
    orch.close(); other=make()
    assert 'diagramas' in str(other._build_ai_context('exemplos')['knowledge_context'])
    assert 'detalhados' not in str(other._build_ai_context('exemplos')['knowledge_context'])
    assert len(list(root.glob('RAS-*.md')))==3
    other.close()
