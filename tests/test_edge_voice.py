"""Voz online opcional: consentimento, isolamento, formato e cancelamento."""
import asyncio
import importlib.util
import io
from pathlib import Path
from unittest.mock import MagicMock,patch
import wave
import pytest
from PySide6.QtWidgets import QApplication
from therion.config.local import _validate_config
from therion.voice import edge_worker
from therion.voice.speech_output import SpeechOutput


def test_online_configuration_needs_explicit_boolean_and_keeps_local_profile():
    tts={'enabled':True,'provider':'edge','voice':'alex_santa_c','python_path':'local-python',
         'model_root':'original-models','edge_python_path':'edge-python','unknown':'preserved'}
    assert not _validate_config({'tts':tts})['tts']['enabled']
    assert not _validate_config({'tts':dict(tts,online_allowed='true')})['tts']['enabled']
    result=_validate_config({'tts':dict(tts,online_allowed=True)})['tts']
    assert result['enabled'] and result['voice']=='alex_santa_c'
    assert result['python_path']=='local-python' and result['model_root']=='original-models' and result['unknown']=='preserved'
    assert not _validate_config({'tts':dict(tts,online_allowed=True,edge_voice='unknown')})['tts']['enabled']


def test_worker_refuses_online_before_import_or_request(monkeypatch,capsys):
    monkeypatch.setattr('sys.argv',['edge_worker.py','--serve'])
    assert edge_worker.main()==2
    assert 'online_not_allowed' in capsys.readouterr().out


def test_audio_stream_preserves_numbers_and_rejects_empty_or_large_result(monkeypatch):
    observed=[]
    class Client:
        def __init__(self,text,**kwargs):observed.append((text,kwargs))
        async def stream(self):
            yield {'type':'SentenceBoundary','text':'ignored'}
            yield {'type':'audio','data':b'one'}
            yield {'type':'audio','data':b'two'}
    text='A revisão é às 14:30. O código é 42.'
    assert asyncio.run(edge_worker.download_audio(text,edge_worker.VOICES[0],Client))==b'onetwo'
    assert observed[0][0]==text and observed[0][1]['proxy'] is None
    monkeypatch.setattr(edge_worker,'MAX_AUDIO_BYTES',2)
    with pytest.raises(ValueError,match='limite'):asyncio.run(edge_worker.download_audio(text,edge_worker.VOICES[0],Client))


def test_mp3_is_decoded_to_valid_mono_wav(tmp_path):
    import av
    import numpy as np
    buffer=io.BytesIO()
    with av.open(buffer,'w',format='mp3') as target:
        stream=target.add_stream('mp3',rate=24000)
        frame=av.AudioFrame.from_ndarray(np.zeros((1,2400),dtype=np.int16),format='s16',layout='mono')
        frame.sample_rate=24000
        for packet in stream.encode(frame):target.mux(packet)
        for packet in stream.encode(None):target.mux(packet)
    output=tmp_path/'speech.wav'
    assert edge_worker.decode_wav(buffer.getvalue(),output)>0
    with wave.open(str(output)) as audio:
        assert audio.getnchannels()==1 and audio.getframerate()==24000 and audio.getsampwidth()==2
        assert audio.getnframes()>0
    assert not output.with_suffix('.wav.partial').exists()
    with pytest.raises(Exception):edge_worker.decode_wav(b'invalid audio',tmp_path/'invalid.wav')
    assert not (tmp_path/'invalid.wav.partial').exists()


def test_service_launches_only_selected_worker_and_revocation_stops_dispatch(tmp_path):
    qt=QApplication.instance() or QApplication([])
    python=tmp_path/'python.exe';python.write_bytes(b'fixture only')
    config={'provider':'edge','online_allowed':True,'edge_python_path':str(python),
            'edge_voice':edge_worker.VOICES[0],'voice':'alex_santa_c'}
    with patch('therion.voice.speech_output.QSoundEffect'),patch('therion.voice.speech_output.QProcess') as factory:
        service=SpeechOutput(config)
        try:
            assert service.warmup()
            args=factory.return_value.setArguments.call_args.args[0]
            assert Path(args[0]).name=='edge_worker.py' and '--allow-online' in args and '--root' not in args
            service.is_ready=True
            service.speak('Olá.');assert factory.return_value.write.call_count==1
            config['online_allowed']=False
            service._dispatch()
            assert factory.return_value.write.call_count==1 and service._pending is None
        finally:service.release();service.deleteLater();qt.processEvents()


def test_no_consent_never_starts_process_or_falls_back_to_paid():
    qt=QApplication.instance() or QApplication([])
    with patch('therion.voice.speech_output.QSoundEffect'),patch('therion.voice.speech_output.QProcess') as factory:
        service=SpeechOutput({'provider':'edge','online_allowed':False})
        try:
            errors=[];service.failed.connect(errors.append)
            service.speak('Teste fictício.')
            factory.assert_not_called()
            assert errors and service._pending is None
        finally:service.release();service.deleteLater();qt.processEvents()


def test_voice_configuration_proposal_preserves_unrelated_settings(tmp_path):
    path=Path(__file__).resolve().parents[1]/'scripts/configure-voice.py'
    spec=importlib.util.spec_from_file_location('configure_voice',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    python=tmp_path/'python.exe';python.write_bytes(b'fixture only')
    original={'ai':{'model':'keep'},'unknown':{'flag':42},'tts':{'voice':'alex_santa_c','python_path':'keep-local'}}
    with pytest.raises(ValueError,match='online'):module.proposal(original,'edge',str(python))
    result=module.proposal(original,'edge',str(python),allow_online=True)
    assert result['ai']==original['ai'] and result['unknown']==original['unknown']
    assert result['tts']['voice']=='alex_santa_c' and original['tts']=={'voice':'alex_santa_c','python_path':'keep-local'}
    disabled=module.proposal(result,None,disable=True)
    assert not disabled['tts']['enabled'] and not disabled['tts']['online_allowed']
