import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

SPEC=importlib.util.spec_from_file_location('voice_install_assets',Path(__file__).parents[1]/'scripts/voice_gateway/install_assets.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)


@pytest.fixture
def setup(tmp_path):
    source=tmp_path/'source';(source/'omnivoice/models').mkdir(parents=True)
    (source/'omnivoice/models/omnivoice.py').write_text('fixture')
    checkpoint=tmp_path/'weights';checkpoint.mkdir()
    reference=tmp_path/'reference.mp3';reference.write_bytes(b'synthetic fixture')
    profile={'id':'120f734a','ref_text':'Controle ficticio.','reference_path':str(reference),
             'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest()}
    temporary=tmp_path/'trial';temporary.mkdir()
    path=temporary/'profile.json';path.write_text(json.dumps(profile),encoding='utf-8')
    identity=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()+b'fixture'+str(checkpoint.resolve()).encode()).hexdigest()[:32]
    cache=temporary/('reference-'+identity+'.pt');cache.write_bytes(b'fixture cached tensors')
    config=tmp_path/'config.json';config.write_text(json.dumps({'voice':{'provider':'parakeet_http'},
        'tts':{'voicestudio_voice':'120f734a','voicestudio_endpoint':'http://127.0.0.1:3902/v1/audio/speech'},'other':42}))
    state=tmp_path/'permanent'
    return path,source,checkpoint,state,config,reference


def test_adoption_preserves_config_and_first_backup_when_repeated(setup):
    path,source,checkpoint,state,config,_=setup
    before=config.read_bytes()
    manifest=MODULE.install(path,source,checkpoint,state,config)
    assert config.read_bytes()==before
    assert (state/'jarvis/profile.json').read_bytes()==path.read_bytes()
    assert (state/'jarvis'/manifest['reference_cache']).read_bytes()==b'fixture cached tensors'
    data=json.loads(config.read_text());data['other']=43;config.write_text(json.dumps(data))
    MODULE.install(path,source,checkpoint,state,config)
    assert (state/'rollback/config-at-adoption.json').read_bytes()==before
    assert json.loads(config.read_text())['other']==43


def test_changed_reference_is_rejected_before_publishing(setup):
    path,source,checkpoint,state,config,reference=setup
    reference.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Referência'):MODULE.install(path,source,checkpoint,state,config)
    assert not state.exists()


def test_existing_profile_is_not_overwritten_silently(setup):
    path,source,checkpoint,state,config,_=setup
    MODULE.install(path,source,checkpoint,state,config)
    published=state/'jarvis/profile.json';published.write_bytes(b'edited')
    with pytest.raises(ValueError,match='diverge'):MODULE.install(path,source,checkpoint,state,config)
    assert published.read_bytes()==b'edited'
