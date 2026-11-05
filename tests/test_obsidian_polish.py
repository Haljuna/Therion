"""Acabamento da interface Obsidiana com dados fictícios; sem microfone, contas ou modelos reais."""
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from tests.test_constellation import app,window,settle
from tests.test_interface_followup import scene,drag
from therion.interface.design_system import COMPONENT_STYLE


def test_free_windows_stay_clear_of_header_navigation_and_composer(window):
    d=scene(window);d.navigate(3);tasks=d.workspace.panels['tasks']
    drag(tasks.title_bar,-2000,-2000)
    assert tasks.y()>=80 and tasks.x()>d.nav.width()
    drag(tasks.title_bar,3000,3000)
    assert tasks.geometry().bottom()<d.composer.y()
    assert d.rect().contains(tasks.geometry())


def test_title_bar_offers_collapse_and_close_with_clear_names(window):
    d=scene(window);d.navigate(3);tasks=d.workspace.panels['tasks']
    controls=tasks.title_bar.controls
    assert controls['minimize'].accessibleName()=='Recolher Tarefas'
    assert controls['close'].accessibleName()=='Fechar Tarefas'
    window._input.setPlainText('Rascunho preservado')
    controls['minimize'].click();QApplication.processEvents()
    assert tasks.isHidden() and tasks.window_state=='minimized'
    d.navigate(3);controls['close'].click();QApplication.processEvents()
    assert tasks.isHidden() and tasks.window_state=='closed'
    assert window._input.toPlainText()=='Rascunho preservado'


def test_agenda_day_navigation_fits_in_one_row(window):
    d=scene(window);d.navigate(2);QApplication.processEvents()
    tops={control.geometry().center().y() for control in d.calendar_date_buttons}
    assert len(tops)==1
    assert [c.accessibleName() for c in d.calendar_date_buttons]==['Dia anterior','Voltar para hoje','Próximo dia','Atualizar agenda']


def test_home_glance_reuses_loaded_data_and_only_opens_windows(window):
    d=scene(window);d.navigate(0);d._arrange_scene();QApplication.processEvents()
    assert not d.glance.isHidden()
    with patch.object(window,'_send_command') as command:
        d.glance.tasks.click();QApplication.processEvents()
        assert d.workspace.panels['tasks'].isVisible() and d.glance.isHidden()
        command.assert_not_called()
    d.navigate(0);QApplication.processEvents()
    assert not d.glance.isHidden()
    window.resize(1024,768);QApplication.processEvents();d._arrange_scene()
    assert d.glance.isHidden()


def test_status_reports_disabled_model_and_lists_services(window):
    d=scene(window);window._config.setdefault('ai',{})['enabled']=False
    d.presentation.interaction='idle';d.poll();QApplication.processEvents()
    assert d.status.text()=='Pronto · IA desativada'
    health=d.service_health()
    assert d.status.toolTip()==health['summary']
    assert not health['ai'] and 'Modelo local: desativado' in health['summary']
    assert 'Agenda:' in health['summary'] and 'Gmail:' in health['summary']


def test_voice_controls_show_only_usable_actions_and_restore_classic(window):
    d=scene(window);d._tidy_session_controls()
    assert window._stop_speech_button.isHidden()==(not window._stop_speech_button.isEnabled())
    if not window._conversation_label.text():assert window._conversation_label.isHidden()
    window._select_interface('classic',persist=False);QApplication.processEvents()
    assert not window._stop_speech_button.isHidden() and not window._conversation_label.isHidden()


def test_scrollbar_track_has_no_default_texture():
    assert 'QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }' in COMPONENT_STYLE


# --- Obsidiana refinada (proposta A) ---
from datetime import datetime
from therion.interface.dashboard import greeting_for


def test_greeting_follows_the_local_clock_only():
    assert greeting_for(datetime(2026,10,29,8,0))=='BOM DIA'
    assert greeting_for(datetime(2026,10,29,12,0))=='BOA TARDE'
    assert greeting_for(datetime(2026,10,29,22,11))=='BOA NOITE'
    assert greeting_for(datetime(2026,10,29,3,0))=='BOA NOITE'


def test_health_dots_hide_parakeet_when_not_configured_and_never_probe(window):
    d=scene(window);window._config.pop('voice',None)
    with patch('therion.interface.dashboard.read_stt_health') as probe:
        d.probe_stt();d.poll();QApplication.processEvents()
        probe.assert_not_called()
    health=d.service_health()
    assert health['levels']['stt']=='hidden' and d.health_dots['stt'][0].isHidden()
    assert not d.health_dots['ai'][0].isHidden()


def test_parakeet_probe_is_read_only_and_reports_failure(window):
    d=scene(window);window._config['voice']={'provider':'parakeet_http'}
    with patch('therion.interface.dashboard.read_stt_health',return_value={'status':'error','failure_type':'MemoryError'}) as probe:
        d.probe_stt();d._stt_probe.join(2)
        probe.assert_called_once_with()
    health=d.service_health()
    assert health['levels']['stt']=='error' and 'MemoryError' in health['summary']
    window._config.pop('voice',None)


def test_quick_actions_use_the_normal_command_path_and_keep_the_draft(window):
    d=scene(window);d.navigate(0);QApplication.processEvents()
    window._input.setPlainText('Rascunho')
    with patch.object(window,'_send_command') as send:
        d.quick_actions[0].click()
        send.assert_called_once_with()
    assert window._input.toPlainText()=='Mostre meu panorama'
    assert [a.text() for a in d.quick_actions]==['Mostre meu panorama','Abrir e-mails','Nova tarefa','Abrir o Obsidian']


def test_voice_controls_live_inside_the_composer(window):
    d=scene(window)
    for widget in (window._conversation_button,window._voice_button,window._send_button,window._stop_speech_button):
        assert d.composer.isAncestorOf(widget)
    assert d.response_preview.isAncestorOf(window._listen_button)
    assert d.control_bar.isAncestorOf(window._workflow_cancel_button)


def test_right_column_and_badges_on_wide_home(window):
    d=scene(window);d.navigate(0);d._arrange_scene();QApplication.processEvents()
    column=d.side_column()
    assert d.glance.geometry().x()==column.x()
    assert not d.composer.geometry().intersects(column)
    d.set_badge('tasks',3);assert d.nav_badges['tasks'].text()=='3' and not d.nav_badges['tasks'].isHidden()
    d.set_badge('tasks',0);assert d.nav_badges['tasks'].isHidden()
    assert not d.greeting_title.isHidden() and d.greeting_title.text()=='Como posso ajudar?'
