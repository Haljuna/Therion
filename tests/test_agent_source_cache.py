import pytest
from therion.integrations.documents import DocumentSession


def test_cache_revalidates_version_and_does_not_expose_mutable_result(tmp_path):
    path=tmp_path/'fixture.md';path.write_bytes(b'Aurora')
    session=DocumentSession({'read_roots':[str(tmp_path)],'cache_enabled':True})
    first=session.dispatch('read',{'path':str(path)})
    first['sections'][0]['text']='alteração do consumidor'
    second=session.dispatch('read',{'path':str(path)})
    assert second['cache_hit'] and second['sections'][0]['text']=='Aurora'
    path.write_bytes(b'Lotus')
    current=session.dispatch('read',{'path':str(path)})
    assert not current['cache_hit'] and current['sections'][0]['text']=='Lotus'
    assert len(session.cache)==1
    path.unlink()
    with pytest.raises(OSError):session.dispatch('read',{'path':str(path)})


def test_cache_never_skips_interval_validation(tmp_path):
    path=tmp_path/'fixture.md';path.write_bytes(b'Aurora')
    session=DocumentSession({'read_roots':[str(tmp_path)],'cache_enabled':True})
    session.dispatch('read',{'path':str(path),'offset':1,'limit':128})
    with pytest.raises(ValueError,match='Intervalo'):session.dispatch('read',{'path':str(path),'offset':True,'limit':128})


def test_cache_bounded_disabled_by_default_and_cleared_on_close(tmp_path):
    path=tmp_path/'fixture.md';path.write_bytes(b'Aurora'*3000)
    session=DocumentSession({'read_roots':[str(tmp_path)]})
    assert 'cache_hit' not in session.dispatch('read',{'path':str(path)}) and not session.cache
    session.cache_enabled=True
    for offset in range(20):session.dispatch('read',{'path':str(path),'offset':offset})
    assert len(session.cache)==16
    session.close();assert not session.cache
