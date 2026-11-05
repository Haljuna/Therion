"""Modo de janela com sessão fictícia; sem áudio, rede ou modelos reais."""
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_constellation import app,window,settle


def visible(window,interface='constellation'):
    window._select_interface(interface,persist=False)
    area=window.screen().availableGeometry()
    window.resize(min(1200,area.width()-80),min(760,area.height()-100))
    window.move(area.topLeft()+QPoint(32,48));window.show();window.activateWindow();QApplication.processEvents()
    if window._dashboard:settle(lambda:not window._dashboard.workers)


def finished(window):
    settle(lambda:not window._changing_window_mode)


def test_fullscreen_button_keeps_session_draft_and_open_windows(window):
    visible(window);d=window._dashboard;d.navigate(3)
    panel=d.workspace.panels['tasks'];session=window._orchestrator.session_id
    window._input.setPlainText('Rascunho preservado');before=window.geometry()
    contained=window.screen().availableGeometry().contains(window.frameGeometry())
    with patch.object(window,'_end_conversation') as end,patch.object(window,'_stop_speech') as stop:
        d.fullscreen_button.click();finished(window)
        assert window.isFullScreen() and d.fullscreen_button.isChecked()
        assert window.geometry().size()==window.screen().geometry().size()
        assert d.fullscreen_button.accessibleName()=='Sair da tela cheia'
        d.fullscreen_button.click();finished(window)
        assert not window.isFullScreen() and not d.fullscreen_button.isChecked()
        end.assert_not_called();stop.assert_not_called()
    assert window.size()==before.size()
    if contained:assert window.geometry()==before
    renderer=d.constellation.renderer
    if renderer:
        settle(lambda:renderer.ready or renderer.disabled)
        assert renderer.ready and not renderer.disabled
    assert window._orchestrator.session_id==session
    assert d.workspace.panels['tasks'] is panel and panel.isVisible()
    assert window._input.toPlainText()=='Rascunho preservado'


@pytest.mark.parametrize('interface',['classic','constellation'])
def test_f11_toggles_from_text_input_in_both_interfaces(window,interface):
    visible(window,interface)
    window._input.setFocus();QApplication.processEvents()
    QTest.keyClick(window._input,Qt.Key_F11);finished(window)
    assert window.isFullScreen()
    QTest.keyClick(window._input,Qt.Key_F11);finished(window)
    assert not window.isFullScreen()


def test_leaving_fullscreen_restores_maximized_window(window):
    visible(window);window.showMaximized();QApplication.processEvents()
    assert window.isMaximized()
    window._toggle_full_screen();finished(window);assert window.isFullScreen()
    window._toggle_full_screen();finished(window)
    assert window.isMaximized() and not window.isFullScreen()


def test_changing_interface_during_fullscreen_keeps_exit_control(window):
    visible(window,'classic');window._fullscreen_button.click();finished(window)
    window._select_interface('constellation',persist=False);QApplication.processEvents()
    assert window.isFullScreen() and window._dashboard.fullscreen_button.isChecked()
    window._dashboard.fullscreen_button.click();finished(window)
    assert not window.isFullScreen()


def test_minimizing_fullscreen_keeps_voice_and_fullscreen_state(window):
    visible(window);window._toggle_full_screen();finished(window)
    with patch.object(window,'_end_conversation') as end,patch.object(window,'_stop_speech') as stop:
        window._minimize_window();QApplication.processEvents()
        assert window.isMinimized()
        window._show_window();QApplication.processEvents()
        assert not window.isMinimized() and window.isFullScreen()
        end.assert_not_called();stop.assert_not_called()
    window._toggle_full_screen();finished(window)
