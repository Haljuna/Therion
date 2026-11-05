import json
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication,QWidget
from scripts.voice_session_metrics import VoiceSessionMetrics,summarize,owned_tts_memory
from therion.agent import AgentEvent


def test_metrics_excludes_content_and_leaves_original_event_delivery(tmp_path):
    app=QApplication.instance() or QApplication([]);window=QWidget();events=[]
    window._orchestrator=SimpleNamespace(_emit_agent_event=events.append)
    window._speech_output=SimpleNamespace(process=None,state='idle',is_ready=False)
    window._voice_service=SimpleNamespace(state='not-loaded')
    window._config={'ai':{'model':'qwen3:4b'},'tts':{'provider':'kokoro','voice':'alex_santa_c'}}
    window._conversation_mode=False;window._processing=False
    clock=[0.0]
    metrics=VoiceSessionMetrics(window,tmp_path,clock=lambda:clock[0],memory_reader=lambda pid:123)
    secret='SEGREDO_QUE_NAO_DEVE_SER_REGISTRADO'
    window._orchestrator._emit_agent_event(AgentEvent(1,'s','t',1,'terminal',{'message':secret}))
    clock[0]=3601;report=metrics.close()
    try:
        assert events[0].payload['message']==secret
        assert secret not in (tmp_path/'voice-session-metrics.jsonl').read_text(encoding='utf-8')
        assert secret not in json.dumps(report)
        assert report['runtime_terminals']==1 and report['conversation_samples']==0
        assert report['acceptance']=='requires_review'
        assert report['fixture_profile']['tts_memory_efficient'] is False
        assert metrics.close() is None
    finally:window.deleteLater();app.processEvents()


def test_memory_is_not_spliced_across_distinct_tts_processes():
    def row(t,pid,size):
        return {'elapsed_seconds':t,'ui_pid':1,'ui_private_bytes':100,'tts_pid':pid,'tts_private_bytes':size,
            'speech_state':'idle','conversation':False,'event_counts':{}}
    report=summarize([row(0,2,1000),row(301,2,1100),row(500,3,1000000),row(801,3,1001000)])
    assert report['memory_after_5min']['tts:2']['first_bytes']==1100
    assert report['memory_after_5min']['tts:3']['first_bytes']==1001000
    assert report['conversation_samples']==0


def test_tts_memory_includes_owned_child_and_never_adopts_an_unrelated_pid():
    process=object();queried=[]
    tree=SimpleNamespace(closed=False,root=10,handles={10:100,11:110,12:120},
        api=SimpleNamespace(WaitForSingleObject=lambda handle,timeout:0 if handle==120 else 258),
        _created=lambda handle:handle*1000)
    speech=SimpleNamespace(process=process,_process_trees={process:tree})
    def read(pid):queried.append(pid);return {10:800000,11:1400000000}[pid]
    rows=owned_tts_memory(speech,read)
    assert queried==[10,11]
    assert rows==[{'pid':10,'created':100000,'private_bytes':800000,'root':True},
        {'pid':11,'created':110000,'private_bytes':1400000000,'root':False}]
    assert owned_tts_memory(SimpleNamespace(process=object(),_process_trees={}),read)==[]


def test_tts_sample_discarded_when_original_process_exits_during_read():
    process=object();alive=[258,0]
    tree=SimpleNamespace(closed=False,root=10,handles={10:100},
        api=SimpleNamespace(WaitForSingleObject=lambda *args:alive.pop(0)),_created=lambda handle:123)
    assert owned_tts_memory(SimpleNamespace(process=process,_process_trees={process:tree}),lambda pid:500)==[]


def test_tts_worker_reused_pid_has_separate_memory_identity():
    def row(t,created,size):
        return {'elapsed_seconds':t,'speech_state':'idle','conversation':False,'event_counts':{},
            'tts_processes':[{'pid':11,'created':created,'private_bytes':size,'root':False}]}
    report=summarize([row(0,100,1000),row(301,100,1100),row(500,200,1000000),row(801,200,1001000)])
    assert report['memory_after_5min']['tts_process:11:100']['first_bytes']==1100
    assert report['memory_after_5min']['tts_process:11:200']['first_bytes']==1001000
    assert report['tts_descendants_observed'] is True
