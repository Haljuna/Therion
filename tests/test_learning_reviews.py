from datetime import datetime,timedelta,timezone
from dataclasses import replace
from unittest.mock import MagicMock
import pytest
from therion.core.orchestrator import Orchestrator
from therion.memory.runtime import KnowledgeRuntime
from therion.memory.knowledge import MemoryError,SourceReference,validate_candidate,RAS_ROOT


@pytest.fixture
def host(tmp_path):
    vault=tmp_path/'vault';note=vault/'10 - Projetos'/'Therion'/'fonte.md'
    note.parent.mkdir(parents=True)
    text='Limitação observada no sistema fictício: duas consultas ao calendário de teste falharam. Uma falha de consulta não comprova ausência de compromissos. O estado da agenda permanece desconhecido.'
    note.write_text(text,encoding='utf-8')
    config={'knowledge_access':dict(read_all=True,supervised_memory=True,authorization='fictício',
        expires_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),revision=1)}
    runtime=KnowledgeRuntime(vault,tmp_path/'state',lambda:config)
    core=Orchestrator(vault_root=str(vault),log_dir=str(tmp_path/'logs'),knowledge_runtime=runtime)
    source=SourceReference.file(note,text,core.second_brain.allowed_roots)
    provider=MagicMock(model='fictício')
    provider.extract_memory_candidates.return_value=[dict(title='Limitação de consulta',
        summary='Falha de consulta não permite concluir que a agenda esteja vazia.',kind='limitação',
        reason='Evitar disponibilidade sem evidência.',evidence=text,sensitivity='uncertain')]
    yield core,note,source,provider,vault
    core.close()


def offer(host):
    core,_,source,provider,_=host
    assert core.knowledge.offer_verified(source,provider,source.roots,reusable=True)
    assert core.knowledge.wait_idle()
    return core.knowledge.learning_reviews(core.second_brain.allowed_roots)


def test_uncertainty_is_reviewable_and_never_automatically_safe_or_saved(host):
    core,_,_,_,vault=host
    row,=offer(host)
    assert not core.knowledge.snapshot() and row.candidate.sensitivity=='uncertain'
    with pytest.raises(MemoryError):validate_candidate(row.candidate)
    assert 'revisão de sensibilidade' in core.memory_notifications()
    assert not core.memory_notifications()
    assert row.id in core.process_command('revisões de aprendizados').message
    shown=core.process_command('mostre a revisão '+row.id)
    assert 'não é candidato salvável' in shown.message and 'Evidência literal:' in shown.message
    core.process_command('sim')
    assert not core.knowledge.snapshot()
    assert core.process_command('salve').status=='clarification'
    assert not (vault/RAS_ROOT).exists()


def test_human_classification_and_separate_save_consent(host):
    core,_,_,_,vault=host;row,=offer(host)
    result=core.process_command(f'classifique a revisão {row.id} como não sensível')
    assert result.status=='success' and 'Ainda não salvei' in result.message
    candidate,=core.knowledge.snapshot()
    assert candidate.sensitivity=='non_sensitive' and 'explicitamente' in candidate.reason
    assert not core.knowledge.learning_reviews(core.second_brain.allowed_roots)
    assert not (vault/RAS_ROOT).exists()
    proposal=core.process_command('salve')
    assert proposal.status=='awaiting_confirmation' and not (vault/RAS_ROOT).exists()
    assert core.confirm_session_proposal(proposal.plan,False,core.session_id,proposal.confirmation_id).status=='cancelled'
    assert not (vault/RAS_ROOT).exists()
    proposal=core.process_command('salve')
    assert core.confirm_session_proposal(proposal.plan,True,core.session_id,proposal.confirmation_id).status=='success'
    assert len(list((vault/RAS_ROOT).glob('RAS-*.md')))==1
    assert core.process_command(f'classifique a revisão {row.id} como não sensível').status=='clarification'


@pytest.mark.parametrize('change',['source','policy','scope','expiry','session','pause','discard'])
def test_stale_or_discarded_review_cannot_be_promoted(host,change):
    core,note,_,_,_=host;row,=offer(host)
    if change=='source':note.write_text('fonte alterada',encoding='utf-8')
    if change=='policy':core.knowledge.policy=replace(core.knowledge.policy,revision=2)
    if change=='scope':core.second_brain.allowed_roots=[]
    if change=='expiry':core.knowledge.reviews.clock=lambda:row.deadline
    if change=='session':core.clear_session()
    if change=='pause':core.knowledge.pause()
    if change=='discard':assert core.process_command('descarte a revisão '+row.id).status=='success'
    assert core.process_command(f'classifique a revisão {row.id} como não sensível').status=='clarification'
    assert not core.knowledge.snapshot()


def test_sensitive_literal_is_not_put_in_review_queue(host):
    core,note,_,provider,_=host
    secret='Procedimento fictício: minha senha é EXEMPLO-SEM-VALOR. Verifique a origem antes de publicar. Não guardar esse segredo.'
    note.write_text(secret,encoding='utf-8')
    source=SourceReference.file(note,secret,core.second_brain.allowed_roots)
    assert not core.knowledge.offer_verified(source,provider,source.roots,reusable=True)
    assert not core.knowledge.learning_reviews(core.second_brain.allowed_roots)
    provider.extract_memory_candidates.assert_not_called()


def test_classification_does_not_consume_another_confirmation(host):
    core,*_=host;row,=offer(host)
    core._confirmation_id='other-proposal'
    result=core.process_command(f'classifique a revisão {row.id} como não sensível')
    assert result.status=='clarification' and core.confirmation_id=='other-proposal'
    assert not core.knowledge.snapshot()
