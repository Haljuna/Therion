"""Pré-síntese pode adiantar trabalho; autorização nunca vem do delta."""
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock,patch

import httpx
import pytest
from PySide6.QtWidgets import QApplication
from therion.agent import CancellationToken,TurnBudget
from therion.agent.ollama import OllamaAgentProvider
from therion.voice.speech_output import SpeechOutput
from therion.voice.stream_prefix import first_sentence


TEXT='Esta primeira frase tem conteúdo suficiente para a voz começar a ser preparada. '+('O restante ainda está sendo produzido pelo modelo. '*6)


def test_prefix_preserves_numbers_and_rejects_private_or_structured_content():
    text='O horário é 14:30 e o valor é 3.14 reais. '+('A informação seguinte continua aqui. '*8)
    prefix=first_sentence(text)
    assert prefix and text.startswith(prefix) and '14:30' in prefix and '3.14' in prefix
    for text in ('<think>'+TEXT,'</think>'+TEXT,'{"kind":"final","message":"'+TEXT,'```'+TEXT):
        assert first_sentence(text) is None
    assert first_sentence('O número é 3.') is None


@pytest.mark.parametrize('protocol',['native','json'])
def test_provider_exposes_bounded_prefix_only_from_native_content(protocol):
    events=[]
    def transport(request):
        messages=([{'content':TEXT[:95]},{'content':TEXT[95:]}] if protocol=='native' else
            [{'content':json.dumps({'kind':'final','message':TEXT,'calls':[]})}])
        return httpx.Response(200,content=''.join(json.dumps({'message':message,'done':i==len(messages)-1})+'\n' for i,message in enumerate(messages)).encode())
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat','fixture',protocol=protocol,
        client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(transport),**kw))
    async def run():
        try:return await provider.decide([{'role':'system','content':'Dados fictícios.'}],[],TurnBudget(),CancellationToken(),lambda kind,**data:events.append((kind,data)))
        finally:await provider.aclose()
    result=asyncio.run(run())
    assert result.message==TEXT.strip()
    prefixes=[data['text'] for kind,data in events if kind=='response_prefix']
    assert len(prefixes)==(1 if protocol=='native' else 0)
    if prefixes:assert TEXT.startswith(prefixes[0]) and len(prefixes[0])<=240


@pytest.fixture
def speech():
    app=QApplication.instance() or QApplication([])
    with patch('therion.voice.speech_output.QSoundEffect'):
        speech=SpeechOutput({'provider':'kokoro','streaming_prepare':True})
        speech.sound.isPlaying.return_value=False
        speech.is_ready=True;speech.process=MagicMock()
        yield speech
        speech.release()


def deliver(speech,text=b'audio',last=True):
    path=Path(speech._pending['output']);path.write_bytes(text)
    speech._message({'event':'audio','id':speech.generation,'part':0,'last':last})


def test_audio_held_until_validation_then_tail_and_single_completion(speech):
    prefix=first_sentence(TEXT);finished=[]
    speech.completed.connect(lambda:finished.append(True))
    assert speech.prepare_prefix(prefix)
    deliver(speech)
    speech.sound.play.assert_not_called()
    assert not finished
    assert speech.commit_prefix(TEXT)
    assert speech._pending['text']==TEXT[len(prefix):]
    assert speech.sound.play.call_count==1
    # O início acabou, mas a síntese do restante ainda está ativa.
    speech._playing=True;speech._playing_changed()
    assert not finished and speech._busy
    deliver(speech,b'tail')
    assert speech.sound.play.call_count==2
    speech._playing=True;speech._playing_changed()
    assert finished==[True]
    assert speech.folder is None


def test_commit_while_prefix_is_synthesizing_queues_tail(speech):
    prefix=first_sentence(TEXT)
    assert speech.prepare_prefix(prefix)
    assert speech.commit_prefix(TEXT)
    assert speech._tail_text==TEXT[len(prefix):]
    deliver(speech)
    assert speech.process.write.call_count==2
    assert speech._pending['output'].endswith('tail.wav')


def test_rejected_or_cancelled_prefix_never_plays(speech):
    prefix=first_sentence(TEXT)
    assert speech.prepare_prefix(prefix)
    folder=speech.folder;generation=speech.generation
    deliver(speech)
    assert not speech.commit_prefix('Não há recibo para a operação anunciada.')
    assert not folder.exists()
    speech._message({'event':'audio','id':generation,'part':0})
    speech.sound.play.assert_not_called()
    assert not speech.commit_prefix(TEXT)


def test_no_online_or_implicit_speculative_synthesis(speech):
    for config in ({'provider':'edge','streaming_prepare':True,'online_allowed':True},
                   {'provider':'kokoro'},{'provider':'kokoro','streaming_prepare':'true'}):
        speech.config=config
        assert not speech.prepare_prefix(first_sentence(TEXT))
    speech.process.write.assert_not_called()


def test_voicestudio_prefix_is_held_until_validation(speech):
    speech.config={'provider':'voicestudio','streaming_prepare':True}
    prefix=first_sentence(TEXT)
    assert speech.prepare_prefix(prefix)
    deliver(speech)
    speech.sound.play.assert_not_called()
    assert speech.commit_prefix(TEXT)
    assert speech.sound.play.call_count==1


def test_desktop_commits_only_success_and_discards_on_new_decision(tmp_path,speech):
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    from therion.agent import AgentEvent
    app=QApplication.instance() or QApplication([])
    config={'tts':{'enabled':False},'agent':{'enabled':False}}
    vault=tmp_path/'vault';vault.mkdir()
    window=MainWindow(app,config,knowledge_runtime=KnowledgeRuntime(vault,tmp_path/'memory',lambda:config),
        log_dir=str(tmp_path/'logs'))
    window._speech_output=speech;window._conversation_mode=True
    prefix=first_sentence(TEXT)
    try:
        host=window._orchestrator
        from therion.agent import AgentRuntime
        runtime=AgentRuntime(None,None);runtime.turn_id='t';runtime._token=CancellationToken()
        host._agent_runtime=runtime;window._processing=True
        host._emit_agent_event(AgentEvent(1,host.session_id,'t',1,'response_prefix',{'text':prefix}))
        window._poll_workflow_progress()
        assert speech._held_prefix==prefix
        deliver(speech)
        speech.sound.play.assert_not_called()
        host._emit_agent_event(AgentEvent(2,host.session_id,'t',1,'decision_rejected',{}))
        window._poll_workflow_progress()
        assert speech._held_prefix is None
        speech.sound.play.assert_not_called()
        # Mesmo que o texto coincida, estado parcial nunca libera áudio antecipado.
        speech.is_ready=True;speech.process=MagicMock()
        speech.prepare_prefix(prefix);deliver(speech)
        window._speech_text=TEXT;window._last_agent_response_status='partial'
        with patch.object(speech,'speak') as normal,patch.object(speech,'commit_prefix') as commit:
            window._conversation_reply()
            commit.assert_not_called();normal.assert_called_once_with(TEXT)
        window._last_agent_response_status='success'
        window._conversation_reply()
        assert speech.sound.play.call_count==1
        speech.stop();runtime.cancel()
        host._emit_agent_event(AgentEvent(3,host.session_id,'t',1,'response_prefix',{'text':prefix}))
        window._poll_workflow_progress()
        assert speech._held_prefix is None
    finally:
        window._conversation_mode=False;window._speech_output=None
        host.close();window.deleteLater();app.processEvents()


def test_activation_is_explicit_local_and_preserves_profile(tmp_path):
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'scripts/configure-voice.py'
    spec=importlib.util.spec_from_file_location('stream_voice_config',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ('python.exe','kokoro-v1.0.onnx','voices-v1.0.bin'):(tmp_path/name).write_bytes(b'fixture')
    config={'ai':{'model':'unchanged'},'tts':{'provider':'kokoro','voice':'alex_santa_c',
        'model_root':str(tmp_path),'python_path':str(tmp_path/'python.exe')}}
    result=module.proposal(config,'kokoro',streaming_prepare=True)
    assert result['tts']['streaming_prepare'] is True and result['tts']['voice']=='alex_santa_c'
    assert result['ai']==config['ai'] and 'streaming_prepare' not in config['tts']
    assert module.proposal(result,'kokoro',streaming_prepare=False)['tts']['streaming_prepare'] is False
    with pytest.raises(ValueError,match='Kokoro'):
        module.proposal(result,'edge',str(tmp_path/'python.exe'),allow_online=True,streaming_prepare=True)


def test_implicit_private_content_never_becomes_prepared_prefix():
    events=[]
    private='Conteúdo privado sintético que nunca deve ser enviado à voz. '*5
    chunks=[private,'</thi','nk>\n',TEXT[:170],TEXT[170:]]
    def transport(request):
        return httpx.Response(200,content=''.join(json.dumps({'message':{'content':chunk},'done':i==len(chunks)-1})+'\n'
            for i,chunk in enumerate(chunks)).encode())
    provider=OllamaAgentProvider('http://127.0.0.1:11435/api/chat',
        'hf.co/pramodlohra/Qween3_4B_thinking_finetune:Q4_K_M',protocol='native',think=False,
        client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(transport),**kw))
    async def run():
        try:return await provider.decide([{'role':'user','content':'Fixture.'}],[],TurnBudget(),CancellationToken(),
            lambda kind,**data:events.append((kind,data)))
        finally:await provider.aclose()
    decision=asyncio.run(run())
    prefixes=[data['text'] for kind,data in events if kind=='response_prefix']
    assert decision.message==TEXT.strip() and len(prefixes)==1
    assert TEXT.startswith(prefixes[0]) and 'privado' not in prefixes[0]
