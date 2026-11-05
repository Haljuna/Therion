"""Regressões com dados fictícios; não acessa microfone, contas ou modelos reais."""
from unittest.mock import MagicMock,patch
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_constellation import app,window,settle
from therion.integrations.mail_text import clean_mail_text

def scene(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    return d

def drag(widget,dx,dy):
    grip=QPoint(12,8)
    QTest.mousePress(widget,Qt.LeftButton,Qt.NoModifier,grip)
    destination=widget.mapToGlobal(grip)+QPoint(dx,dy)
    event=QMouseEvent(QEvent.MouseMove,QPointF(widget.mapFromGlobal(destination)),QPointF(destination),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(widget,event)
    QTest.mouseRelease(widget,Qt.LeftButton,Qt.NoModifier,grip)
    QApplication.processEvents()

def test_clean_reading_hides_angle_link_destinations_without_touching_source():
    source='<https://instagram.example.test/a> <https://facebook.example.test/b>\n\nBoletim <https://example.test/documento?token=segredo> | 27/10/2026\n\nPrazo < 10 dias. Código <ABC123>.'
    result=clean_mail_text(source)
    assert 'https://' not in result['text'] and '<https://' in source
    assert 'Boletim' in result['text'] and '27/10/2026' in result['text']
    assert 'Prazo < 10 dias. Código <ABC123>.' in result['text']
    assert 'endereços de links' in result['reasons']
    assert clean_mail_text('<https://example.test/unico>')['text']==''

def test_drag_resize_and_organize_keep_both_panels_and_draft(window):
    d=scene(window);d.navigate(2);d.workspace.organize(['calendar','tasks'])
    calendar=d.workspace.panels['calendar'];tasks=d.workspace.panels['tasks']
    window._input.setPlainText('Rascunho preservado')
    before=calendar.geometry();drag(calendar.title_bar,-160,24)
    assert calendar.pos()!=before.topLeft() and not tasks.isHidden()
    moved=calendar.geometry();d._arrange_scene();assert calendar.geometry()==moved
    drag(calendar.resize_handle,48,40)
    assert calendar.width()>moved.width() and calendar.height()>moved.height()
    calendar.resize_handle.setFocus();size=calendar.size()
    QTest.keyClick(calendar.resize_handle,Qt.Key_Right)
    assert calendar.width()==size.width()+16
    window.resize(1024,768);QApplication.processEvents();d._arrange_scene()
    assert d.workspace_rect().contains(calendar.geometry())
    window.resize(1440,900);QApplication.processEvents()
    d.organize_button.click();QApplication.processEvents()
    assert not calendar.manually_placed and not tasks.manually_placed
    assert not calendar.geometry().intersects(tasks.geometry())
    assert window._input.toPlainText()=='Rascunho preservado'

@pytest.mark.parametrize('intro_finished_first',[False,True])
def test_greeting_speaks_before_panels_and_summary_never_interrupts_it(window,intro_finished_first):
    from therion.interface.desktop import _CommandWorker
    d=scene(window)
    worker=_CommandWorker(window._orchestrator,'bom dia');window._command_worker=worker
    window._conversation_mode=True;window._processing=True
    speech=MagicMock();window._speech_output=speech
    payload=dict(session=window._orchestrator.session_id,account=window._orchestrator._mailbox.identity(),
                 calendar_account=d.source.identity()[1],greeting='Bom dia, senhor.')
    order=[];speech.speak.side_effect=lambda text:order.append(('speech',text))
    try:
        with patch.object(d,'open_briefing',side_effect=lambda:order.append(('panels',None))):
            window._present_worker(worker,'open_briefing',payload)
        assert order[0][0]=='speech' and order[1][0]=='panels'
        assert not worker.isRunning()  # Não foi necessário executar consultas reais.
        if intro_finished_first:window._conversation_playback_finished()
        window._processing=False
        window._speech_text='Bom dia, senhor. Sua agenda tem dois compromissos.'
        window._conversation_reply()
        if not intro_finished_first:
            assert speech.speak.call_count==1
            window._conversation_playback_finished()
        assert speech.speak.call_count==2
        assert speech.speak.call_args.args[0]=='Sua agenda tem dois compromissos.'
    finally:
        window._briefing_intro=None;window._conversation_mode=False;window._command_worker=None;window._processing=False

def test_stopping_intro_discards_the_automatic_summary(window):
    from therion.interface.desktop import _CommandWorker
    d=scene(window);worker=_CommandWorker(window._orchestrator,'boa noite')
    window._command_worker=worker;window._conversation_mode=True;window._processing=True
    speech=MagicMock();window._speech_output=speech
    window._briefing_intro=dict(worker=worker,greeting='Boa noite, senhor.',active=True,tail=None,stopped=False)
    try:
        window._stop_speech()
        window._speech_text='Boa noite, senhor. Resumo fictício.'
        with patch.object(window,'_conversation_playback_finished'):
            window._conversation_reply()
        speech.speak.assert_not_called()
    finally:
        window._briefing_intro=None;window._conversation_mode=False;window._command_worker=None;window._processing=False

def test_panel_clean_view_hides_links_and_complete_view_preserves_original(window):
    d=scene(window);mail=d.mailbox
    text='Boletim <https://example.test/documento>\n\nPrazo em 28/10/2026.'
    mail.current_body={'text':text}
    mail.read_mode.setCurrentIndex(0);mail._present_body()
    assert '<https://' not in mail.body.toPlainText()
    assert 'Boletim' in mail.body.toPlainText() and '28/10/2026' in mail.body.toPlainText()
    mail.read_mode.setCurrentIndex(1);mail._present_body()
    assert mail.body.toPlainText()==text and mail.current_body['text']==text

def test_opening_another_panel_keeps_the_manual_workspace(window):
    d=scene(window);d.navigate(3);tasks=d.workspace.panels['tasks']
    drag(tasks.title_bar,-160,24);geometry=tasks.geometry()
    tools=d.workspace.open('tools');d._arrange_scene()
    assert not tools.isHidden() and not tasks.isHidden()
    assert tasks.geometry()==geometry
