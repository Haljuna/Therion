"""Redesign: leitura e navegação com serviços e contas exclusivamente fictícios."""
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtCore import QPoint,Qt,QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_constellation import app,window,settle
from tests.test_mailbox_panel import mailbox,ready
from therion.agent.briefing import briefing_command,BriefingMarker,mail_since,collect,acknowledge
from therion.agent.contracts import CancellationToken,Cancelled


@pytest.mark.parametrize('text',['Bom dia','Boa tarde, Therion!','Therion, boa noite.',
    'Mostre meu panorama','mostra o panorama do dia'])
def test_explicit_greetings_and_panorama(text):assert briefing_command(text)


@pytest.mark.parametrize('text',['não abra meu panorama','bom dia, apague um e-mail',
    'o e-mail diz bom dia','como responder boa tarde','mostra meus e-mails'])
def test_other_commands_are_not_greetings(text):assert briefing_command(text) is None


def test_new_mail_count_paginates_and_is_not_unread(mailbox):
    host,client=mailbox;account=host._mailbox.identity();cutoff=1792843200000
    marker=BriefingMarker(host._agent_root,account);marker.write(cutoff-5*3600000)
    result=mail_since(host,CancellationToken(),cutoff)
    assert result['complete'] and result['count']==5
    assert any(call[:3]==('search',f'in:inbox after:{(cutoff-5*3600000)//1000-1} before:{cutoff//1000+1}','page-2') for call in client.calls)
    assert marker.read()==cutoff-5*3600000
    assert not any(call[0]=='thread' for call in client.calls)


def test_first_marker_only_committed_after_display_ack(mailbox):
    host,client=mailbox;token=CancellationToken();events=[]
    result=collect(host,'bom dia',token,lambda action,payload:events.append(action))
    marker=BriefingMarker(host._agent_root,host._mailbox.identity())
    assert result['parts']['mail']['first'] and marker.read() is None
    assert events[0]=='open_briefing' and events.count('briefing_part')==3
    assert acknowledge(host,result['candidate']) is True
    assert marker.read()==result['parts']['mail']['cutoff_ms']
    assert acknowledge(host,result['candidate']) is False
    assert set(__import__('json').loads(marker.path.read_text()))=={'version','cutoff_ms'}


def test_cancel_and_account_change_cannot_commit_marker(mailbox):
    host,client=mailbox;token=CancellationToken();token.cancel()
    with pytest.raises(Cancelled):collect(host,'boa tarde',token)
    result=collect(host,'boa tarde',CancellationToken())
    host._agent_config['gmail_enabled']=False
    assert acknowledge(host,result['candidate']) is False


def test_corrupt_marker_is_preserved(mailbox):
    host,_=mailbox;marker=BriefingMarker(host._agent_root,host._mailbox.identity())
    marker.root.mkdir(parents=True);marker.path.write_text('invalid',encoding='utf-8')
    result=collect(host,'bom dia',CancellationToken())
    assert result['parts']['mail']['state']=='error'
    assert not acknowledge(host,result['candidate']) and marker.path.read_text()=='invalid'


def test_partial_count_never_advances_marker(mailbox):
    host,client=mailbox;cutoff=1792843200000;marker=BriefingMarker(host._agent_root,host._mailbox.identity())
    marker.write(cutoff-10*3600000);original=client.search
    def fail(query,page=None):
        if page:raise OSError('Falha fictícia')
        return original(query,page)
    client.search=fail
    result=mail_since(host,CancellationToken(),cutoff)
    assert result['state']=='partial' and not result['complete']
    assert marker.read()==cutoff-10*3600000


def test_greeting_skips_model_and_returns_structured_ui(mailbox):
    host,_=mailbox
    with patch.object(host,'_dispatch_agent',side_effect=AssertionError('Não chamar modelo')):
        result=host.process_session_command('boa noite',host.session_id,host.confirmation_id)
    assert result.ui_action=='open_briefing' and result.status=='success'
    assert set(result.ui_payload['parts'])=={'calendar','tasks','mail'}


def test_window_states_navigation_and_resize(window):
    window._select_interface('constellation',persist=False);window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    assert d.nav.width()==192 and d.activity_dock.isHidden()
    d.toggle_navigation();assert d.nav.width()==64
    d.toggle_navigation();panel=d.workspace.open('tasks');before=panel.geometry()
    from PySide6.QtTest import QTest
    QTest.keyClick(panel.resize_handle,Qt.Key_Left)
    assert panel.width()==before.width()-16 and panel.manually_placed
    panel.minimize();assert panel.window_state=='minimized' and panel.isHidden()
    d.workspace.open('tasks');assert panel.window_state=='open'
    panel.dismiss();assert panel.window_state=='closed'


def test_scene_repositions_and_returns_without_changing_session(window):
    window._select_interface('constellation',persist=False);window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers);session=window._orchestrator.session_id
    original=d._orb_target;d.navigate(6)
    assert d.workspace_presentation.visible_windows==('settings',) and d._orb_target!=original
    settle(lambda:d.orb_transition.state()==d.orb_transition.State.Stopped)
    assert d.constellation.focus_rect==d._orb_target
    d.navigate(0);settle(lambda:d.orb_transition.state()==d.orb_transition.State.Stopped)
    assert d._orb_target==original and session==window._orchestrator.session_id


def test_manual_resize_and_compact_window_recovery(window):
    window._select_interface('constellation',persist=False);window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;panel=d.workspace.open('tasks');area=d.panel_opening_rect()
    panel.place(QRect(area.x(),area.y(),area.width()//2,area.height()),manual=True)
    d._arrange_scene();assert panel.width()==area.width()//2
    d.workspace.open('calendar');d.workspace.organize();window.resize(960,640);QApplication.processEvents()
    d.workspace.organize(['calendar','tasks'])
    assert len(d.workspace.visible_keys())==1 and d.workspace.panels['calendar'].isHidden()


def test_compact_email_switches_list_and_reader(window):
    d,_=ready(window);d.open_mail('m2');settle(lambda:not d.mailbox.busy)
    assert d.mailbox.list.isVisible() and d.mailbox.body.isVisible()
    panel=d.workspace.panels['mail'];panel.resize(700,650);QApplication.processEvents()
    mail=d.mailbox;assert mail.compact
    assert mail.reader_page.isVisible() and mail.list_page.isHidden()
    mail.back.click();assert mail.list_page.isVisible() and mail.reader_page.isHidden()
    mail.select_row(0);assert mail.reader_page.isVisible() and mail.list_page.isHidden()


def test_typed_greeting_opens_organized_panels_without_starting_microphone(window):
    d,_=ready(window);window._input.setPlainText('bom dia');window._send_command()
    settle(lambda:window._command_worker is None and not window._processing,timeout=15)
    assert set(d.workspace.visible_keys())=={'calendar','mail'}
    assert d.workspace.panels['tasks'].window_state=='minimized'
    assert not window._conversation_mode
    assert 'acompanhamento' in window._speech_text


def test_compact_search_returns_to_list_and_fits_viewport(window):
    d,_=ready(window);window.resize(960,640);d.open_mail('m2')
    d.workspace.organize(['mail']);settle(lambda:not d.mailbox.busy)
    mail=d.mailbox;assert mail.compact and mail.reader_page.isVisible()
    viewport=d.workspace.panels['mail'].content.viewport()
    assert mail.height()<=viewport.height()
    mail.search_field.setText('projeto');mail.search();settle(lambda:not mail.busy)
    assert mail.list_page.isVisible() and mail.reader_page.isHidden()


def test_late_briefing_payload_of_other_account_is_not_presented(window):
    from therion.core.orchestrator import OrchestrationResult
    d,_=ready(window);host=window._orchestrator
    payload=collect(host,'bom dia',CancellationToken())
    host._agent_config['gmail_enabled']=False;d.workspace.hide_all()
    window._apply_command_result(OrchestrationResult(status='success',ui_action='open_briefing',ui_payload=payload,message='CONTEÚDO ANTIGO'))
    assert not d.workspace.visible_keys() and 'CONTEÚDO ANTIGO' not in window._history.toPlainText()


def test_reduced_motion_stops_workspace_transition(window):
    window._select_interface('constellation',persist=False);window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;d.navigate(6);d.reduced.setChecked(True);d._arrange_scene()
    assert d.orb_transition.state()==d.orb_transition.State.Stopped
    assert d.constellation.focus_rect==d._orb_target


def test_revoked_source_does_not_reuse_last_snapshot(window):
    window._select_interface('constellation',persist=False);d=window._dashboard;settle(lambda:not d.workers)
    d.render_calendar(dict(state='ready',items=[dict(time='10:00',title='Anterior')]),d.day)
    d.render_tasks(dict(state='ready',saved=[dict(id='1',title='Anterior',state='pending')],temporary=[]))
    d.render_calendar(dict(state='disconnected',items=[],message='Conectar'),d.day)
    d.render_tasks(dict(state='disconnected',saved=[],temporary=[],message='Configurar'))
    assert all('Anterior' not in listing.item(0).text() for listing,_,_ in d.calendar_lists)
    assert d.task_rows['saved']==[] and not hasattr(d,'_tasks_snapshot')
