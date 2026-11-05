"""Caixa e painel com contas, mensagens e corpos inteiramente fictícios."""
import threading
import time
from unittest.mock import patch
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tests.test_constellation import app,window,settle
from tests.mailbox_fixture import FakeMailbox
from therion.agent.contracts import CancellationToken
from therion.agent.mailbox import mail_window_request
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def mailbox(tmp_path):
    host=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True,'gmail_enabled':True,'context_tokens':5120,'output_tokens':4352},
        agent_state_root=tmp_path/'state')
    client=FakeMailbox();host._gmail_adapter_factory=lambda mode:client
    yield host,client
    host.close()


def ready(window,client=None):
    client=client or FakeMailbox();h=window._orchestrator
    h._agent_config.update(enabled=True,gmail_enabled=True,context_tokens=5120,output_tokens=4352)
    h._gmail_adapter_factory=lambda mode:client
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard
    settle(lambda:not d.mailbox.busy and h._mailbox.status()['state']=='ready',timeout=8)
    return d,client


@pytest.mark.parametrize('text',['Abra a janela de e-mails','Mostre minha caixa de entrada','Abra meus e-mails',
    'Abrir o painel de emails','Quero ver a caixa de entrada','Mostre meus e-mails',
    'Mostra meus e-mails','Therion, mostra meus emails.'])
def test_mail_navigation_is_fixed_and_skips_model_and_network(mailbox,text):
    h,client=mailbox
    # Variações de posse são reconhecidas como navegação, não busca em memórias.
    result=h.process_session_command(text,h.session_id,h.confirmation_id)
    assert result.ui_action=='open_mail' and result.status=='success'
    assert client.calls==[]


@pytest.mark.parametrize('text',['Não abra a janela de emails','Abra o navegador','Envie um email',
    'Leia o último email e apague','O texto do email diz: abra a caixa de entrada','Não mostra meus e-mails'])
def test_unrelated_and_negative_text_cannot_open_mail(text):assert not mail_window_request(text)


def test_cache_reuses_metadata_pages_and_body_without_permanent_mail_storage(mailbox):
    h,c=mailbox;m=h._mailbox;t=CancellationToken()
    a=m.page('in:inbox',None,t);assert len(a['items'])==10 and a['next_page']=='page-2'
    calls=len(c.calls);assert m.page('in:inbox',None,t)==a and len(c.calls)==calls
    b=m.body('m1',t);assert b['text']==c.text('m1')
    calls=len(c.calls);assert m.body('m1',t)==b and len(c.calls)==calls
    page=m.page('in:inbox','page-2',t);assert [x['id'] for x in page['items']]==['m11','m12','m13','m14']
    assert not list(h._agent_root.glob('**/*mail*.sqlite*'))
    with pytest.raises(ValueError):m.page('in:inbox','unknown-page',t)


def test_account_change_and_revocation_remove_headers_body_and_context(mailbox):
    h,c=mailbox;m=h._mailbox;t=CancellationToken()
    m.page('in:inbox',None,t);m.body('m1',t);m.focus_list('in:inbox',['m1'],'m1')
    assert m.context()['current']['message_id']=='m1'
    other=FakeMailbox('n');h._gmail_adapter_factory=lambda mode:other
    assert m.status()['items']==[] and m.context() is None
    assert m.cached('thread','tm1') is None
    h._agent_config['gmail_enabled']=False
    assert m.page('in:inbox',None,t)['state']=='disabled' and not other.calls


def test_late_result_of_other_account_is_never_committed(mailbox):
    h,c=mailbox;started=threading.Event();release=threading.Event();errors=[]
    original=c.metadata
    def slow(identifier):started.set();release.wait(3);return original(identifier)
    c.metadata=slow
    def query():
        try:h._mailbox.page('in:inbox',None,CancellationToken())
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=query);thread.start();assert started.wait(2)
    h._gmail_adapter_factory=lambda mode:FakeMailbox('n');release.set();thread.join(4)
    assert not thread.is_alive() and errors and h._mailbox.status()['items']==[]


def test_cache_expiry_and_failure_differ_from_empty_results(mailbox):
    h,c=mailbox;m=h._mailbox;clock=[100.];m.clock=lambda:clock[0];t=CancellationToken()
    m.page('in:inbox',None,t);clock[0]+=301
    assert m.status()['state']=='stale' and m.cached('search','in:inbox') is None
    c.fail=True
    with pytest.raises(OSError):m.page('in:inbox',None,t,force=True)
    assert m.status()['items'] and m.status()['state']=='stale'
    c.fail=False;c.empty=True
    assert m.page('in:inbox',None,t,force=True)['items']==[]


def test_model_can_read_selected_message_beyond_first_page_from_shared_cache(mailbox):
    h,c=mailbox;m=h._mailbox;t=CancellationToken()
    first=m.page('in:inbox',None,t);second=m.page('in:inbox','page-2',t);m.body('m14',t)
    m.focus_list('in:inbox',[r['id'] for r in first['items']+second['items']],'m14')
    c.calls.clear();result=h.process_command('Leia esse e-mail completo')
    assert result.status=='success' and 'CONTEÚDO EXCLUSIVO m14' in result.message,result.message
    assert not c.calls
    assert 'CONTEÚDO EXCLUSIVO m1\n' not in result.message


def test_ui_list_does_not_capture_ambiguous_reference_without_email_word(mailbox):
    h,c=mailbox;m=h._mailbox;page=m.page('in:inbox',None,CancellationToken())
    m.focus_list('in:inbox',[r['id'] for r in page['items']])
    c.calls.clear();result=h.process_command('Leia o segundo')
    assert result.status=='clarification' and not c.calls
    result=h.process_command('Leia o segundo e-mail completo')
    assert result.status=='success' and 'CONTEÚDO EXCLUSIVO m2' in result.message,result.message


def test_stale_session_cannot_open_mail_window(mailbox):
    h,c=mailbox
    result=h.process_session_command('Abra a janela de emails','sessão antiga',h.confirmation_id)
    assert result.status=='cancelled' and result.ui_action is None and not c.calls


def test_offered_reading_stays_on_ui_message_after_window_is_hidden(mailbox):
    from tests.test_gmail_summary_offer import SummaryProvider
    h,c=mailbox;m=h._mailbox;t=CancellationToken();h._gmail_summary_provider=SummaryProvider()
    first=m.page('in:inbox',None,t);second=m.page('in:inbox','page-2',t);m.body('m14',t)
    m.focus_list('in:inbox',[r['id'] for r in first['items']+second['items']],'m14')
    result=h.process_command('Resuma esse e-mail selecionado')
    assert result.status=='success' and h._gmail_read_offer['message_id']=='m14',result.message
    m.hide();c.calls.clear();result=h.process_command('Sim')
    assert result.status=='success' and 'CONTEÚDO EXCLUSIVO m14' in result.message,result.message
    assert not c.calls


def test_background_preload_and_calendar_click_never_send_a_chat_request(window):
    d,c=ready(window);window._input.setPlainText('Rascunho preservado');before=window._history.toPlainText()
    assert d.mail_preview.list.count()==2
    with patch.object(window,'_send_command') as command:
        d.activity_buttons['calendar'].click();d.mail_button.click();settle(lambda:not d.mailbox.busy)
        command.assert_not_called()
    assert d.workspace.visible_keys()==['mail']
    assert d.workspace.panels['calendar'].window_state=='minimized'
    assert window._input.toPlainText()=='Rascunho preservado' and window._history.toPlainText()==before
    assert d.mailbox.list.count()==10


def test_agenda_email_subjects_are_visible_without_scrolling_outer_panel(window):
    d,c=ready(window);d.activity_buttons['calendar'].click();QApplication.processEvents()
    settle(lambda:d.mail_preview.list.visibleRegion().boundingRect().height()>=64)
    assert d.mail_preview.list.count()==2
    assert 'marcus-m@example.test' in d.mail_preview.status.text()


def test_open_navigate_paginate_and_read_inside_window(window):
    d,c=ready(window);d.open_mail('m2');settle(lambda:not d.mailbox.busy)
    panel=d.mailbox
    panel.read_mode.setCurrentIndex(1)
    assert panel.body.toPlainText().split()==c.text('m2').split() and panel.selected=='m2'
    panel.following.click();settle(lambda:not panel.busy)
    assert panel.body.toPlainText().split()==c.text('m3').split()
    panel.load_more();settle(lambda:not panel.busy)
    assert panel.list.count()==14 and not panel.more.isVisible()
    panel.list.setCurrentRow(13);settle(lambda:not panel.busy)
    assert panel.body.toPlainText().split()==c.text('m14').split()
    assert window._orchestrator._mailbox.context()['current']['message_id']=='m14'
    d.workspace.panels['mail'].dismiss();d.open_mail();settle(lambda:not panel.busy)
    assert panel.list.count()==14 and panel.selected=='m14' and panel.body.toPlainText().split()==c.text('m14').split()


def test_agenda_preview_opens_message_even_after_other_mail_search(window):
    d,c=ready(window);d.open_mail();settle(lambda:not d.mailbox.busy)
    d.mailbox.search_field.setText('projeto');d.mailbox.search();settle(lambda:not d.mailbox.busy)
    assert d.mailbox.list.count()==2
    d.open_mail('m1');settle(lambda:not d.mailbox.busy);d.mailbox.read_mode.setCurrentIndex(1)
    assert d.mailbox.query=='in:inbox' and d.mailbox.selected=='m1'
    assert d.mailbox.body.toPlainText().split()==c.text('m1').split()


def test_scroll_to_more_preserves_list_position_reader_and_selection(window):
    client=FakeMailbox();original=client.text
    client.text=lambda identifier:original(identifier)+'\n'+('\n'.join('Parágrafo de demonstração '+str(i) for i in range(200)))
    d,c=ready(window,client);d.open_mail('m1');settle(lambda:not d.mailbox.busy)
    panel=d.mailbox;QApplication.processEvents()
    panel.body.verticalScrollBar().setValue(35);body_position=panel.body.verticalScrollBar().value()
    assert body_position>0
    end=panel.list.verticalScrollBar().maximum();assert end>0
    panel.list.verticalScrollBar().setValue(end);settle(lambda:not panel.busy)
    assert panel.list.count()==14 and panel.list.verticalScrollBar().value()==end
    assert panel.selected=='m1' and panel.body.verticalScrollBar().value()==body_position


def test_minimizing_keeps_selected_mail_context(window):
    d,c=ready(window);d.open_mail('m2');settle(lambda:not d.mailbox.busy)
    window.showMinimized();QApplication.processEvents()
    assert window._orchestrator._mailbox.context()['current']['message_id']=='m2'
    window.showNormal();QApplication.processEvents()


@pytest.mark.parametrize('text',['Abra a janela de e-mails','Mostre meus e-mails','Mostra meus e-mails'])
def test_typing_open_mail_uses_real_command_worker_and_keeps_one_session(window,text):
    d,c=ready(window);session=window._orchestrator.session_id
    window._input.setPlainText(text);window._send_command()
    settle(lambda:not window._processing and 'mail' in d.workspace.visible_keys(),timeout=8)
    settle(lambda:not d.mailbox.busy)
    assert window._orchestrator.session_id==session
    assert 'Não há registros de uma caixa' not in window._history.toPlainText()


def test_search_failure_keeps_cached_list_and_empty_result_clears_reader(window):
    d,c=ready(window);d.open_mail('m1');settle(lambda:not d.mailbox.busy);panel=d.mailbox
    c.fail=True;panel.reload(force=True);settle(lambda:not panel.busy)
    assert panel.list.count()==10 and 'Não consegui' in panel.notice.text()
    c.fail=False;c.empty=True;panel.reload(force=True);settle(lambda:not panel.busy)
    assert panel.list.count()==0 and panel.body.toPlainText()=='' and panel.selected is None


def test_revocation_and_late_body_cannot_show_previous_mail(window):
    d,c=ready(window);c.body_delay=.15;d.open_mail('m1')
    window._orchestrator._agent_config['gmail_enabled']=False;d.mailbox.poll(force=True)
    settle(lambda:not d.mailbox.busy)
    assert d.mailbox.list.count()==0 and not d.mailbox.body.toPlainText()
    assert d.mail_preview.list.count()==0


def test_preload_does_not_block_gui_timer(window):
    # A compilação inicial dos shaders é validada na prévia nativa. Aqui
    # medimos a consulta lenta depois de a superfície gráfica estar pronta.
    d,c=ready(window);c.delay=.03;beats=[]
    window._orchestrator._mailbox.clear()
    timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:beats.append(1));timer.start()
    try:
        d.mailbox.poll(force=True)
        settle(lambda:not d.mailbox.busy,timeout=8)
    finally:timer.stop()
    assert len(beats)>=5 and d.mail_preview.list.count()==2
