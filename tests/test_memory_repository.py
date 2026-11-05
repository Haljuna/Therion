from dataclasses import replace
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest

from therion.memory.knowledge import (MemoryPolicy, MemoryError, SourceReference,
    user_candidate, validate_candidate, safe_path, RAS_ROOT)
from therion.memory.repository import MarkdownMemoryRepository, deserialize, serialize

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def storage(tmp_path):
    root = tmp_path / RAS_ROOT
    policy = MemoryPolicy(mode='authorized', read_roots=(str(tmp_path.resolve()),),
        write_root=str(root.resolve()), authorization='teste-fictício', expires_at=NOW+timedelta(days=1))
    return MarkdownMemoryRepository(root), policy


def consent(source):
    return source.kind == 'user'


def test_preview_is_not_permission_to_write(storage):
    repo, policy = storage
    with pytest.raises(MemoryError):
        repo.store(user_candidate('prefiro respostas curtas', 's', NOW), replace(policy, mode='preview'), NOW, consent)
    assert not Path(repo.root).exists()


def test_restart_recovers_ras_with_source_and_review_state(storage):
    repo, policy = storage
    candidate = user_candidate('prefiro respostas curtas', 's', NOW)
    result = repo.store(candidate, policy, NOW, consent)
    text = Path(result.path).read_text(encoding='utf-8')
    assert result.identifier == 'RAS-20261009-001'
    assert 'Estado: Rascunho da IA' in text
    assert all(section in text for section in ('## Contexto', '## Aprendizado', '## Evidência', '## Possível uso futuro', '## Destino sugerido', '## Observações'))
    assert deserialize(text)[1].summary == candidate.summary
    other = MarkdownMemoryRepository(repo.root)
    records = other.retrieve('respostas curtas', policy, NOW, consent)
    assert len(records) == 1 and records[0]['state'] == 'Rascunho da IA'
    assert other.store(candidate, policy, NOW, consent).state == 'existing'
    assert len(list(Path(repo.root).glob('*.md'))) == 1


@pytest.mark.parametrize('change', [dict(mode='off'), dict(authorization=''),
    dict(expires_at=NOW), dict(read_roots=()), dict(per_day=11),dict(per_session=4)])
def test_invalid_or_revoked_policy_blocks_write(storage, change):
    repo, policy = storage
    with pytest.raises(MemoryError):
        repo.store(user_candidate('prefiro respostas curtas', 's', NOW), replace(policy, **change), NOW, consent)
    assert not Path(repo.root).exists()


@pytest.mark.parametrize('text', ['minha senha é abc', 'token: segredo123',
    'GOCSPX-valor-ficticio', 'CPF 123.456.789-00', 'meu diagnóstico é algo'])
def test_sensitive_content_is_rejected(text):
    with pytest.raises(MemoryError):
        user_candidate(text,'s',NOW)


def test_files_require_original_and_current_scope_and_unchanged_version(storage, tmp_path):
    repo, policy = storage
    path = tmp_path/'source.md'
    text = 'Procedimento: use um diretório temporário e confira o resultado antes de publicar a nota.'
    path.write_text(text,encoding='utf-8')
    source = SourceReference.file(path,text,(str(tmp_path),))
    candidate = replace(user_candidate(text,'s',NOW),source=source,kind='procedimento',summary='Confira o resultado no diretório temporário antes de publicar.')
    result = repo.store(candidate,policy,NOW)
    assert repo.retrieve('diretório temporário',policy,NOW)
    assert not repo.retrieve('diretório temporário',replace(policy,read_roots=(repo.root,)),NOW)
    path.write_text('Fonte corrigida',encoding='utf-8')
    assert not repo.retrieve('diretório temporário',policy,NOW)
    with pytest.raises(MemoryError):
        repo.store(replace(candidate,id='outra'),policy,NOW)
    assert Path(result.path).exists()


def test_expired_record_is_not_recovered(storage):
    repo, policy = storage
    repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert not repo.retrieve('respostas',policy,NOW+timedelta(days=31),consent)


def test_session_and_daily_limits_survive_restart(storage):
    repo, policy = storage
    for i in range(3):
        repo.store(user_candidate(f'procedimento número {i}','s',NOW),policy,NOW,consent)
    with pytest.raises(MemoryError, match='Limite'):
        MarkdownMemoryRepository(repo.root).store(user_candidate('outro aprendizado','s',NOW),policy,NOW,consent)
    for i in range(7):
        MarkdownMemoryRepository(repo.root).store(user_candidate(f'outro procedimento {i}',f's{i}',NOW),policy,NOW,consent)
    with pytest.raises(MemoryError, match='Limite'):
        MarkdownMemoryRepository(repo.root).store(user_candidate('excedente','nova',NOW),policy,NOW,consent)


def test_concurrent_requests_create_at_most_one_record(storage):
    repo, policy = storage
    candidate = user_candidate('prefiro respostas curtas','s',NOW)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: repo.store(candidate,policy,NOW,consent),range(4)))
    assert len({r.identifier for r in results}) == 1
    assert len(list(Path(repo.root).glob('*.md'))) == 1


def test_other_agents_id_is_preserved_and_sequence_skips_it(storage):
    repo,policy = storage
    Path(repo.root).mkdir(parents=True)
    foreign = Path(repo.root)/'RAS-20261009-007 - Outro agente.md'
    foreign.write_text('# Rascunho de outro agente',encoding='utf-8')
    result = repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert result.identifier == 'RAS-20261009-008'
    assert foreign.read_text(encoding='utf-8') == '# Rascunho de outro agente'


def test_interrupted_publication_preserves_existing_records(storage):
    repo,policy = storage
    old = repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    before = Path(old.path).read_bytes()
    with patch('therion.memory.repository.os.link',side_effect=OSError('simulado')):
        with pytest.raises(MemoryError,match='Não consegui publicar'):
            repo.store(user_candidate('prefiro exemplos concretos','s',NOW),policy,NOW,consent)
    assert Path(old.path).read_bytes() == before
    assert len(list(Path(repo.root).glob('*.md'))) == 1
    assert not list(Path(repo.root).glob('*.tmp'))


def test_foreign_lock_does_not_get_removed_or_retried(storage):
    repo,policy = storage
    Path(repo.root).mkdir(parents=True)
    lock=Path(repo.root)/'.therion-memory.lock'
    lock.write_text('outra operação',encoding='utf-8')
    with pytest.raises(MemoryError, match='Não repeti'):
        repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert lock.read_text(encoding='utf-8') == 'outra operação'


def _owner_lock(repo, created):
    import json, os
    Path(repo.root).mkdir(parents=True, exist_ok=True)
    lock=Path(repo.root)/'.therion-memory.lock'
    lock.write_text(json.dumps({'pid':os.getpid(),'created':created}),encoding='utf-8')
    return lock


@pytest.mark.skipif(__import__('os').name!='nt', reason='checagem de processo do Windows')
def test_lock_of_live_owner_still_blocks(storage):
    import os
    from therion.memory.repository import _running_since
    repo,policy=storage
    lock=_owner_lock(repo,_running_since(os.getpid()))
    with pytest.raises(MemoryError, match='Não repeti'):
        repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert lock.exists()


@pytest.mark.skipif(__import__('os').name!='nt', reason='checagem de processo do Windows')
def test_lock_of_dead_owner_is_cleared_once(storage):
    # Mesmo PID com outra hora de criação = PID reaproveitado, o dono morreu.
    repo,policy=storage
    lock=_owner_lock(repo,1)
    (Path(repo.root)/'.therion-interrompida.tmp').write_text('sobra',encoding='utf-8')
    result=repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert result.state=='stored' and result.recovered
    assert not lock.exists() and not list(Path(repo.root).glob('*.tmp'))


@pytest.mark.skipif(__import__('os').name!='nt', reason='checagem de processo do Windows')
def test_crash_right_after_publish_does_not_duplicate(storage):
    import os
    repo,policy=storage
    candidate=user_candidate('prefiro respostas curtas','s',NOW)
    first=repo.store(candidate,policy,NOW,consent)
    # Queda entre os.link e unlink: a nota tem um segundo nome .tmp e a trava ficou.
    os.link(first.path,Path(repo.root)/'.therion-sobra.tmp')
    _owner_lock(repo,1)
    again=repo.store(candidate,policy,NOW,consent)
    assert again.state=='existing' and again.identifier==first.identifier and again.recovered
    assert os.stat(first.path).st_nlink==1 and len(list(Path(repo.root).glob('RAS-*.md')))==1


def test_tampered_record_cannot_hide_counts_or_be_used(storage):
    repo,policy=storage
    result=repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    path=Path(result.path)
    path.write_text(path.read_text(encoding='utf-8').replace('## Aprendizado','## Alterado'),encoding='utf-8')
    with pytest.raises(MemoryError):
        repo.retrieve('respostas',policy,NOW,consent)
    with pytest.raises(MemoryError):
        repo.store(user_candidate('novo conteúdo','s',NOW),policy,NOW,consent)


def test_no_obsidian_links_are_generated(storage):
    repo,policy=storage
    candidate=user_candidate('consultar [[Perfil]] e [site](https://example.invalid)','s',NOW)
    result=repo.store(candidate,policy,NOW,consent)
    visible=Path(result.path).read_text(encoding='utf-8')
    assert '[[' not in visible and '](' not in visible


def test_limits_and_invalid_evidence_are_rejected():
    c=user_candidate('prefiro respostas curtas','s',NOW)
    for invalid in (replace(c,summary='x'*1501),replace(c,evidence='invenção'),
                    replace(c,sensitivity='uncertain'),replace(c,kind='fato'),replace(c,reason='')):
        with pytest.raises(MemoryError): validate_candidate(invalid,explicit=True)


def test_escape_path_is_refused(tmp_path):
    with pytest.raises(MemoryError): safe_path(tmp_path/'outside.md',(str(tmp_path/'allowed'),))


def test_context_budget_is_respected(storage):
    repo,policy=storage
    for i in range(5):
        repo.store(user_candidate(f'procedimento comum exemplo {i}',f's{i}',NOW),policy,NOW,consent)
    result=repo.retrieve('procedimento comum',policy,NOW,consent)
    assert len(result)==3 and sum(len(r['content']) for r in result)<=4000


def test_revocation_immediately_before_publication_blocks_write(storage,monkeypatch):
    repo,policy=storage
    current=[policy]
    repo.policy_provider=lambda:current[0]
    import therion.memory.repository as module
    original=module.os.fsync
    def revoke(fd):
        original(fd)
        current[0]=replace(policy,mode='off',revision=1)
    monkeypatch.setattr(module.os,'fsync',revoke)
    with pytest.raises(MemoryError,match='revogada'):
        repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    assert not list(Path(repo.root).glob('*.md'))


@pytest.mark.parametrize('link_type',['symlink','junction'])
def test_linked_root_is_rejected(storage,monkeypatch,link_type):
    repo,policy=storage
    original=Path.is_symlink if link_type=='symlink' else Path.is_junction
    def linked(path):
        return str(path)==repo.root or original(path)
    monkeypatch.setattr(Path,'is_symlink' if link_type=='symlink' else 'is_junction',linked)
    with pytest.raises(MemoryError,match='Links'):
        repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)


@pytest.mark.parametrize('failure', [OSError, MemoryError])
def test_uncertain_write_is_detected_without_repetition(storage,monkeypatch,failure):
    repo,policy=storage
    import therion.memory.repository as module
    original=module.deserialize
    calls=[]
    def fail_after_publication(text):
        calls.append(text)
        raise failure('falha de verificação simulada')
    monkeypatch.setattr(module,'deserialize',fail_after_publication)
    candidate=user_candidate('prefiro respostas curtas','s',NOW)
    with pytest.raises(MemoryError,match='incerto'):
        repo.store(candidate,policy,NOW,consent)
    assert len(calls)==1 and len(list(Path(repo.root).glob('*.md')))==1
    monkeypatch.setattr(module,'deserialize',original)
    assert repo.store(candidate,policy,NOW,consent).state=='existing'


def test_large_context_does_not_exceed_character_budget(storage):
    repo,policy=storage
    for i in range(3):
        text=('procedimento longo ' * 75) + str(i)
        repo.store(user_candidate(text,'s',NOW),policy,NOW,consent)
    result=repo.retrieve('procedimento longo',policy,NOW,consent)
    assert len(result)<3 and sum(len(row['content']) for row in result)<=4000


def test_overlap_preserves_both_versions_and_records_authorization(storage):
    repo,policy=storage
    first=repo.store(user_candidate('prefiro respostas curtas','s',NOW),policy,NOW,consent)
    second=repo.store(user_candidate('não prefiro respostas curtas','s',NOW),policy,NOW,consent)
    _,candidate=deserialize(Path(second.path).read_text(encoding='utf-8'))
    assert candidate.authorization_id==policy.authorization
    assert any(first.identifier in relationship for relationship in candidate.related)
    assert len(list(Path(repo.root).glob('*.md')))==2


def test_copying_entire_note_does_not_create_learning(tmp_path):
    from dataclasses import replace
    text='Procedimento de teste: valide a fonte e só então apresente os dados autorizados.'
    path=tmp_path/'source.md';path.write_text(text,encoding='utf-8')
    candidate=replace(user_candidate(text,'s',NOW),source=SourceReference.file(path,text,(str(tmp_path),)),kind='procedimento')
    with pytest.raises(MemoryError,match='Cópia integral'):
        validate_candidate(candidate)


def test_operation_evidence_requires_explicit_resolver_after_restart(storage):
    from therion.memory.coordinator import MemoryCoordinator
    from unittest.mock import MagicMock
    repo, policy = storage
    service = MemoryCoordinator('s', clock=lambda: NOW)
    provider = MagicMock(model='fictício')
    def extract(evidence, **kwargs):
        return [{'title':'Consulta indisponível', 'summary':'Consulta sem resultado válido não prova agenda livre.',
            'kind':'limitação', 'reason':'Evitar conclusões sem evidência.',
            'evidence':evidence['content'][:180], 'sensitivity':'non_sensitive'}]
    provider.extract_memory_candidates.side_effect = extract
    service.observe_result('calendar_query_failed', provider)
    service.observe_result('calendar_query_failed', provider)
    assert service.wait_idle()
    candidate, = service.snapshot()
    with pytest.raises(MemoryError, match='Fonte'):
        repo.store(candidate, policy, NOW)
    saved = repo.store(candidate, policy, NOW, service._operation_source_valid)
    restarted = MarkdownMemoryRepository(repo.root)
    assert restarted.retrieve('consulta', policy, NOW, service._operation_source_valid)
    service.close()
    assert not restarted.retrieve('consulta', policy, NOW, service._operation_source_valid)
    assert Path(saved.path).exists()  # Revogar a evidência não apaga o rascunho.


def test_old_candidate_cannot_bypass_daily_publication_limit(storage):
    repo, policy = storage
    policy = replace(policy, per_day=1)
    old = NOW - timedelta(days=1)
    repo.store(user_candidate('prefiro respostas curtas', 'a', old), policy, NOW, consent)
    restarted = MarkdownMemoryRepository(repo.root)
    with pytest.raises(MemoryError, match='Limite'):
        restarted.store(user_candidate('prefiro exemplos concretos', 'b', old), policy, NOW, consent)
    assert len(list(Path(repo.root).glob('*.md'))) == 1
