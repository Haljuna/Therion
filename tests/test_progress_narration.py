"""Andamento falado com relógio, áudio e ferramentas fictícios."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import pytest
from tests.test_constellation import app,window,settle
from therion.voice.progress_narration import ProgressNarration
from therion.agent import AgentRuntime,AgentDecision,ToolCall,ToolResult,ToolSpec
from therion.agent.registry import ToolRegistry,object_schema

def event(kind,**payload):return SimpleNamespace(type=kind,payload=payload)

def test_fast_tasks_are_silent_and_long_tasks_do_not_repeat():
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    assert n.next_phrase() is None
    clock[0]=5.99;assert n.next_phrase() is None
    clock[0]=6.;assert n.next_phrase()=='Estou preparando a resposta.'
    clock[0]=90.;assert n.next_phrase() is None

def test_quick_tool_task_finishes_without_any_announcement():
    # Ex.: abrir o navegador — decisão, execução e resposta em poucos segundos.
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    clock[0]=1;n.observe(event('tool_running',effect='external'))
    clock[0]=2;assert n.next_phrase() is None
    clock[0]=2.5;n.observe(event('tool_finished',status='success'))
    clock[0]=3.5;assert n.next_phrase() is None

def test_stage_that_just_changed_is_not_announced_even_in_a_long_turn():
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    clock[0]=7;n.observe(event('tool_finished',status='success'))
    clock[0]=8;assert n.next_phrase() is None
    clock[0]=9;assert n.next_phrase()=='Estou conferindo o resultado.'

@pytest.mark.parametrize('effect,phrase',[('read','Estou verificando as informações.'),('prepare','Estou preparando a resposta.'),('write','Estou executando essa etapa.'),('external','Estou executando essa etapa.')])
def test_phrase_follows_the_actual_authorized_stage(effect,phrase):
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    n.observe(event('tool_running',effect=effect));clock[0]=6
    assert n.next_phrase()==phrase

def test_waiting_or_terminal_states_never_announce_execution():
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    clock[0]=2;n.observe(event('tool_started',name='destructive_operation'))
    clock[0]=6;assert n.next_phrase()=='Estou verificando as informações.'
    for kind in ('awaiting_confirmation','terminal','provider_failed'):
        n.observe(event(kind));clock[0]+=20
        assert n.next_phrase() is None

def test_cooldown_limit_and_cancel_keep_progress_brief():
    clock=[0.];n=ProgressNarration(clock=lambda:clock[0])
    clock[0]=6;assert n.next_phrase()
    n.observe(event('tool_running',effect='read'));clock[0]=9;assert n.next_phrase() is None
    clock[0]=18;assert n.next_phrase()=='Estou verificando as informações.'
    n.observe(event('tool_running',effect='write'));clock[0]=40;assert n.next_phrase() is None
    n.cancel();assert n.next_phrase() is None

def age(narration,seconds=10):
    narration.started-=seconds;narration.phase_since-=seconds

def configure(window):
    from therion.interface.desktop import _CommandWorker
    worker=_CommandWorker(window._orchestrator,'consulta fictícia')
    window._conversation_mode=True;window._processing=True;window._command_worker=worker
    speech=MagicMock();speech.state='idle';speech._held_prefix=None
    window._speech_output=speech;window._begin_progress_narration(worker)
    age(window._progress_narration)
    return worker,speech

def clean(window):
    window._briefing_intro=None;window._progress_narration.cancel()
    window._conversation_mode=False;window._processing=False;window._command_worker=None

def test_narration_does_not_wait_for_or_stop_a_running_action(window):
    worker,speech=configure(window)
    try:
        window._poll_progress_narration([event('tool_running',effect='read')])
        speech.speak.assert_not_called()  # etapa recém-iniciada ainda pode terminar rápido
        age(window._progress_narration,3)
        window._poll_progress_narration([])
        speech.speak.assert_called_once_with('Estou verificando as informações.')
        assert window._processing and window._command_worker is worker
        assert not worker.cancelled.is_set()
        speech.stop.assert_not_called()
        window._speech_text='Resultado confirmado da consulta.'
        window._conversation_reply();assert speech.speak.call_count==1
        window._processing=False;window._conversation_playback_finished()
        assert speech.speak.call_args.args[0]=='Resultado confirmado da consulta.'
    finally:clean(window)

@pytest.mark.parametrize('reason',['stopped','stale','typed','prefix','cancelled'])
def test_no_unwanted_or_stale_narration(window,reason):
    worker,speech=configure(window)
    try:
        if reason=='stopped':window._stop_speech()
        elif reason=='stale':window._progress_identity=('outra-sessao',0)
        elif reason=='typed':window._conversation_mode=False
        elif reason=='prefix':speech._held_prefix='Resposta final em preparação.'
        else:worker.cancelled.set()
        window._poll_progress_narration([event('tool_running',effect='write')])
        speech.speak.assert_not_called()
    finally:clean(window)

@pytest.mark.parametrize('allowed',[True,False])
def test_running_event_is_emitted_only_after_authorization(allowed):
    events=[];called=[]
    class Provider:
        def __init__(self):self.decided=False
        async def decide(self,*args):
            if not self.decided:
                self.decided=True
                return AgentDecision('tools',calls=(ToolCall('lookup',{}),))
            return AgentDecision('final','Consulta finalizada com a fonte fictícia.')
    registry=ToolRegistry()
    registry.register(ToolSpec('lookup','Consulta fictícia',object_schema(),
        lambda args,token:called.append(True) or ToolResult('success',evidence=({'id':'fixture'},)),
        authorize=lambda args:allowed,effect='read'))
    runtime=AgentRuntime(Provider(),registry,emit=events.append)
    asyncio.run(runtime.run('Consulta fictícia',session_id='fixture'))
    running=[e for e in events if e.type=='tool_running']
    assert bool(running)==allowed and bool(called)==allowed
    if running:assert running[0].payload['effect']=='read'

def test_action_worker_keeps_running_while_progress_is_sent_to_speech(window):
    from therion.core.orchestrator import OrchestrationResult
    entered=threading.Event();release=threading.Event()
    speech=MagicMock();speech.state='idle';speech._held_prefix=None
    window._speech_output=speech;window._conversation_mode=True
    def action(*args):
        entered.set()
        assert release.wait(5),'O teste não liberou o worker fictício.'
        return OrchestrationResult(status='success',message='Resultado fictício confirmado.')
    with patch.object(window._orchestrator,'process_session_command',side_effect=action):
        window._set_processing(True);window._start_command_worker('consulta fictícia')
        worker=window._command_worker
        try:
            settle(entered.is_set)
            age(window._progress_narration)
            window._poll_workflow_progress()
            assert worker.isRunning() and window._processing
            speech.speak.assert_called_once_with('Estou preparando a resposta.')
            release.set();settle(lambda:window._command_worker is None)
            assert speech.speak.call_count==1
            window._conversation_playback_finished()
            assert speech.speak.call_args.args[0]=='Resultado fictício confirmado.'
        finally:
            release.set();worker.wait(3000)
            clean(window)
