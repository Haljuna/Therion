"""Painel real Qt com conversa fictícia, sem perfil ou conta pessoal."""
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QApplication
from therion.core.orchestrator import Orchestrator
from therion.interface.agent_panel import AgentPanel


def test_generated_artifact_open_rechecks_version_and_capability(tmp_path,monkeypatch):
    from therion.integrations.documents import DocumentAdapter
    import therion.interface.agent_panel as module
    qt=QApplication.instance() or QApplication([])
    host=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'documents_enabled':True,'document_write_roots':[str(tmp_path)]},agent_state_root=tmp_path/'state')
    panel=AgentPanel(host,{},lambda *args:None);opened=[];warnings=[]
    monkeypatch.setattr(module.QDesktopServices,'openUrl',lambda url:opened.append(url.toLocalFile()) or True)
    monkeypatch.setattr(module.QMessageBox,'warning',lambda *args:warnings.append(args[-1]))
    try:
        path=tmp_path/'generated.md';result=DocumentAdapter((),[tmp_path]).write(path,'Resultado fictício',None)
        panel.last_artifact={'path':str(path),'version':result['version']}
        assert panel.open_generated_artifact() and [Path(value) for value in opened]==[path]
        path.write_text('Versão alterada',encoding='utf-8')
        assert not panel.open_generated_artifact() and len(opened)==1
        host._agent_config['documents_enabled']=False
        assert not panel.open_generated_artifact() and len(opened)==1 and len(warnings)==2
    finally:panel.close();host.close();qt.processEvents()


def test_history_panel_search_dates_reopen_and_profiles(tmp_path):
    qt=QApplication.instance() or QApplication([])
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'history_enabled':True},agent_state_root=tmp_path/'state')
    panel=None
    try:
        store=host._get_agent_store();identifier=store.append('fixture-session','user','Aurora PONTE-42')
        store.append('fixture-session','assistant','Resposta fictícia autorizada.')
        panel=AgentPanel(host,{'agent':{'history_enabled':True}},lambda *args:None)
        assert not panel.checks['enabled'].isChecked()
        assert panel.thinking.currentIndex()==0 and panel.context_tokens.value()==8192
        assert panel.browser_channel.currentData()=='chromium'
        assert panel.output_tokens.value()==2048
        panel.history_query.setText('Aurora');panel.search_history()
        preview=panel.preview.toPlainText()
        assert 'PONTE-42' in preview and 'Mensagem '+str(identifier) in preview
        assert str(datetime.now().year) in preview
        panel.list.setCurrentRow(0);panel.reopen()
        assert host.session_id=='fixture-session'
        assert [row.text for row in host.memory.turns]==['Aurora PONTE-42','Resposta fictícia autorizada.']
        assert host._confirmation_id is None
    finally:
        if panel is not None:panel.deleteLater();qt.processEvents()
        host.close()


def test_visual_approval_preserves_active_foreground_turn(tmp_path,monkeypatch):
    import time
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PySide6.QtWidgets import QWidget,QMessageBox
    from therion.agent.proposals import ActionProposals
    qt=QApplication.instance() or QApplication([])
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),agent_state_root=tmp_path/'state')
    store=host._get_agent_store();host._agent_proposals=ActionProposals(store,lambda:host.session_id)
    effects=[];row=host._agent_proposals.prepare('fixture.write',{},'Conteúdo fictício',lambda _:effects.append(1) or {'id':'fixture'},lambda *args:True,lambda *args:True)
    host._agent_runtime=SimpleNamespace(active=True,waiting_confirmation=True,cancel=lambda:None)
    parent=QWidget();parent._processing=True;parent._command_worker=object()
    parent._end_conversation=Mock();parent._append=Mock();parent._set_processing=lambda value:setattr(parent,'_processing',value)
    panel=AgentPanel(host,{},lambda *args:None,parent)
    monkeypatch.setattr(QMessageBox,'exec',lambda _:QMessageBox.Yes)
    try:
        panel.proposal_list.setCurrentRow(0);panel.approve()
        deadline=time.monotonic()+5
        while panel.approval_worker is not None and time.monotonic()<deadline:qt.processEvents();time.sleep(.005)
        assert panel.approval_worker is None and effects==[1]
        assert parent._processing is True
        parent._end_conversation.assert_not_called()
        assert not host.memory.turns
    finally:
        panel.proposal_timer.stop();panel.deleteLater();parent.deleteLater();qt.processEvents();host.close()
