"""Releitura, paginação e detalhes verificáveis sem conteúdo pessoal."""
import asyncio
import pytest
from therion.agent import AgentDecision, AgentEvent, AgentRuntime, ToolCall, ToolResult, ToolSpec
from therion.agent.registry import ToolRegistry, object_schema
from therion.agent.reading import complete_reads, missing_reading, read_range, reading_required
from therion.agent.presentation import event_detail
from tests.test_agent_runtime import ScriptedProvider


def page(start=0, end=10, total=10, version='v1', **extra):
    data={'text':'x'*(end-start),'offset':start,'total_characters':total,
          'partial':start>0 or end<total,'next_offset':end if end<total else None}
    data.update(extra)
    return ToolCall('read_source',{}), ToolResult('success',data=data,
        evidence=({'id':'note:1','source':'/fixture/Aurora.md','version':version},))


def test_gaps_last_page_and_different_versions_do_not_prove_complete_read():
    assert not complete_reads([page(5,10)])
    assert not complete_reads([page(0,3),page(5,10)])
    assert not complete_reads([page(0,5),page(5,10,version='v2')])
    assert not complete_reads([page(),page(0,5,version='v2')])
    assert complete_reads([page(0,6),page(5,10)])=={'note:1'}
    assert complete_reads([page()])=={'note:1'}


@pytest.mark.parametrize('extra',[{'coverage_limited':True},{'warnings':['OCR necessário']},
    {'next_offset':99},{'total_characters':True},{'offset':-1}])
def test_invalid_or_limited_coverage_never_counts_as_complete(extra):
    assert not complete_reads([page(**extra)])


def test_empty_search_or_wrong_file_never_proves_reread():
    result=(ToolCall('search_notes',{}),ToolResult('success',data=[]))
    assert missing_reading('Leia novamente Aurora.md inteira.','Não há senha na nota.',[result],set())
    assert missing_reading('Leia novamente Outra.md inteira.','Conferido.',[page()],set())
    assert not missing_reading('Leia novamente Aurora.md inteira.','Conferido.',[page()],{'note:1'})


def test_named_file_with_spaces_is_checked_without_accepting_wrong_prefix():
    call,result=page()
    evidence=({'id':'note:1','source':'/fixture/Plano Aurora.md','version':'v1'},)
    result=ToolResult('success',data=result.data,evidence=evidence)
    assert not missing_reading('Leia a nota Plano Aurora.md inteira.','Conferido.',[(call,result)],{'note:1'})
    assert missing_reading('Leia a nota Aurora.md inteira.','Conferido.',[(call,result)],{'note:1'})


def test_greeting_and_refusal_do_not_claim_complete_read():
    assert not reading_required('Olá','Olá!')
    assert not reading_required('Não leia a nota inteira.','Não realizei leitura completa.')
    assert reading_required('Qual é a senha?','A senha não consta na nota Aurora.')
    assert reading_required('Qual é a senha?','A senha não foi encontrada na fonte.')
    assert not reading_required('Enviou?', 'A mensagem não foi enviada. Fonte: note:1.')
    from scripts.agent_workflow_fixture import PROMPT
    assert not reading_required(PROMPT,'Enviei a resposta e registrei a pendência revisada.')


@pytest.mark.parametrize('answer',['Não há senha registrada. note:1.','Não encontrei a senha. note:1.'])
def test_cited_read_source_requires_fresh_coverage_without_resource_word_in_prose(answer):
    assert missing_reading('Qual é a senha?',answer,[],{'note:1'})
    assert missing_reading('Qual é a senha?',answer,[page(0,5)],{'note:1'})
    assert not missing_reading('Qual é a senha?',answer,[page()],{'note:1'})
    assert not missing_reading('Enviou?', 'A mensagem não foi enviada. receipt:1.',[],{'receipt:1'})


def test_new_question_cannot_use_historical_summary_as_a_new_read():
    assert missing_reading('Qual é o prazo?', 'O prazo é amanhã. note:1.',[],{'note:1'},historical_ids={'note:1'})
    assert not missing_reading('Qual era o código que você informou?', 'PONTE-42. note:1.',[],{'note:1'},historical_ids={'note:1'})
    assert not missing_reading('Qual é o prazo?', 'O prazo é amanhã. note:1.',[page()],{'note:1'},historical_ids={'note:1'})


@pytest.mark.parametrize('answer',['Não possui senha. note:1.','Não inclui senha. note:1.'])
def test_absence_is_not_recap_even_with_past_tense_request(answer):
    assert missing_reading('Qual era a senha?',answer,[],{'note:1'},historical_ids={'note:1'})


def test_model_gets_one_correction_and_reads_before_finalizing():
    events=[];tools=ToolRegistry()
    tools.register(ToolSpec('read_source','Ler fixture',object_schema(),lambda args,token:page()[1],
        authorize=lambda args:True,verify=lambda *args:True))
    provider=ScriptedProvider(AgentDecision('final','Após revisão completa, a nota não contém senha.'),
        AgentDecision('tools',calls=(ToolCall('read_source',{}),)),
        AgentDecision('final','A nota não contém senha. Fonte: note:1.'))
    result=asyncio.run(AgentRuntime(provider,tools,emit=events.append).run('Leia Aurora.md inteira.',session_id='s'))
    assert result.status=='completed' and len(result.results)==1
    assert len([event for event in events if event.type=='decision_rejected'])==1
    step=next(event for event in events if event.type=='tool_finished')
    assert step.payload['reading']['complete'] and step.payload['verified']
    assert 'caracteres 0–10 de 10; leitura completa' in event_detail(step)
    assert events[-1].payload['complete_read_count']==1


def test_repeated_unsupported_read_claim_cannot_complete():
    decision=AgentDecision('final','Após revisão completa, a nota não contém senha.')
    events=[]
    result=asyncio.run(AgentRuntime(ScriptedProvider(decision,decision),ToolRegistry(),emit=events.append).run(
        'Leia novamente Aurora.md inteira.',session_id='s'))
    assert result.status=='partial' and not result.results
    assert 'Não há leitura integral verificada' in result.message
    assert 'nenhuma nova leitura neste turno' in event_detail(events[-1])


def test_activity_flood_preserves_steps_and_sequence(tmp_path):
    from therion.core.orchestrator import Orchestrator
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_state_root=tmp_path/'state')
    try:
        def emit(number,kind):host._emit_agent_event(AgentEvent(number,'s','t',1,kind,{}))
        emit(1,'tool_finished')
        for number in range(2,2002):emit(number,'provider_activity')
        emit(2002,'terminal')
        events=host.agent_events()
        assert [event.type for event in events]==['tool_finished','provider_activity','terminal']
        assert [event.sequence for event in events]==[1,2001,2002]
        assert not host.agent_events()
    finally:host.close()


def test_section_pagination_uses_extracted_character_ranges():
    call,result=page()
    data=dict(result.data);data.pop('text');data['sections']=[{'text':'1234'},{'text':'567890'}]
    result=ToolResult('success',data=data,evidence=result.evidence)
    assert read_range(ToolCall('document_read',{}),result)['end']==10
    assert complete_reads([(ToolCall('document_read',{}),result)])=={'note:1'}


def test_desktop_shows_read_range_and_terminal_without_read(tmp_path):
    from PySide6.QtWidgets import QApplication
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    qt=QApplication.instance() or QApplication([])
    config={'tts':{'enabled':False},'agent':{'enabled':False}}
    vault=tmp_path/'vault';vault.mkdir()
    knowledge=KnowledgeRuntime(vault,tmp_path/'memory',lambda:config)
    window=MainWindow(qt,config,knowledge_runtime=knowledge,log_dir=str(tmp_path/'logs'))
    try:
        host=window._orchestrator
        host._emit_agent_event(AgentEvent(1,host.session_id,'t',1,'tool_finished',{
            'name':'read_source','status':'success','verified':True,
            'reading':{'offset':0,'end':10,'total':10,'complete':True}}))
        window._poll_workflow_progress()
        assert 'caracteres 0–10 de 10; leitura completa' in window._agent_details_view.toPlainText()
        host._emit_agent_event(AgentEvent(2,host.session_id,'t',1,'terminal',{'status':'completed','read_count':0}))
        window._poll_workflow_progress()
        assert 'nenhuma nova leitura neste turno' in window._agent_details_view.toPlainText()
    finally:
        window._orchestrator.close();window.deleteLater();qt.processEvents()


def test_stop_button_releases_real_qt_worker_and_shows_feedback(tmp_path):
    import time
    from PySide6.QtWidgets import QApplication
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    from tests.test_agent_turn_coordination import WaitingProvider
    qt=QApplication.instance() or QApplication([])
    config={'tts':{'enabled':False},'agent':{'enabled':True}}
    vault=tmp_path/'vault';vault.mkdir()
    window=MainWindow(qt,config,knowledge_runtime=KnowledgeRuntime(vault,tmp_path/'memory',lambda:config),
        log_dir=str(tmp_path/'logs'))
    provider=WaitingProvider();window._orchestrator._agent_provider=provider
    try:
        window._input.setPlainText('Converse sobre Aurora.');window._send_command()
        deadline=time.monotonic()+3
        while not provider.started.is_set() and time.monotonic()<deadline:
            qt.processEvents();time.sleep(.005)
        assert provider.started.is_set()
        assert window._workflow_cancel_button.text()=='Parar'
        assert window._stop_speech_button.text()=='Parar fala'
        window._poll_workflow_progress()
        started=time.monotonic();window._workflow_cancel_button.click()
        assert window._workflow_label.text()=='Cancelando etapas restantes…'
        assert time.monotonic()-started < .5
        deadline=time.monotonic()+2
        while window._processing and time.monotonic()<deadline:
            qt.processEvents();time.sleep(.005)
        assert not window._processing
        window._poll_workflow_progress()
        assert 'cancelled' in window._agent_details_view.toPlainText()
    finally:
        window._orchestrator.cancel_agent()
        if window._command_worker is not None:window._command_worker.wait(3000)
        qt.processEvents();window._orchestrator.close();window.deleteLater();qt.processEvents()
