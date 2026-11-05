from unittest.mock import Mock
import pytest
from therion.integrations.browser import BrowserSession,CONTROL_SELECTOR


def session(text,*,research=True,title='Fonte pública fictícia'):
    browser=BrowserSession.__new__(BrowserSession)
    browser.config={'research':research,'domains':['example.test'],'fixture':True}
    browser.page=Mock();browser.page.url='https://example.test/article';browser.page.title.return_value=title
    body=Mock();body.inner_text.return_value=text
    controls=Mock();controls.count.return_value=0
    browser.page.locator.side_effect=lambda selector:body if selector=='body' else controls
    browser.page.locator('form').evaluate_all.return_value=[]
    browser.sources={'web:1':browser.page.url}
    return browser,body


def test_public_source_is_paged_and_versions_cover_the_entire_text():
    browser,body=session('A'*7000+' Informações finais: PONTE-42')
    first=browser.dispatch('read_source',{'source_id':'web:1'})
    assert first['partial'] and first['next_offset']==6000 and first['id']=='web:1' and first['accessed_at']
    second=browser.dispatch('read_source',{'source_id':'web:1','offset':7000,'limit':128})
    assert 'PONTE-42' in second['text'] and second['version']==first['version'] and second['next_offset'] is None
    browser.page.goto.assert_not_called()
    body.inner_text.return_value+=' Fonte alterada.'
    assert browser.dispatch('read_source',{'source_id':'web:1'})['version']!=first['version']


def test_visual_snapshot_detects_changes_after_the_visible_excerpt():
    browser,body=session('A'*20000+'antes',research=False)
    first=browser.snapshot();body.inner_text.return_value='A'*20000+'depois'
    second=browser.snapshot()
    assert first['text']==second['text'] and first['partial'] and first['version']!=second['version']


def test_blocked_public_page_is_not_published_as_article():
    browser,_=session('Please wait.',title='Just a moment...')
    with pytest.raises(OSError,match='verificação humana'):browser.dispatch('read_source',{'source_id':'web:1'})


@pytest.mark.parametrize('label',['Pay','Confirmar pagamento','Excluir permanentemente','Delete account','Senha','MFA'])
def test_known_out_of_scope_visual_actions_are_rejected(label):
    from therion.integrations.verification import protected_action
    assert protected_action(label)


def test_regular_fixture_confirmation_remains_supported():
    from therion.integrations.verification import protected_action
    assert not protected_action('Confirmar') and not protected_action('Salvar documento')


def test_browser_launch_failure_closes_driver_and_preserves_error(monkeypatch):
    from playwright import sync_api
    engine=Mock();error=OSError('Falha fictícia de dependência nativa')
    engine.chromium.launch.side_effect=error
    manager=Mock();manager.start.return_value=engine
    monkeypatch.setattr(sync_api,'sync_playwright',lambda:manager)
    with pytest.raises(OSError) as caught:BrowserSession({'research':True,'domains':['*']})
    assert caught.value is error
    engine.stop.assert_called_once()
