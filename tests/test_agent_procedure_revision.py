import pytest

from therion.agent.contracts import ToolCall
from therion.agent.procedures import ProcedureLibrary
from therion.agent.store import SessionStore


def active(library,body):
    identifier=library.propose(body,{'kind':'fixture'});row=library.get(identifier)
    library.transition(identifier,'testing',row['digest'])
    evidence(library,identifier)
    library.transition(identifier,'active',row['digest'])
    return identifier,row['digest']


def evidence(library,identifier):
    for index in range(2):
        call=ToolCall('fixture.read',{'index':index,'procedure':identifier})
        library.store.begin(call,'fixture','turn','read');library.store.finish(call.id,'success',verified=True)
        library.record_test(identifier,call.id)


def body():
    return {key:('fixture.read' if key=='tools' else 'Procedimento técnico '+key) for key in ('title','goal','preconditions','tools','steps','verification','limitations')}


def test_revision_keeps_active_until_review_and_verified_tests(tmp_path):
    library=ProcedureLibrary(SessionStore(tmp_path/'state.sqlite3'));original=body();identifier,digest=active(library,original)
    improved=dict(original,steps='Consultar a versão atual antes de escolher a fonte.')
    candidate=library.propose_revision(identifier,digest,improved,{'kind':'fixture_correction'})
    assert candidate!=identifier and library.get(identifier)['state']=='active'
    row=library.get(candidate);assert row['state']=='proposed' and 'diff' in row['source']
    library.transition(candidate,'testing',row['digest'])
    with pytest.raises(ValueError,match='dois recibos'):library.transition(candidate,'active',row['digest'])
    evidence(library,candidate);library.transition(candidate,'active',row['digest'])
    assert library.get(candidate)['state']=='active' and library.get(identifier)['state']=='retired'


def test_parent_change_invalidates_candidate_activation(tmp_path):
    library=ProcedureLibrary(SessionStore(tmp_path/'state.sqlite3'));original=body();identifier,digest=active(library,original)
    candidate=library.propose_revision(identifier,digest,dict(original,steps='Consultar novamente a origem.'),{})
    row=library.get(candidate);library.transition(candidate,'testing',row['digest']);evidence(library,candidate)
    library.transition(identifier,'retired',digest)
    with pytest.raises(ValueError,match='original mudou'):library.transition(candidate,'active',row['digest'])
    assert library.get(candidate)['state']=='testing'


def test_background_revision_requires_index_and_current_read(tmp_path):
    from therion.agent.learning import LearningReviewer
    from therion.agent.contracts import AgentDecision
    from tests.test_agent_runtime import ScriptedProvider
    library=ProcedureLibrary(SessionStore(tmp_path/'state.sqlite3'));original=body();identifier,digest=active(library,original)
    improved=dict(original,steps='Reconsultar a origem após alteração da versão.')
    decisions=[AgentDecision('tools',calls=(ToolCall(name,args),)) for name,args in
        [('procedure_index',{}),('procedure_read',{'id':identifier}),('procedure_revise',{'id':identifier,'body':improved})]]
    provider=ScriptedProvider(*decisions,AgentDecision('final','Correção proposta para revisão.'))
    reviewer=LearningReviewer(library);reviewer.start(provider,[{'tool':'fixture.read','status':'blocked'},{'tool':'fixture.read','status':'success','recovered_issue':True}])
    reviewer.thread.join(timeout=5)
    assert not reviewer.thread.is_alive()
    assert library.get(identifier)['state']=='active'
    candidates=[row for row in library.index() if row['id']!=identifier]
    assert len(candidates)==1 and candidates[0]['state']=='proposed'
    assert library.get(candidates[0]['id'])['body']==improved
