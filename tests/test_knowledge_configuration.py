from datetime import datetime,timedelta,timezone
import json
import pytest
from therion.config.knowledge import configuration_proposal,apply_configuration
from therion.memory.knowledge import MemoryError


def setup(tmp_path):
    path=tmp_path/'config.json'
    original={'ai':{'model':'fictício','think':True},'tts':{'voice':'Alex-fictício'},'extra':{'preserve':[1,2]}}
    path.write_text(json.dumps(original),encoding='utf-8')
    proposal=configuration_proposal(path,tmp_path/'vault','autorização fictícia',
        (datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),read_all=True,supervised_memory=True)
    return path,original,proposal


def test_preview_is_read_only_and_apply_preserves_all_unrelated_fields(tmp_path):
    path,original,proposal=setup(tmp_path)
    before=path.read_bytes()
    assert json.loads(before)==original and len(list(tmp_path.iterdir()))==1
    backup=apply_configuration(proposal,proposal['sha256'])
    from pathlib import Path
    assert Path(backup).read_bytes()==before
    current=json.loads(path.read_bytes())
    assert {k:v for k,v in current.items() if k!='knowledge_access'}==original
    assert current['knowledge_access']['supervised_memory'] is True


@pytest.mark.parametrize('change',['hash','file','expiry'])
def test_changed_or_unreviewed_configuration_cannot_be_applied(tmp_path,change):
    path,_,proposal=setup(tmp_path)
    expected=proposal['sha256']
    if change=='hash':expected='outro'
    if change=='file':path.write_text('{}',encoding='utf-8')
    if change=='expiry':proposal['updated']['knowledge_access']['expires_at']='2000-01-01T00:00:00+00:00'
    before=path.read_bytes()
    with pytest.raises(MemoryError):apply_configuration(proposal,expected)
    assert path.read_bytes()==before
