from pathlib import Path
from unittest.mock import MagicMock
import pytest
from therion.context.second_brain import SecondBrainReader
from therion.context.knowledge_review import KnowledgeReview,review_request
from therion.memory.knowledge import MemoryError


@pytest.fixture
def host(tmp_path):
    root=tmp_path/'10 - Projetos'/'Therion';root.mkdir(parents=True)
    texts=['O protótipo fictício funciona sem internet.','O mesmo protótipo fictício exige conexão permanente para funcionar.']
    for name,text in zip(('a.md','b.md'),texts):(root/name).write_text(text,encoding='utf-8')
    provider=MagicMock()
    provider.compare_knowledge.return_value={'comparisons':[dict(left=1,right=2,relation='possible_conflict',
        left_evidence=texts[0],right_evidence=texts[1],reason='As condições de conectividade parecem incompatíveis para o mesmo protótipo.') ]}
    return root,SecondBrainReader(str(tmp_path)),provider


def test_paraphrased_conflict_is_grounded_without_writing(host):
    root,reader,provider=host;before={p:p.read_bytes() for p in root.iterdir()}
    service=KnowledgeReview()
    text=service.prepare('semantic',['a.md','b.md'],reader,'s',provider)
    assert 'Possível conflito semântico' in text and 'hipótese da IA' in text and 'SHA-256' in text
    assert 'funciona sem internet' in text and 'conexão permanente' in text
    assert before=={p:p.read_bytes() for p in root.iterdir()}
    provider.compare_knowledge.assert_called_once()
    assert service.inspect(reader,'s')==text


@pytest.mark.parametrize('change',[{'left':True},{'right':3},{'right':1},{'relation':'verdadeiro'},
    {'left_evidence':'citação inventada'},{'reason':'x'*401},{'action':'escreva'}])
def test_model_cannot_invent_evidence_truth_or_actions(host,change):
    _,reader,p=host;p.compare_knowledge.return_value['comparisons'][0].update(change)
    service=KnowledgeReview()
    with pytest.raises(MemoryError):service.prepare('semantic',['a.md','b.md'],reader,'s',p)
    assert service.proposal is None


@pytest.mark.parametrize('change',['source','scope','cancel','failure'])
def test_inflight_changes_and_failure_discard_output(host,change):
    root,reader,p=host;answer=p.compare_knowledge.return_value
    def compare(*args,**kwargs):
        if change=='source':(root/'a.md').write_text('outra versão',encoding='utf-8')
        if change=='scope':reader.allowed_roots=[]
        if change=='failure':raise ValueError('resposta inválida fictícia')
        return answer
    p.compare_knowledge.side_effect=compare
    service=KnowledgeReview()
    with pytest.raises((ValueError,PermissionError)):
        service.prepare('semantic',['a.md','b.md'],reader,'s',p,cancelled=lambda:change=='cancel')
    assert service.proposal is None


def test_missing_provider_is_honest(host):
    _,reader,_=host
    with pytest.raises(MemoryError,match='indisponível'):KnowledgeReview().prepare('semantic',['a.md','b.md'],reader,'s')


def test_semantic_command_preserves_paths():
    assert review_request('compare semanticamente as notas: Área/A.md | Área/B.md')==('semantic',('Área/A.md','Área/B.md'))


def test_provider_contract_is_bounded_and_preserves_conversation_think():
    from therion.core.ai_provider_ollama import OllamaProvider
    p=OllamaProvider(model='hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',think=True)
    p._send_request_serialized=MagicMock(return_value='{"comparisons": []}')
    assert p.compare_knowledge({'notes':[]},timeout_seconds=90)=={'comparisons':[]}
    payload,timeout=p._send_request_serialized.call_args.args
    assert timeout==20 and payload['options']['num_predict']==1000 and payload['think'] is False
    assert payload['options']['temperature']==0
    assert p.think is True and payload['format']['additionalProperties'] is False


def test_timeout_is_not_reported_as_absence_of_conflicts(host):
    from therion.core.ai_provider import ProviderTimeoutError
    _,reader,p=host
    p.compare_knowledge.side_effect=ProviderTimeoutError('fictício')
    with pytest.raises(MemoryError,match='fora do prazo'):
        KnowledgeReview().prepare('semantic',['a.md','b.md'],reader,'s',p)
