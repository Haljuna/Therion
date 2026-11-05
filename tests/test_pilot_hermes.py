"""O piloto precisa manter configurações e fontes dentro da fixture."""
import importlib.util
import os
from pathlib import Path
import pytest


def test_pilot_does_not_load_personal_config_or_enable_accounts(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'pilot-hermes.py'
    spec = importlib.util.spec_from_file_location('pilot_hermes', path)
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    monkeypatch.setenv('THERION_TEST_ROOT', str(tmp_path))
    # prepare altera apenas o ambiente do processo de teste; restaurá-lo depois.
    for name in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, os.environ.get(name, ''))
    root, vault, config_path, config = pilot.prepare('fixture-model')
    assert root.is_relative_to(tmp_path) and config_path.is_relative_to(root)
    assert config['ai']['model'] == 'fixture-model'
    assert config['agent']['enabled'] is True
    assert config['agent']['documents_enabled'] is True
    assert not config['agent']['history_enabled']
    for capability in ('gmail_enabled', 'browser_enabled', 'desktop_enabled', 'web_enabled', 'mcp_enabled'):
        assert not config['agent'][capability]
    assert config['tts']['enabled'] is False
    assert config['calendar']['enabled'] is False
    assert config['runtime']['real_actions_enabled'] is False
    assert config['knowledge_access']['supervised_memory'] is False
    for variable in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        assert Path(os.environ[variable]).is_relative_to(root)
    assert (vault / '10 - Projetos' / 'Therion' / 'Aurora.md').is_file()
    assert all(Path(value).is_relative_to(root) for value in config['agent']['document_write_roots'])


def test_voice_pilot_uses_explicit_local_files_and_keeps_accounts_off(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('pilot_voice',Path(__file__).resolve().parents[1]/'scripts/pilot-hermes.py')
    pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
    monkeypatch.setenv('THERION_TEST_ROOT',str(tmp_path))
    for name in ('APPDATA','LOCALAPPDATA','TEMP','TMP','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE'):
        monkeypatch.setenv(name,os.environ.get(name,''))
    python=tmp_path/'python.exe';python.write_bytes(b'fixture')
    tts=tmp_path/'tts';tts.mkdir();stt=tmp_path/'stt';stt.mkdir()
    for name in ('kokoro-v1.0.onnx','voices-v1.0.bin'):(tts/name).write_bytes(b'fixture')
    for name in ('config.json','model.bin','tokenizer.json','vocabulary.txt'):(stt/name).write_bytes(b'fixture')
    root,_,_,config=pilot.prepare('fixture',voice_python=python,voice_root=tts,stt_model=stt,streaming_voice=True)
    assert config['tts']['provider']=='kokoro' and config['tts']['voice']=='alex_santa_c'
    assert config['tts']['streaming_prepare'] is True and config['tts']['online_allowed'] is False
    assert config['voice']['model_path']==str(stt)
    assert os.environ['HF_HUB_OFFLINE']=='1'
    assert not config['agent']['history_enabled'] and not config['agent']['gmail_enabled']
    assert not config['runtime']['real_actions_enabled']
    stt.joinpath('tokenizer.json').unlink()
    with pytest.raises(ValueError,match='ausentes'):
        pilot.prepare('fixture',voice_python=python,voice_root=tts,stt_model=stt)


def test_partial_voice_options_do_not_create_state(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('pilot_invalid_voice',Path(__file__).resolve().parents[1]/'scripts/pilot-hermes.py')
    pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
    monkeypatch.setenv('THERION_TEST_ROOT',str(tmp_path))
    for args in ({'streaming_voice':True},{'voice_python':tmp_path/'python.exe'}):
        with pytest.raises(ValueError):pilot.prepare('fixture',**args)
    assert not list(tmp_path.iterdir())


def test_voice_pilot_window_does_not_start_capture_or_speech(tmp_path):
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    from therion.config.local import _validate_config
    app=QApplication.instance() or QApplication([])
    config=_validate_config({'tts':{'enabled':True,'provider':'kokoro','voice':'alex_santa_c',
        'warm_on_start':False,'streaming_prepare':True},'voice':{'model_path':str(tmp_path/'stt')}})
    vault=tmp_path/'vault';vault.mkdir()
    with patch('therion.voice.capture.AudioCaptureService.start',return_value=False) as capture, \
         patch('therion.voice.speech_output.SpeechOutput.speak') as speak:
        window=MainWindow(app,config,knowledge_runtime=KnowledgeRuntime(vault,tmp_path/'memory',lambda:config),
            config_loader=lambda:config,log_dir=str(tmp_path/'logs'))
        try:
            window.show();QTest.qWait(1100)
            capture.assert_not_called();speak.assert_not_called()
            assert not window._conversation_mode and window._voice_pipeline is None
        finally:
            window._orchestrator.close();window._speech_output.shutdown()
            window.deleteLater();app.processEvents()
