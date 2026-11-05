"""Contratos do painel com dados fictícios; nenhuma fonte pessoal é utilizada."""
import math
import threading
import time
import wave
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtWidgets import QApplication
from therion.interface.presentation import Presentation, normalized_level, QualityController
from therion.interface.dashboard_data import DashboardSource
from therion.agent.contracts import CancellationToken


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def settle(predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:
        QApplication.processEvents(); time.sleep(.005)
    assert predicate()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    for variable in ('APPDATA','LOCALAPPDATA'):
        folder=tmp_path/variable;folder.mkdir()
        monkeypatch.setenv(variable,str(folder))
    from therion.interface.desktop import MainWindow
    with patch.object(MainWindow,'_setup_tray'):
        w=MainWindow(MagicMock(), config={'ai':{'enabled':False},'tts':{'enabled':False}},
                     config_writer=MagicMock(),log_dir=tmp_path/'logs')
    yield w
    dashboard = getattr(w,'_dashboard',None)
    if dashboard:
        dashboard.cancel()
        for worker in list(dashboard.mailbox.jobs.values()):worker.wait(3000)
        for worker in list(dashboard.workers.values()): worker.wait(3000)
        if dashboard.action_worker: dashboard.action_worker.wait(3000)
    w._closing=True; w.close(); w.deleteLater()
    QApplication.sendPostedEvents(None,QEvent.DeferredDelete);app.processEvents()


@pytest.mark.parametrize('value,expected',[(float('nan'),0),(float('inf'),0),(-1,0),(3,1),(.4,.4),('bad',0)])
def test_levels_are_finite(value, expected):
    assert normalized_level(value)==expected


def test_states_do_not_simulate_speech_while_synthesizing():
    p=Presentation(interaction='thinking',speech='synthesizing')
    assert p.state=='thinking'
    p.interaction='idle'; assert p.state=='synthesizing'
    p.speech='playing'; assert p.state=='speaking'
    p.confirmation=True; assert p.state=='awaiting_confirmation'
    p.confirmation=False; p.speech='idle'; p.capture='recording'; assert p.state=='listening'
    p.capture='transcribing'; assert p.state=='transcribing'


def test_quality_reacts_to_sustained_load_and_manual_stays_fixed():
    q=QualityController()
    for _ in range(150): q.observe(.06)
    assert q.level=='low'
    q=QualityController('high')
    for _ in range(500): q.observe(.1)
    assert q.level=='high'


def test_graphics_timing_preserves_surface_and_avoids_unbounded_rendering():
    from PySide6.QtGui import QSurfaceFormat
    from therion.interface.graphics import prepare_graphics, FRAME_INTERVAL_MS
    original=QSurfaceFormat.defaultFormat()
    configured=QSurfaceFormat(original)
    configured.setVersion(3,3); configured.setSamples(4)
    configured.setDepthBufferSize(24); configured.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(configured)
    try:
        prepare_graphics()
        result=QSurfaceFormat.defaultFormat()
        assert result.swapInterval()==0
        result.setSwapInterval(1)
        assert result==configured
        assert 15<=FRAME_INTERVAL_MS<=17
    finally: QSurfaceFormat.setDefaultFormat(original)


def test_particle_layers_remain_distributed_at_every_quality():
    from therion.interface.constellation import particle_data
    data=particle_data(QualityController.COUNTS['high'])
    assert data.shape==(48000,8) and data.dtype==np.float32
    assert np.isfinite(data).all()
    for count in QualityController.COUNTS.values():
        subset=data[:count]
        radii=np.linalg.norm(subset[:,:3],axis=1)
        assert radii.min()>.96 and radii.max()<1.23
        assert .68<np.mean(subset[:,4]==0)<.76
        assert .16<np.mean(subset[:,4]==1)<.24
        assert .05<np.mean(subset[:,4]==2)<.11


def test_responsive_density_preserves_coverage_without_saturating_small_sphere():
    from therion.interface.constellation import visible_particle_count
    assert visible_particle_count('high',900,600)==48000
    assert visible_particle_count('high',900,250)==12000
    assert visible_particle_count('high',250,900)==12000
    assert visible_particle_count('low',900,250)==3000
    assert 0<visible_particle_count('low',0,0)<=12000


def test_wav_envelope_preserves_silence_and_pauses(tmp_path):
    from therion.voice.envelope import wav_envelope
    path=tmp_path/'voice.wav'
    samples=np.concatenate([np.zeros(1600),np.ones(1600)*.1,np.zeros(1600)])
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
        out.writeframes((samples*32767).astype('<i2').tobytes())
    levels=wav_envelope(path)
    assert len(levels)==12
    assert levels[:4]==(0,)*4 and levels[-4:]==(0,)*4
    assert min(levels[4:8])>.45


def test_capture_level_uses_existing_stream_and_resets():
    from therion.voice.capture import AudioCaptureService
    stream=MagicMock(); factory=MagicMock(return_value=stream)
    capture=AudioCaptureService(stream_factory=factory)
    assert capture.start()
    capture._audio_callback(np.full((400,1),.1,dtype='float32'),400,None,None)
    assert .45<capture.level<.5
    assert factory.call_count==1
    capture.cancel(); assert capture.level==0


def test_envelope_rejects_late_generation_and_different_chunk(app,tmp_path):
    from therion.voice.speech_output import SpeechOutput
    service=SpeechOutput({})
    service.set_meter_enabled(True)
    service._active_audio=tmp_path/'two.wav'
    service._accept_envelope(service.generation-1,str(service._active_audio),(.5,))
    assert service._envelope==()
    service._accept_envelope(service.generation,str(tmp_path/'one.wav'),(.5,))
    assert service._envelope==()
    service._accept_envelope(service.generation,str(service._active_audio),(.5,))
    assert service._envelope==(.5,)
    service.stop(); assert service.level==0 and service._envelope==()
    service._accept_envelope(service.generation-1,str(tmp_path/'two.wav'),(1.,))
    assert service._envelope==()


def test_interface_roundtrip_preserves_session_draft_and_history(window):
    w=window
    history,input_widget=w._history,w._input
    w._append('Você','Mensagem original'); w._input.setPlainText('rascunho')
    session=w._orchestrator.session_id
    w._select_interface('constellation',persist=False)
    d=w._dashboard
    settle(lambda:not d.workers)
    assert d.pages.count()==1 and len(d.workspace.panels)==7
    assert w._history is history and w._input is input_widget
    for i in range(7): d.navigate(i)
    w._select_interface('classic',persist=False)
    assert w._orchestrator.session_id==session
    assert 'Mensagem original' in w._history.toPlainText()
    assert w._input.toPlainText()=='rascunho'
    assert w.centralWidget().currentWidget() is w._classic_ui
    w._select_interface('constellation',persist=False)
    settle(lambda:not d.workers)
    assert w._input.toPlainText()=='rascunho'
    w._append('Therion','Mensagem de exemplo [gmail:identificador-ficticio]')
    assert '[gmail:' not in d.last_response.toPlainText()
    assert '[gmail:identificador-ficticio]' in w._history.toPlainText()
    w._clear_conversation();d.poll()
    assert d.response_preview.isHidden()


def test_temporary_tasks_do_not_become_saved(window):
    source=DashboardSource(window._orchestrator)
    result=source.action('session_add',{'title':'Exemplo temporário'},CancellationToken())
    assert result.status=='success'
    tasks=source.tasks(CancellationToken())
    assert tasks['state']=='disconnected' and tasks['saved']==[]
    assert tasks['temporary'][0]['title']=='Exemplo temporário'
    window._orchestrator.clear_session()
    assert source.tasks(CancellationToken())['temporary']==[]


def test_saved_task_requires_preview_and_visual_confirmation(window):
    source=DashboardSource(window._orchestrator); host=source.host
    host._agent_config['tasks_enabled']=True
    token=CancellationToken()
    result=source.action('prepare_task',{'title':'Tarefa aprovada','source_id':'user:current','due':''},token)
    assert result.status=='awaiting_confirmation'
    assert source.tasks(token)['saved']==[]
    proposal=host._agent_proposals.list()[0]
    result=source.action('approve',{'id':proposal.id,'digest':proposal.digest},token)
    assert result.status=='success'
    row=source.tasks(token)['saved'][0]
    assert row['title']=='Tarefa aprovada' and row['state']=='pending'
    source.action('prepare_task_state',{'id':row['id'],'state':'completed'},token)
    assert source.tasks(token)['saved'][0]['state']=='pending'
    proposal=host._agent_proposals.list()[0]
    host._agent_config['tasks_enabled']=False
    blocked=source.action('approve',{'id':proposal.id,'digest':proposal.digest},token)
    assert blocked.status!='success'


def test_calendar_disconnected_does_not_mean_empty(window):
    result=DashboardSource(window._orchestrator).calendar(window._orchestrator._calendar_now().date(),CancellationToken())
    assert result['state']=='disconnected' and result['message']


def test_late_calendar_response_does_not_replace_selected_day(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    started,release=threading.Event(),threading.Event()
    original=d.source.calendar
    def slow(day,token):
        started.set(); release.wait(2)
        return {'state':'ready','items':[{'time':'12:00','title':'Resultado antigo'}]}
    d.source.calendar=slow
    d.refresh('calendar'); assert started.wait(1)
    d.day += timedelta(days=1); d.epochs['calendar']+=1
    d.source.calendar=original
    release.set(); settle(lambda:not d.workers)
    assert all('Resultado antigo' not in listing.item(i).text()
               for listing,day,compact in d.calendar_lists for i in range(listing.count()))


def test_minimize_pauses_renderer_without_ending_conversation(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    window.show(); QApplication.processEvents()
    # Exercita a semântica do botão, sem iniciar microfone nesta fixture.
    with patch.object(window,'_end_conversation') as end:
        window._minimize_window(); QApplication.processEvents()
        end.assert_not_called()
    window.showNormal(); QApplication.processEvents()


def test_graphics_config_rejects_invalid_values():
    from therion.config.local import _validate_config
    config=_validate_config({'ui':{'interface':'wrong','graphics_quality':'wrong','reduced_motion':'yes'}})
    assert config['ui']['interface']=='constellation'
    assert config['ui']['graphics_quality']=='auto'
    assert config['ui']['reduced_motion'] is False
    for value in ([],{},None,True):
        config=_validate_config({'ui':{'interface':value,'graphics_quality':value}})
        assert config['ui']['interface']=='constellation' and config['ui']['graphics_quality']=='auto'


def test_appearance_saves_preserve_pending_model_settings(window):
    from copy import deepcopy
    saved={'ai':{'enabled':False,'model':'original'},'tts':{'enabled':False},'ui':{},'unknown':{'keep':True}}
    window._config=deepcopy(saved)
    window._agent_config_loader=lambda:deepcopy(saved)
    def write(config): saved.clear(); saved.update(deepcopy(config))
    window._agent_config_writer=write
    window._select_interface('constellation')
    d=window._dashboard; settle(lambda:not d.workers)
    d.model.setText('future-model'); d.save_runtime()
    assert saved['ai']['model']=='future-model'
    assert window._config['ai']['model']=='original'
    d.save_appearance()
    window._select_interface('classic')
    assert saved['ai']['model']=='future-model' and saved['unknown']=={'keep':True}


def test_proposal_expiry_clears_visual_confirmation(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    d.presentation.interaction='awaiting_confirmation'
    d.poll()
    assert d.presentation.state=='idle' and d.proposal_bar.isHidden()


def test_calendar_oauth_is_only_started_by_explicit_button(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    for page in range(7): d.navigate(page)
    settle(lambda:not d.workers)
    assert d.calendar_auth is None


def test_activity_windows_start_minimized_and_preserve_content_on_reopen(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    assert d.workspace.visible_keys()==[]
    window._append('Therion','Resposta que deve continuar disponível ao recolher a janela.')
    panel=d.workspace.panels['tasks']
    draft=window._input
    draft.setPlainText('Texto em edição')
    session=window._orchestrator.session_id
    d.activity_buttons['tasks'].click()
    settle(lambda:not d.workers)
    assert not panel.isHidden()
    d.task_tabs[0][0].setCurrentIndex(1)
    panel.dismiss()
    assert panel.isHidden() and not d.activity_buttons['tasks'].isChecked()
    d.activity_buttons['tasks'].click()
    assert d.workspace.panels['tasks'] is panel
    assert d.task_tabs[0][0].currentIndex()==1
    assert draft.toPlainText()=='Texto em edição' and window._orchestrator.session_id==session
    # Esc recolhe a janela focada; o texto inicial reaparece sem alterar o conteúdo.
    from PySide6.QtTest import QTest
    window.show(); QApplication.processEvents()
    response=d.last_response.toPlainText()
    focus=d.constellation.focus_rect
    assert all(widget.isHidden() for widget in d.home_copy)
    QTest.keyClick(panel,Qt.Key_Escape)
    QApplication.processEvents()
    assert panel.isHidden() and all(not widget.isHidden() for widget in d.home_copy)
    assert d.last_response.toPlainText()==response and d.constellation.focus_rect==focus


def test_opening_windows_keeps_one_scene_and_supports_future_surfaces(window):
    from PySide6.QtWidgets import QLabel
    from PySide6.QtCore import QSize,QRect
    window._select_interface('constellation',persist=False)
    window.show(); QApplication.processEvents()
    d=window._dashboard; settle(lambda:not d.workers)
    scene=d.constellation.geometry()
    settle(lambda:d.orb_transition.state()==d.orb_transition.State.Stopped)
    focus=d.constellation.focus_rect
    with patch.object(window._orchestrator,'process_command') as process:
        d.workspace.register('future-mail','Caixa de entrada de exemplo',QLabel('Conteúdo fictício'),QSize(480,340))
        panel=d.workspace.open('future-mail')
        panel.place(QRect(-100,-100,9999,9999))
        assert d.workspace_rect().contains(panel.geometry())
        panel.dismiss(); d.workspace.open('future-mail')
        process.assert_not_called()
    QApplication.processEvents()
    assert d.constellation.geometry()==scene==d.rect()
    settle(lambda:d.orb_transition.state()==d.orb_transition.State.Stopped)
    assert d.constellation.focus_rect==d._orb_target and d.constellation.focus_rect!=focus


def test_navigation_uses_stable_panels_and_preserves_previous_content(window):
    from PySide6.QtTest import QTest
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    d.navigate(2);agenda=d.workspace.panels['calendar']
    d.navigate(3);panel=d.workspace.panels['tasks'];old=panel.geometry()
    QTest.mousePress(panel.title_bar,Qt.LeftButton,Qt.NoModifier,QPoint(40,15))
    QTest.mouseMove(panel.title_bar,QPoint(10,15),20)
    QTest.mouseRelease(panel.title_bar,Qt.LeftButton,Qt.NoModifier,QPoint(10,15))
    assert panel.geometry()!=old and panel.manually_placed and agenda.isHidden()
    assert d.workspace.visible_keys()==['tasks']
    assert old==d.panel_opening_rect()
    d.navigate(2);assert d.workspace.panels['calendar'] is agenda
    d.navigate(0);assert d.workspace.visible_keys()==[]


def test_scene_focus_uses_local_coordinates_after_main_window_moves(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900); window.move(150,110); window.show()
    QApplication.processEvents()
    d=window._dashboard; d._arrange_scene()
    settle(lambda:d.orb_transition.state()==d.orb_transition.State.Stopped)
    expected=d.hero_space.mapTo(d,QPoint(0,0))
    assert d.constellation.focus_rect.topLeft().toPoint()==expected
    first=d.constellation.focus_rect
    window.move(250,180); QApplication.processEvents(); d._arrange_scene()
    assert d.constellation.focus_rect==first


def test_minimizing_settings_keeps_unsaved_form_content(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    d.navigate(6)
    d.model.setText('rascunho-de-modelo')
    d.workspace.panels['settings'].dismiss()
    d.navigate(6)
    assert d.model.text()=='rascunho-de-modelo'
    window._agent_config_writer.assert_not_called()


def test_auxiliary_panel_replaces_main_below_1000_and_returns_without_loss(window):
    from PySide6.QtWidgets import QLabel
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers);d.navigate(3)
    main=d.workspace.panels['tasks']
    detail=d.workspace.register('detail-test','Detalhes',QLabel('Dados fictícios'))
    d.workspace.open('detail-test');QApplication.processEvents()
    assert not main.isHidden() and not detail.isHidden()
    assert not main.geometry().intersects(detail.geometry())
    window.resize(960,640);QApplication.processEvents();d._arrange_scene()
    assert main.isHidden() and not detail.isHidden()
    detail.dismiss();assert not main.isHidden() and detail.isHidden()
    assert d.workspace.visible_keys()==['tasks']


@pytest.mark.parametrize('key',['tasks','calendar','tools'])
def test_panel_headers_keep_content_outside_navigation_and_composer(window,key):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    panel=d.workspace.open(key);d._arrange_scene()
    assert d.panel_opening_rect().contains(panel.geometry())
    assert panel.x()>d.nav.geometry().right()
    assert panel.geometry().bottom()<d.composer.y()
    assert not panel.manually_placed


def test_agenda_switch_keeps_the_organized_layout(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    d.toggle_activity('calendar');panel=d.workspace.panels['calendar']
    d.navigate(2);d._arrange_scene()
    assert panel.geometry()==d.panel_opening_rect() and not d.calendar_compact


def test_free_windows_keep_confirmation_above_panels_without_changing_buttons(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    panel=d.workspace.open('tasks');panel.place(d.workspace_rect(),manual=True)
    window._confirm_description.setText('Exemplo fictício: revisar esta proposta.')
    window._confirm_panel.show();d._arrange_confirmations();QApplication.processEvents()
    d.workspace.activate('tasks')
    point=window._btn_confirm.mapTo(d,window._btn_confirm.rect().center())
    assert d.childAt(point) is window._btn_confirm
    assert not d.confirm_overlay.isHidden() and not panel.isHidden()
    window._confirm_panel.hide();d._arrange_confirmations()
    assert d.confirm_overlay.isHidden() and not panel.isHidden()


def test_short_viewport_keeps_input_reachable_by_scrolling(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard; settle(lambda:not d.workers)
    window.setMinimumSize(0,0); window.resize(960,500); window.show()
    QApplication.processEvents()
    scroll=window._dashboard_scroll
    assert scroll.verticalScrollBar().maximum()>0
    scroll.ensureWidgetVisible(window._input)
    QApplication.processEvents()
    center=window._input.mapTo(window,QPoint(window._input.width()//2,window._input.height()//2))
    assert window.rect().contains(center)


def test_stop_task_cancels_dashboard_operation(window):
    from therion.agent.contracts import ToolResult
    window._select_interface('constellation',persist=False)
    window.resize(960,640);window.show();QApplication.processEvents()
    d=window._dashboard; settle(lambda:not d.workers)
    started=threading.Event()
    def wait_for_cancel(operation,arguments,token):
        started.set()
        deadline=time.monotonic()+2
        while not token.cancelled and time.monotonic()<deadline: time.sleep(.005)
        return ToolResult('cancelled',message='Operação interrompida.')
    d.source.action=wait_for_cancel
    d.action('prepare_task',{})
    assert started.wait(1)
    assert not window._workflow_cancel_button.isHidden()
    QApplication.processEvents();d._arrange_scene();QApplication.processEvents()
    assert d.control_bar.rect().contains(window._workflow_cancel_button.geometry())
    window._on_workflow_cancel()
    settle(lambda:d.action_worker is None)
    assert not window._processing and 'interrompida' in window._history.toPlainText()


def test_singularity_crop_preserves_aspect_and_stays_inside_image():
    from therion.interface.singularity import environment_crop,filament_mesh
    for width,height in [(1920,1080),(1440,900),(960,640),(800,1100)]:
        crop=environment_crop(width,height,1672,941)
        assert 0<=crop.x() and 0<=crop.y()
        assert crop.right()<=1672.001 and crop.bottom()<=941.001
        assert crop.width()/crop.height()==pytest.approx(width/height)
    mesh=filament_mesh(88)
    assert mesh.dtype==np.float32 and mesh.shape[1]==4 and len(mesh)<200000
    assert len(mesh)%3==0 and np.isfinite(mesh).all()
    assert set(np.unique(mesh[:,2]))=={-1.,1.}
    low=filament_mesh(32)
    # Os filamentos existentes não trocam de trajetória ao adaptar a qualidade.
    prefix=32*224*6
    assert np.array_equal(low[:prefix],mesh[:prefix])


def test_singularity_button_skin_keeps_mouse_keyboard_and_caption(app):
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QTest
    from therion.interface.singularity_chrome import GlyphSkin
    btn=QPushButton('Falar');before=(btn.minimumSize(),btn.maximumSize())
    clicked=[];pressed=[];released=[]
    btn.clicked.connect(lambda:clicked.append(True));btn.pressed.connect(lambda:pressed.append(True));btn.released.connect(lambda:released.append(True))
    skin=GlyphSkin(btn,'M2 2l20 20');btn.show();btn.setFocus();QApplication.processEvents()
    QTest.mouseClick(btn,Qt.LeftButton);QTest.keyClick(btn,Qt.Key_Space)
    assert len(clicked)==len(pressed)==len(released)==2
    btn.setText('Gravando…');QApplication.processEvents()
    assert btn.text()=='Gravando…'
    skin.detach();assert (btn.minimumSize(),btn.maximumSize())==before
    btn.close();btn.deleteLater()


def test_singularity_restores_classic_button_constraints(window):
    window.show();QApplication.processEvents()
    buttons=(window._send_button,window._voice_button)
    before=[(btn.minimumSize(),btn.maximumSize()) for btn in buttons]
    input_before=(window._input.minimumSize(),window._input.maximumSize())
    names=[(btn.objectName(),btn.accessibleName()) for btn in buttons]
    window._select_interface('constellation',persist=False)
    assert len(window._dashboard.glyph_skins)==2
    assert window._send_button.width()==32 and window._voice_button.width()==32
    window._select_interface('classic',persist=False)
    assert [(btn.minimumSize(),btn.maximumSize()) for btn in buttons]==before
    assert (window._input.minimumSize(),window._input.maximumSize())==input_before
    assert [(btn.objectName(),btn.accessibleName()) for btn in buttons]==names


def test_agenda_uses_main_panel_and_preserves_home_response(window):
    window._select_interface('constellation',persist=False)
    window.resize(1440,900);window.show();QApplication.processEvents()
    d=window._dashboard;settle(lambda:not d.workers)
    window._append('Therion','Resposta preservada')
    d.toggle_activity('calendar');panel=d.workspace.panels['calendar']
    assert panel.geometry()==d.panel_opening_rect()
    assert d.last_response.toPlainText()=='Resposta preservada'
    assert d.response_preview.isHidden()
    d.navigate(0);assert not d.response_preview.isHidden()


def test_singularity_mail_shortcut_opens_mail_window_and_preserves_draft(window):
    window._select_interface('constellation',persist=False)
    d=window._dashboard;settle(lambda:not d.workers)
    window._input.setPlainText('Meu rascunho')
    captured=[]
    def submit():captured.append(window._input.toPlainText());window._input.clear()
    with patch.object(window,'_send_command',side_effect=submit):d.mail_button.click()
    assert captured==[]
    assert window._input.toPlainText()=='Meu rascunho'
    assert 'mail' in d.workspace.visible_keys()


def test_singularity_small_navigation_has_room_for_complete_icons(window):
    window._select_interface('constellation',persist=False)
    window.resize(960,640);window.show();QApplication.processEvents()
    d=window._dashboard
    assert all(btn.width()>=50 and btn.iconSize().width()==20 for btn in d.nav_buttons)
    assert window.rect().contains(window._send_button.mapTo(window,QPoint(27,27)))
