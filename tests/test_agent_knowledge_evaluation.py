import asyncio
import importlib.util
from pathlib import Path
import pytest
from therion.agent import AgentRuntime,AgentDecision,ToolCall
from therion.agent.store import SessionStore
from therion.agent.procedures import ProcedureLibrary
from tests.test_agent_runtime import ScriptedProvider


def evaluator():
    path=Path(__file__).resolve().parents[1]/'scripts/evaluate-agent-knowledge.py'
    spec=importlib.util.spec_from_file_location('knowledge_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_knowledge_runner_uses_real_selected_note_versions(tmp_path):
    module=evaluator();(tmp_path/'Aurora.md').write_text('# Aurora\nPlano alternativo: VELA-31',encoding='utf-8')
    def call(name,**args):return AgentDecision('tools',calls=(ToolCall(name,args),))
    provider=ScriptedProvider(call('search_notes',query='Aurora'),call('read_source',source_id='note:1'),AgentDecision('final','VELA-31 note:1'))
    result=asyncio.run(AgentRuntime(provider,module.knowledge_registry(tmp_path)).run('Consulte Aurora.',session_id='fixture'))
    assert result.status=='completed' and result.results[-1][1].data['text'].endswith('VELA-31')


def test_reviewed_fixture_activation_requires_actual_matching_read_receipts(tmp_path):
    module=evaluator();store=SessionStore(tmp_path/'history.sqlite3');library=ProcedureLibrary(store)
    old=dict(title='Relatório Aurora',goal='Consultar código',preconditions='Ler versão ativa',tools='report_lookup',steps='Usar TOPO-17',verification='Conferir report:aurora',limitations='Somente leitura')
    identifier=library.propose(old,{'kind':'fixture'})
    asyncio.run(module.reviewed_activation(library,identifier,'TOPO-17'))
    parent=library.get(identifier)
    candidate=library.propose_revision(identifier,parent['digest'],dict(old,steps='Usar TOPO-83'),{'kind':'human_fixture'})
    asyncio.run(module.reviewed_activation(library,candidate,'TOPO-83'))
    assert library.get(identifier)['state']=='retired' and library.get(candidate)['state']=='active'
    receipts=store.operations()
    assert len(receipts)==4 and all(row['verified']==1 for row in receipts)


def test_normalized_lookup_keeps_original_text_and_literal_queries(tmp_path):
    import unicodedata
    from therion.context.second_brain import SecondBrainReader
    text=unicodedata.normalize('NFD','# Café\n\nA ação combinada é VELA-31.\n')
    (tmp_path/'Lotus.md').write_text(text,encoding='utf-8')
    reader=SecondBrainReader(str(tmp_path),[str(tmp_path)])
    assert not reader.search_notes('acao')
    rows=reader.search_notes('acao',normalize_accents=True,constrained=True)
    assert len(rows)==1 and unicodedata.normalize('NFD','ação combinada') in rows[0].snippet
    assert not reader.search_notes('"acao"',normalize_accents=True,constrained=True)
    assert reader.read_note('Lotus.md',constrained=True).content==text


def test_unreadable_or_oversized_note_is_not_reported_as_empty_search(tmp_path):
    module=evaluator();target=tmp_path/'Aurora.md'
    with target.open('wb') as stream:stream.truncate(20_000_001)
    registry=module.knowledge_registry(tmp_path);spec,blocked=registry.prepare(ToolCall('search_notes',{'query':'Aurora'}))
    from therion.agent import CancellationToken
    result=asyncio.run(spec.handler({'query':'Aurora'},CancellationToken()))
    assert blocked is None and result.status=='unavailable' and result.message and not result.evidence


def test_multiword_lookup_and_human_subject_hint_rank_the_correct_original(tmp_path):
    from therion.context.second_brain import SecondBrainReader
    for name in ('Atlas','Aurora','Cedro','Horizonte','Lótus','Íris'):
        (tmp_path/(name+'.md')).write_text('# Projeto '+name+'\nContexto de entrega.\nPlano de contingência: código fictício.',encoding='utf-8')
    reader=SecondBrainReader(str(tmp_path),[str(tmp_path)])
    assert not reader.search_notes('plano alternativo Atlas projeto atraso')
    rows=reader.search_notes('plano alternativo Atlas projeto atraso',constrained=True,normalize_accents=True,context_hint='Plano alternativo para Atlas')
    assert rows[0].path=='Atlas.md' and 'contingência' in rows[0].snippet
    generic=reader.search_notes('contingencia',constrained=True,normalize_accents=True,context_hint='Identificador da contingência do projeto Íris')
    assert generic[0].path=='Íris.md'
    assert not reader.search_notes('"plano alternativo Atlas projeto atraso"',constrained=True,normalize_accents=True)


def test_procedure_verification_example_cannot_be_cited_as_query_evidence():
    from therion.agent import ToolSpec,ToolResult
    from therion.agent.registry import ToolRegistry,object_schema
    registry=ToolRegistry()
    registry.register(ToolSpec('procedure_read','Consultar instruções',object_schema(),
        lambda args,token:ToolResult('success',data={'verification':'Conferir report:aurora'},
        evidence=({'id':'procedure:reviewed','source':'Procedimento fictício'},)),authorize=lambda args:True))
    provider=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('procedure_read',{}),)),
        AgentDecision('final','O resultado é report:aurora, conforme procedure:reviewed.'))
    result=asyncio.run(AgentRuntime(provider,registry).run('Execute o procedimento e consulte o relatório.',session_id='fixture'))
    assert result.status=='partial' and 'fonte que não foi confirmada' in result.message
