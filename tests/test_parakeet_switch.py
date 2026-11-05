import importlib.util
import io
import json
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('parakeet_switch',Path(__file__).parents[1]/'scripts/voice_gateway/switch_therion.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_activate_restore_preserves_unrelated_edits(tmp_path,monkeypatch):
    class Client:
        def open(self,*args,**kwargs):return io.BytesIO(b'{"status":"ready","model":"parakeet"}')
    monkeypatch.setattr(MODULE,'build_opener',lambda *args:Client())
    config=tmp_path/'config.json'
    before={'voice':{'model_path':'original'},'tts':{'voicestudio_voice':'120f734a','voicestudio_endpoint':'http://127.0.0.1:3901/v1/audio/speech'},'ai':{'model':'same'},'extra':42}
    config.write_text(json.dumps(before))
    runtime=tmp_path/'backup'
    assert MODULE.switch('activate',config,runtime)['ai_unchanged']
    data=json.loads(config.read_text())
    assert data['voice']['provider']=='parakeet_http' and data['voice']['model_path']=='original'
    assert data['ai']==before['ai'] and data['extra']==42
    data['extra']=43
    config.write_text(json.dumps(data))
    MODULE.switch('restore',config,runtime)
    expected={**before,'extra':43}
    assert json.loads(config.read_text())==expected
    assert json.loads((runtime/'config-before-parakeet.json').read_text())==before
