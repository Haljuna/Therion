"""Conteúdo real em janelas internas; fontes, configurações e arquivos fictícios."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from PySide6.QtCore import QTimer,QPoint,Qt
from PySide6.QtWidgets import QApplication,QDialog as NativeDialog,QMessageBox as NativeMessageBox
from tests.test_constellation import app,window,settle
from therion.interface.surface_dialogs import Dialog,MessageBox,InputDialog,FileDialog


def scene(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    return d


def respond(d,callback):
    errors=[]
    def run():
        try:
            assert d.surfaces.modals,'A pergunta saiu do painel.'
            dialog,layer,_=d.surfaces.modals[-1]
            assert not dialog.isWindow() and layer.parentWidget() is d
            assert layer.geometry()==d.rect()
            callback(dialog)
        except BaseException as error:
            errors.append(error)
            if d.surfaces.modals:d.surfaces.modals[-1][0].reject()
            else:
                active=QApplication.activeModalWidget()
                if active:active.reject()
    QTimer.singleShot(0,run)
    return errors


def test_capabilities_history_proposals_and_procedures_use_one_canvas(window):
    d=scene(window);session=window._orchestrator.session_id
    window._input.setPlainText('Rascunho preservado')
    with patch.object(NativeDialog,'exec',side_effect=AssertionError('Diálogo externo')):
        window._agent_button.click()
        panel=window._agent_panel
        assert panel.owner is window and not panel.isWindow()
        assert panel is d.surfaces.views['capabilities']
        assert panel.tabs.currentIndex()==0
        d.agent_tab(1);assert panel.tabs.currentIndex()==1
        d.agent_tab(2);assert panel.tabs.currentIndex()==2
        shell=d.workspace.panels['capabilities'];shell.dismiss();d.agent_tab(0)
        assert window._agent_panel is panel and not shell.isHidden()
        panel.show_procedures()
        assert 'procedures' in d.workspace.visible_keys()
        assert not d.surfaces.views['procedures'].isWindow()
    assert window._orchestrator.session_id==session
    assert window._input.toPlainText()=='Rascunho preservado'
    window._agent_config_writer.assert_not_called()
    assert not any(isinstance(w,NativeDialog) and w.isVisible() for w in QApplication.topLevelWidgets())


def test_capabilities_keep_owner_and_preferences_after_reparenting(window):
    d=scene(window)
    saved=deepcopy(window._config);saved['unknown']={'preserve':True}
    window._agent_config_loader=lambda:deepcopy(saved)
    panel=d.open_agent()
    panel.checks['history_enabled'].setChecked(True)
    panel.save()
    updated=window._agent_config_writer.call_args.args[0]
    assert updated['unknown']=={'preserve':True} and updated['agent']['history_enabled'] is True
    assert panel.owner is window and panel.parentWidget() is not window
    assert window._orchestrator._agent_config['history_enabled'] is True


@pytest.mark.parametrize('decision',[MessageBox.Yes,MessageBox.No])
def test_confirmation_is_internal_and_returns_only_clicked_decision(window,decision):
    d=scene(window);effects=[]
    window._input.setFocus();QApplication.processEvents()
    def click(box):
        assert box.defaultButton() is box.button(MessageBox.No)
        assert not window._send_button.isEnabled() and not d.find_shortcut.isEnabled()
        box.button(decision).click()
    errors=respond(d,click)
    answer=MessageBox.question(window,'Exemplo fictício','Confirmar esta alteração fictícia?')
    if answer==MessageBox.Yes:effects.append('confirmed')
    assert not errors and answer==decision
    assert effects==(['confirmed'] if decision==MessageBox.Yes else [])
    assert not d.surfaces.modals and QApplication.activeModalWidget() is None
    assert window._send_button.isEnabled() and d.find_shortcut.isEnabled()
    assert QApplication.focusWidget() is window._input


def test_input_and_file_selection_stay_inside_the_scene(window,tmp_path):
    d=scene(window)
    errors=respond(d,lambda dialog:(dialog.setTextValue('Título fictício'),dialog.accept()))
    assert InputDialog.getText(window,'Criar tarefa','Título:')==('Título fictício',True)
    assert not errors
    file=tmp_path/'example.txt';file.write_text('Somente fixture',encoding='utf-8')
    errors=respond(d,lambda dialog:(dialog.selectFile(str(file)),dialog.accept()))
    selected,_=FileDialog.getOpenFileName(window,'Escolher exemplo',str(tmp_path),'Texto (*.txt)')
    assert not errors and selected.replace('\\','/')==file.as_posix()
    assert not d.surfaces.modals


def test_nested_confirmation_and_shutdown_cancel_internal_dialogs(window):
    d=scene(window);outer=Dialog(window);outer.setWindowTitle('Formulário fictício')
    def nested(dialog):
        errors=respond(d,lambda box:box.button(MessageBox.No).click())
        assert MessageBox.question(dialog,'Confirmação','Exemplo?')==MessageBox.No
        assert not errors and len(d.surfaces.modals)==1
        d.surfaces.cancel()
    errors=respond(d,nested)
    assert outer.exec()==Dialog.Rejected
    assert not errors and not d.surfaces.modals


def test_declining_overwrite_keeps_file_picker_open_and_returns_no_path(window,tmp_path):
    d=scene(window);file=tmp_path/'existing.txt';file.write_text('Preservar',encoding='utf-8')
    def choose(dialog):
        dialog.selectFile(str(file))
        errors=respond(d,lambda box:box.button(MessageBox.No).click())
        dialog.accept()
        assert not errors and len(d.surfaces.modals)==1
        dialog.reject()
    errors=respond(d,choose)
    selected,_=FileDialog.getSaveFileName(window,'Salvar exemplo',str(tmp_path),'Texto (*.txt)')
    assert not errors and selected==''
    assert file.read_text(encoding='utf-8')=='Preservar' and not d.surfaces.modals


def test_default_config_opens_new_interface_and_explicit_classic_remains_supported(app,tmp_path):
    from therion.config.local import _validate_config
    from therion.interface.desktop import MainWindow
    config=_validate_config({})
    assert config['ui']['interface']=='constellation'
    assert _validate_config({'ui':{'interface':'classic'}})['ui']['interface']=='classic'
    with patch.object(MainWindow,'_setup_tray'):
        w=MainWindow(app,config,config_writer=lambda data:None,log_dir=tmp_path/'logs')
    try:
        assert w._dashboard.active and w._interface_stack.currentWidget() is w._dashboard_scroll
        settle(lambda:not w._dashboard.workers)
    finally:
        w._dashboard.cancel();w._closing=True;w.close();QApplication.processEvents()
