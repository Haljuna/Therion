from pathlib import Path
from unittest.mock import MagicMock
import pytest
from therion.context.second_brain import SecondBrainReader
from therion.memory.coordinator import MemoryCoordinator
from therion.skills.proposals import REFERENCES, skill_proposals


@pytest.fixture
def host(tmp_path):
    for relative in REFERENCES:
        path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('# Referência fictícia\nEstado: em teste\nNenhuma permissão é concedida.',encoding='utf-8')
    return SecondBrainReader(str(tmp_path)),MemoryCoordinator('s')


def test_only_verified_recurrence_creates_evolution_proposal(host):
    reader,coordinator=host
    assert 'Não há padrão' in skill_proposals(reader,coordinator)
    coordinator.observe_result('calendar_query_failed',None)
    assert 'Não há padrão' in skill_proposals(reader,coordinator)
    coordinator.observe_result('calendar_query_failed',None)
    before={p:p.read_bytes() for p in Path(reader.vault_root).rglob('*.md')}
    text=skill_proposals(reader,coordinator)
    assert 'SKILL-002' in text and 'pelo menos 2' in text and 'SHA-256' in text
    assert 'Nenhum arquivo' in text and 'Passos:' in text and 'Validação proposta:' in text
    assert before=={p:p.read_bytes() for p in Path(reader.vault_root).rglob('*.md')}
    coordinator.reset('new')
    assert 'Não há padrão' in skill_proposals(reader,coordinator)


def test_unknown_model_claim_does_not_count(host):
    reader,c=host
    for _ in range(3):c.observe_result('modelo_disse_que_falhou',None)
    assert not c.verified_patterns()
    assert 'Não há padrão' in skill_proposals(reader,c)


def test_missing_or_revoked_references_fail_closed(host):
    reader,c=host
    for _ in range(2):c.observe_result('action_verification_failed',None)
    Path(reader.vault_root,REFERENCES[0]).unlink() # exclusivamente fixture
    with pytest.raises((ValueError,OSError)):skill_proposals(reader,c)


def test_internal_limitation_survives_model_uncertainty(host):
    _,c=host
    provider=MagicMock(model='fictício')
    provider.extract_memory_candidates.return_value=[]
    c.observe_result('calendar_query_failed',provider)
    c.observe_result('calendar_query_failed',provider)
    assert c.wait_idle()
    candidate,=c.snapshot()
    assert candidate.kind=='limitação' and candidate.model.startswith('verificador interno')
    assert 'desconhecido' in candidate.summary
    c.close()
