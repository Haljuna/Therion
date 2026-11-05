"""Acceptance tests for presentation only, with fictitious data and no audio devices."""
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLabel
from tests.test_constellation import app,window,settle
from therion.interface.design_system import COLORS,history_html

def show(window,size=(1440,900)):
    window._select_interface('constellation',persist=False)
    window.resize(*size);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    return d

def luminance(color):
    values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(a*b for a,b in zip(values,(.2126,.7152,.0722)))

@pytest.mark.parametrize('foreground',['text','muted','accent','danger','warning','success'])
@pytest.mark.parametrize('background',['background','surface'])
def test_normal_text_palette_meets_wcag_aa(foreground,background):
    light,dark=sorted([luminance(COLORS[foreground]),luminance(COLORS[background])],reverse=True)
    assert (light+.05)/(dark+.05)>=4.5

def test_history_theme_keeps_message_literals_and_markup_escaped():
    message='<span style="color:#fb923c;font-size:13px;">color:#fb923c &lt;script&gt;</span>'
    result=history_html(message)
    assert 'style="color:#C4B5FD;font-size:14px;"' in result
    assert '>color:#fb923c &lt;script&gt;</span>' in result

@pytest.mark.parametrize('size,expanded',[((1440,900),True),((1199,800),False),((1024,768),False),((960,640),False)])
def test_layout_keeps_composer_and_panels_accessible(window,size,expanded):
    d=show(window,size);d.navigate(1);QApplication.processEvents();d._arrange_scene()
    assert (d.nav.width()==192)==expanded
    assert d.rect().contains(d.composer.geometry())
    assert d.rect().contains(d.control_bar.geometry())
    panel=d.workspace.panels['conversations']
    assert d.panel_opening_rect().contains(panel.geometry())
    assert panel.geometry().bottom()<d.composer.y()
    assert panel.x()>d.nav.geometry().right()
    window._input.setPlainText('Linha um\nLinha dois\nLinha três\nLinha quatro')
    QApplication.processEvents();d._arrange_scene()
    assert window._input.height()>40 and d.rect().contains(d.composer.geometry())
    assert panel.geometry().bottom()<d.composer.y()

def test_reading_position_is_preserved_when_a_new_reply_arrives(window):
    d=show(window);d.navigate(1)
    for i in range(35):window._append('Therion',f'Resposta fictícia {i}\n'+'Conteúdo para leitura. '*12)
    QApplication.processEvents()
    bar=window._history.verticalScrollBar();assert bar.maximum()>100
    bar.setValue(20);window._append('Therion','Uma nova resposta chegou.')
    QApplication.processEvents();assert bar.value()==20
    d.latest_button.click();assert bar.value()==bar.maximum()

def test_nested_details_return_to_the_previous_view_without_losing_draft(window):
    d=show(window);d.navigate(3)
    window._input.setPlainText('Rascunho fictício')
    for key in ('detail-a','detail-b'):
        d.workspace.register(key,key,QLabel('Detalhe fictício'))
        d.workspace.open(key);QApplication.processEvents()
    d.workspace.panels['detail-b'].dismiss()
    assert not d.workspace.panels['detail-a'].isHidden()
    d.workspace.panels['detail-a'].dismiss()
    assert d.workspace.visible_keys()==['tasks']
    assert window._input.toPlainText()=='Rascunho fictício'

def test_renderer_failure_keeps_static_presence_and_text_controls(window):
    d=show(window)
    d.constellation._failed('Renderização indisponível neste teste')
    QApplication.processEvents()
    assert d.constellation.stack.currentWidget() is d.constellation.still
    assert d.constellation.notice.isVisible()
    assert window._input.isVisible() and window._send_button.isVisible()

def test_session_browser_is_collapsible_and_keeps_the_conversation(window):
    d=show(window);d.navigate(1)
    window._append('Therion','Conversa fictícia preservada')
    draft='Rascunho antes de consultar sessões'
    window._input.setPlainText(draft)
    text=window._history.toPlainText()
    d.sessions_toggle.click();QApplication.processEvents()
    assert 'sessions' in d.workspace.visible_keys()
    view=d.surfaces.views['sessions']
    assert view.tabs.count()==1 and view.tabs.tabBar().isHidden()
    settle(lambda:d.workspace.panels['sessions'].content.horizontalScrollBar().maximum()==0)
    d.workspace.panels['sessions'].dismiss()
    assert d.workspace.visible_keys()==['conversations']
    assert window._history.toPlainText()==text and window._input.toPlainText()==draft
    assert not d.sessions_toggle.isChecked()

def test_voice_controls_keep_the_existing_handlers_without_starting_audio(window):
    d=show(window)
    with patch.object(window,'_voice_pipeline') as pipeline:
        # Visual state consumes already measured levels only.
        for state in ('preparing','listening','transcribing','thinking','executing','speaking','error'):
            d.constellation.set_visual(state,.4)
        pipeline.start.assert_not_called()
    session=window._orchestrator.session_id
    window._input.setPlainText('Pedido fictício')
    window._select_interface('classic',persist=False)
    window._select_interface('constellation',persist=False)
    assert window._input.toPlainText()=='Pedido fictício'
    assert window._orchestrator.session_id==session
