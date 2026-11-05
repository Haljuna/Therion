"""Chromium próprio em página local fictícia; nenhum perfil pessoal."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import pytest
from therion.agent.contracts import CancellationToken
from therion.integrations.rpc import OwnedWorker


@pytest.fixture
def page_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=(b'<html><body><form action="/payment"><input autocomplete="cc-number" name="cardnumber" value="4111111111111111"><button>Confirmar</button></form></body></html>' if self.path=='/protected' else
                b'<html><body><form action="/save" method="post"><input type="hidden" name="version" value="initial-private-value"><input name="subject" placeholder="Assunto" value="Aurora"><button>Salvar</button></form></body></html>' if self.path=='/form' else
                b'<html><body><h1>Aurora fixture</h1><input placeholder="Nome"><button onclick="document.querySelector(\'h1\').textContent=\'Confirmado\'">Confirmar</button></body></html>')
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown();server.server_close();thread.join(timeout=2)


def test_protected_card_fields_are_masked_and_never_filled(tmp_path,page_server):
    import json
    worker=OwnedWorker('browser',{'profile':str(tmp_path/'browser'),'domains':['127.0.0.1'],'fixture':True})
    token=CancellationToken()
    try:
        first=worker.call('open',{'url':page_server+'/protected'},token)
        assert '4111111111111111' not in json.dumps(first) and first['forms'][0]['protected']
        edit=next(row for row in first['controls'] if row['tag']=='input')
        assert edit['protected'] and edit['value']=='<protegido>'
        with pytest.raises(ValueError,match='manual'):
            worker.call('fill',{'control_id':edit['id'],'version':first['version'],'text':'nunca preencher'},token)
    finally:worker.close()


def test_visible_edge_uses_own_profile_and_verifies_fixture_click(tmp_path,page_server):
    from pathlib import Path
    if not Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe').is_file():pytest.skip('Edge não instalado; canal opcional.')
    profile=tmp_path/'therion-edge-fixture'
    worker=OwnedWorker('browser',{'profile':str(profile),'domains':['127.0.0.1'],'fixture':True,'visible':True,'channel':'msedge'})
    token=CancellationToken()
    try:
        first=worker.call('open',{'url':page_server},token)
        button=next(row for row in first['controls'] if row['tag']=='button')
        result=worker.call('click',{'control_id':button['id'],'version':first['version'],
            'expect':{'kind':'text_present','value':'Confirmado'}},token)
        assert result['action_observed'] and 'Confirmado' in result['text'] and profile.is_dir()
    finally:worker.close()


def test_owned_browser_scope_drift_and_verified_result(tmp_path,page_server):
    worker=OwnedWorker('browser',{'profile':str(tmp_path/'browser'),'domains':['127.0.0.1'],'fixture':True})
    token=CancellationToken()
    try:
        first=worker.call('open',{'url':page_server},token)
        assert 'Aurora fixture' in first['text']
        edit=next(item for item in first['controls'] if item['tag']=='input')
        filled=worker.call('fill',{'control_id':edit['id'],'version':first['version'],'text':'Teste'},token)
        assert filled['version']!=first['version']
        with pytest.raises(ValueError,match='mudou'):
            worker.call('click',{'control_id':'1','version':first['version']},token)
        current=worker.call('read',{},token)
        button=next(item for item in current['controls'] if item['tag']=='button')
        clicked=worker.call('click',{'control_id':button['id'],'version':current['version'],'expect':{'kind':'text_present','value':'Confirmado'}},token)
        assert 'Confirmado' in clicked['text']
        assert clicked['action_observed'] is True
        with pytest.raises(ValueError,match='escopo'):
            worker.call('open',{'url':'https://example.test'},token)
    finally:
        worker.close()
    assert worker.process is None


def test_hidden_form_change_invalidates_preview_without_exposing_tokens(tmp_path,page_server):
    import json
    from therion.integrations.browser import BrowserSession
    session=BrowserSession({'profile':str(tmp_path/'browser'),'domains':['127.0.0.1'],'fixture':True})
    try:
        before=session.dispatch('open',{'url':page_server+'/form'})
        assert 'initial-private-value' not in json.dumps(before)
        assert all(row['tag']!='input' or row['text']=='Assunto' for row in before['controls'])
        session.page.locator('input[type=hidden]').evaluate('(element)=>element.value="changed-private-value"')
        after=session.snapshot()
        assert before['text']==after['text'] and before['version']!=after['version']
        assert 'changed-private-value' not in json.dumps(after)
        button=next(row for row in before['controls'] if row['tag']=='button')
        with pytest.raises(ValueError,match='mudou'):
            session.dispatch('click',{'control_id':button['id'],'version':before['version'],'expect':{'kind':'text_present','value':'Concluído'}})
    finally:session.close()


def test_registered_browser_action_requires_visual_approval_and_verifies_page(tmp_path,page_server,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from therion.agent.contracts import ToolCall
    from therion.agent.proposals import ActionProposals
    from therion.agent.registry import ToolRegistry
    from therion.agent.store import SessionStore
    from therion.integrations.visual_tools import register_visual_tools
    class FixtureWorker(OwnedWorker):
        def __init__(self,kind,config):super().__init__(kind,dict(config,fixture=True))
    monkeypatch.setattr('therion.integrations.visual_tools.OwnedWorker',FixtureWorker)
    store=SessionStore(tmp_path/'state.sqlite3');proposals=ActionProposals(store,lambda:'fixture')
    host=SimpleNamespace(_agent_config={'browser_enabled':True,'browser_domains':['127.0.0.1']},_agent_root=tmp_path,
        _agent_proposals=proposals,_agent_workers={})
    registry=ToolRegistry();register_visual_tools(registry,host)
    async def call(name,args):
        spec,blocked=registry.prepare(ToolCall(name,args));assert blocked is None
        return await spec.handler(args,CancellationToken())
    async def scenario():
        opened=await call('browser_open',{'url':page_server})
        button=next(row for row in opened.data['controls'] if row['tag']=='button')
        prepared=await call('browser_prepare_action',{'control_id':button['id'],'version':opened.data['version'],
            'operation':'click','text':'','expect':{'kind':'text_present','value':'Confirmado'}})
        assert prepared.status=='awaiting_confirmation'
        before=await call('browser_read',{});assert 'Confirmado' not in before.data['text']
        row=proposals.list()[0]
        approved=await asyncio.to_thread(proposals.approve_visual,row.id,row.digest,CancellationToken())
        assert approved.status=='success' and approved.side_effect_state=='verified'
        after=await call('browser_read',{});assert 'Confirmado' in after.data['text']
        assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked'
    try:asyncio.run(scenario())
    finally:
        for worker in host._agent_workers.values():worker.close()
