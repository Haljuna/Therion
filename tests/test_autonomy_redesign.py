"""Regressão comportamental do redesign, em configuração fictícia."""
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import unittest

from tests import test_autonomy_v4 as base
from tests import test_autonomy_panel_v4 as panel_base
from therion.autonomy.apps import ApplicationCatalog
from therion.autonomy.integration import implementation_version


class BatchTests(unittest.TestCase):
    setUp=base.AutonomyTests.setUp;tearDown=base.AutonomyTests.tearDown
    write=base.AutonomyTests.write;seed=base.AutonomyTests.seed;app=base.AutonomyTests.app

    def rows(self,names):
        rows=[]
        for name in names:
            path=self.root/(name+'.exe');path.write_bytes(name.encode())
            rows.append(dict(name=name,path=str(path),source='fixture',aliases=[]))
        return rows

    def test_batch_preserves_existing_and_publishes_once_without_grants(self):
        existing=self.app('Existente');catalog=ApplicationCatalog(self.runtime)
        rows=self.rows(['Novo A','Novo B'])
        proposal=catalog.preview_many(rows+[dict(name='Ignorar',path=existing.path,aliases=['trocar'])])
        self.assertEqual(catalog.entries(),[existing])
        writes=[];self.runtime.writer=lambda config:(writes.append(deepcopy(config)),self.write(config))
        added=catalog.commit_many(proposal)
        self.assertEqual(len(writes),1);self.assertEqual(len(added),2)
        self.assertEqual(catalog.entries()[0],existing);self.assertEqual(self.runtime.policies(),[])

    def test_changed_executable_or_catalog_rejects_entire_batch(self):
        catalog=ApplicationCatalog(self.runtime);rows=self.rows(['A','B']);proposal=catalog.preview_many(rows)
        from pathlib import Path
        Path(rows[1]['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):catalog.commit_many(proposal)
        self.assertEqual(catalog.entries(),[])
        proposal=catalog.preview_many(rows);self.app('Outro')
        with self.assertRaises(ValueError):catalog.commit_many(proposal)
        self.assertEqual(len(catalog.entries()),1)

    def test_alias_edit_preserves_identity_and_atomically_revokes_grant(self):
        app=self.app();version=implementation_version(self.runtime,app.as_dict())
        self.seed('open_app',app.id,version);self.runtime.grant('open_app',app.id,version,'visual')
        updated=ApplicationCatalog(self.runtime).update_aliases(app,['editar','novo','NOVO'])
        self.assertEqual(updated.id,app.id);self.assertEqual(updated.identity,app.identity)
        self.assertEqual(len(updated.aliases),2);self.assertFalse(self.runtime.policies()[0].enabled)
        self.assertEqual(len(self.store.recent()),10)

    def test_alias_collision_does_not_modify_catalog_or_policy(self):
        app=self.app('Editor');self.app('Outro');catalog=ApplicationCatalog(self.runtime)
        before=deepcopy(self.config)
        with self.assertRaises(ValueError):catalog.update_aliases(app,['Outro'])
        self.assertEqual(self.config,before)

    def test_batch_persistence_failure_does_not_claim_success(self):
        catalog=ApplicationCatalog(self.runtime);proposal=catalog.preview_many(self.rows(['A','B']))
        self.runtime.writer=lambda config:(_ for _ in ()).throw(OSError('Disk full'))
        with self.assertRaises(OSError):catalog.commit_many(proposal)
        self.assertEqual(catalog.entries(),[])

    def test_legacy_alias_conflict_does_not_block_unrelated_batch(self):
        catalog=ApplicationCatalog(self.runtime)
        first=self.app('Primeiro');second=self.app('Segundo')
        self.runtime._update(lambda section:section['applications'][0].update(aliases=['Segundo']))
        existing=catalog.entries()
        catalog.commit_many(catalog.preview_many(self.rows(['Novo'])))
        self.assertEqual(catalog.entries()[:2],existing)
        with self.assertRaises(ValueError):catalog.preview_many([dict(self.rows(['Outro'])[0],aliases=['Segundo'])])


class RedesignTests(unittest.TestCase):
    setUp=base.AutonomyTests.setUp;tearDown=base.AutonomyTests.tearDown
    write=base.AutonomyTests.write;seed=base.AutonomyTests.seed
    window=panel_base.PanelTests.window;wait=panel_base.PanelTests.wait

    @classmethod
    def setUpClass(cls):panel_base.PanelTests.setUpClass();cls.app=panel_base.PanelTests.app

    def open_panel(self):
        window=self.window();window._show_autonomy();self.wait(window)
        panel=window._autonomy_panel;self.addCleanup(panel.close)
        return window,panel

    def register(self,name='Editor'):
        path=self.root/(name+'.exe');path.write_bytes(b'fixture')
        return ApplicationCatalog(self.runtime).register(name,str(path))

    def test_app_checkbox_without_observation_requests_visual_grant_and_can_cancel(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        app=self.register();window,panel=self.open_panel();card=panel.app_cards[app.id]
        before=deepcopy(self.config)
        self.assertTrue(card.check.isEnabled())
        self.assertTrue(panel.snapshot['app_states'][app.id]['eligible'])
        self.assertNotIn('0/10',panel.snapshot['app_states'][app.id]['detail'])
        with patch.object(panel,'confirm',return_value=False) as confirm:
            card.check.setFocus();QTest.keyClick(card.check,Qt.Key_Space)
            self.wait(window);confirm.assert_called_once()
        self.assertFalse(card.check.isChecked());self.assertEqual(self.config,before)

    def test_unready_memory_and_routine_explain_without_permission_changes(self):
        window=self.window();spec=window._routine_service.configure('daily_summary',8,0)
        window._show_autonomy();self.wait(window);panel=window._autonomy_panel;self.addCleanup(panel.close)
        before=deepcopy(self.config)
        with patch.object(panel,'confirm') as confirm:
            panel.routine_cards['daily_summary'].check.setChecked(True)
            self.assertFalse(panel.routine_cards['daily_summary'].check.isChecked())
            self.assertIn('0/10',panel.feedback.text())
            panel.memory_check.setChecked(True)
            self.assertFalse(panel.memory_check.isChecked());confirm.assert_not_called()
        self.assertEqual(self.config,before);self.assertFalse(window._routine_service.entries()[0].enabled)

    def test_expansion_and_click_outside_do_not_modify_authorizations(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt,QPoint
        app=self.register();window,panel=self.open_panel();before=deepcopy(self.config)
        card=panel.app_cards[app.id]
        QTest.mouseClick(card.title,Qt.LeftButton)
        self.assertTrue(card.body.isVisible())
        QTest.mouseClick(panel.app_content,Qt.LeftButton,Qt.NoModifier,QPoint(2,panel.app_content.height()-2))
        self.assertFalse(card.body.isVisible());self.assertEqual(self.config,before)

    def test_refresh_preserves_selection_and_never_grants_or_revokes(self):
        app=self.register();window,panel=self.open_panel()
        panel.select_row('apps',app.id);before=deepcopy(self.config)
        for _ in range(3):panel.refresh();self.wait(window)
        self.assertEqual(self.config,before);self.assertTrue(panel.app_cards[app.id].body.isVisible())

    def test_keyboard_expansion_does_not_modify_authority(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        app=self.register();window,panel=self.open_panel();card=panel.app_cards[app.id]
        before=deepcopy(self.config);card.setFocus()
        QTest.keyClick(card,Qt.Key_Space);self.assertTrue(card.body.isVisible())
        QTest.keyClick(card,Qt.Key_Return);self.assertFalse(card.body.isVisible())
        self.assertEqual(self.config,before)

    def test_tab_moves_from_navigation_to_an_accessible_action(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        window,panel=self.open_panel();panel.nav.setFocus()
        QTest.keyClick(panel.nav,Qt.Key_Tab)
        self.assertEqual(panel.focusWidget().text(),'Como funciona')

    def test_simulation_migration_requires_confirmation_and_only_changes_app_mode(self):
        window,panel=self.open_panel();before=deepcopy(self.config)
        self.assertTrue(panel.mode_banner.isVisible())
        with patch.object(panel,'confirm',return_value=False):panel.activate_real()
        self.assertEqual(before,self.config)
        with patch.object(panel,'confirm',return_value=True):panel.activate_real()
        self.wait(window)
        expected=deepcopy(before);expected.setdefault('autonomy',{})['app_opening_mode']='real'
        self.assertEqual(expected,self.config);self.assertFalse(panel.mode_banner.isVisible())

    def test_existing_pause_requires_explicit_resume_without_renewing_policy(self):
        app=self.register();version=implementation_version(self.runtime,app.as_dict())
        self.seed('open_app',app.id,version)
        policy=self.runtime.grant('open_app',app.id,version,'visual');self.runtime.pause()
        window,panel=self.open_panel();card=panel.app_cards[app.id]
        self.assertTrue(panel.pause_banner.isVisible());self.assertFalse(card.check.isChecked())
        with patch.object(panel,'confirm',return_value=False):panel.resume()
        self.assertEqual(self.store.state('paused'),'1')
        with patch.object(panel,'confirm',return_value=True):panel.resume()
        self.wait(window);self.assertTrue(card.check.isChecked())
        self.assertEqual(self.runtime.policies()[0],policy)

    def test_checkbox_cancel_grant_revoke_expire_and_persistence_error(self):
        app=self.register();version=implementation_version(self.runtime,app.as_dict())
        window,panel=self.open_panel();card=panel.app_cards[app.id]
        before=deepcopy(self.config)
        with patch.object(panel,'confirm',return_value=False):card.check.setChecked(True)
        self.wait(window);self.assertEqual(self.config,before);self.assertFalse(card.check.isChecked())
        with patch.object(panel,'confirm',return_value=True):card.check.setChecked(True)
        self.wait(window);self.assertTrue(card.check.isChecked());self.assertTrue(self.runtime.policies()[0].enabled)
        writer=self.runtime.writer;self.runtime.writer=lambda value:(_ for _ in ()).throw(OSError('Disk full'))
        card.check.setChecked(False);self.wait(window)
        self.assertTrue(card.check.isChecked());self.assertIn('Disk full',panel.feedback.text())
        self.runtime.writer=writer;card.check.setChecked(False);self.wait(window)
        self.assertFalse(self.runtime.policies()[0].enabled)
        with patch.object(panel,'confirm',return_value=True):card.check.setChecked(True)
        self.wait(window);self.now+=timedelta(days=7);panel.refresh();self.wait(window)
        self.assertFalse(card.check.isChecked());self.assertTrue(card.subtitle.text().startswith('Expirada ·'))

    def test_open_honors_effective_grant_without_individual_confirmation(self):
        from therion.autonomy.apps import CatalogLauncher
        import os
        self.runtime._update(lambda section:section.update(app_opening_mode='real'))
        app=self.register();version=implementation_version(self.runtime,app.as_dict())
        self.runtime.grant('open_app',app.id,version,'visual')
        window,panel=self.open_panel();paths=set();launched=[]
        def launch(path):launched.append(path);paths.add(os.path.normcase(os.path.realpath(path)))
        window._orchestrator.catalog_launcher=CatalogLauncher(panel.catalog,paths=lambda:paths,launch=launch)
        with patch.object(panel,'confirm',side_effect=AssertionError('Não deveria confirmar uma política vigente.')):
            panel.open_app(app.id);self.wait(window)
        self.assertEqual(launched,[app.path]);self.assertEqual(self.store.recent()[0].mode,'autonomous')

    def test_open_rechecks_expired_grant_and_cancel_clears_pending_plan(self):
        from unittest.mock import MagicMock
        app=self.register();version=implementation_version(self.runtime,app.as_dict())
        self.seed('open_app',app.id,version);self.runtime.grant('open_app',app.id,version,'visual')
        window,panel=self.open_panel();self.assertTrue(panel.app_cards[app.id].check.isChecked())
        self.now+=timedelta(days=7)
        launcher=MagicMock();window._orchestrator.catalog_launcher=launcher
        with patch.object(panel,'confirm',return_value=False) as confirm:
            panel.open_app(app.id);self.wait(window);confirm.assert_called_once()
        launcher.open.assert_not_called()
        self.assertIsNone(window._orchestrator._pending_action_plan)
        self.assertEqual(len(self.store.recent()),10)

    def test_routine_checkbox_revokes_schedule_and_policy(self):
        window=self.window();service=window._routine_service;spec=service.configure('daily_summary',8,0)
        version=service.version(spec);self.seed('daily_summary',spec.id,version)
        self.runtime.grant('daily_summary',spec.id,version,'visual');service.enable(spec,True)
        # A rotina fictícia só precisa de adapter disponível para mostrar seu estado.
        window._orchestrator.calendar_adapter=object()
        window._show_autonomy();panel=window._autonomy_panel;self.wait(window)
        card=panel.routine_cards['daily_summary'];self.assertTrue(card.check.isChecked())
        card.check.setChecked(False);self.wait(window)
        self.assertFalse(service.entries()[0].enabled);self.assertFalse(self.runtime.policies()[0].enabled)
        panel.close()

    def test_edit_routine_prefills_time_and_requires_new_authorization(self):
        from PySide6.QtCore import QTimer,QTime
        from PySide6.QtWidgets import QApplication,QTimeEdit
        window=self.window();service=window._routine_service
        spec=service.configure('daily_summary',9,35);version=service.version(spec)
        self.seed('daily_summary',spec.id,version);self.runtime.grant('daily_summary',spec.id,version,'visual')
        service.enable(spec,True);window._show_autonomy();self.wait(window)
        panel=window._autonomy_panel;observed=[]
        def edit():
            dialog=QApplication.activeModalWidget()
            control=dialog.findChild(QTimeEdit)
            observed.append(control.time().toString('HH:mm'))
            control.setTime(QTime(10,45));dialog.accept()
        QTimer.singleShot(50,edit)
        with patch.object(panel,'confirm',return_value=True):panel.configure_routine('daily_summary')
        self.wait(window)
        self.assertEqual(observed,['09:35'])
        updated=service.entries()[0]
        self.assertEqual((updated.hour,updated.minute),(10,45))
        self.assertFalse(updated.enabled);self.assertFalse(self.runtime.policies()[0].enabled)
        panel.close()

    def test_unconfigured_routine_keeps_configure_action_after_click_outside(self):
        window,panel=self.open_panel();panel.nav.setCurrentRow(1)
        panel.clear_selection()
        self.assertTrue(panel.routine_cards['review_notes'].edit.isVisible())
        self.assertFalse(panel.routine_cards['review_notes'].property('selected'))

    def test_gallery_filters_and_selects_multiple_without_executing(self):
        from therion.interface.autonomy_widgets import ApplicationGallery
        app=self.register('Cadastrado');window,panel=self.open_panel()
        rows=[dict(name='Cadastrado',path=app.path)]
        for i in range(60):
            path=self.root/f'App{i}.exe';path.write_bytes(b'fixture');rows.append(dict(name=f'App {i}',path=str(path)))
        gallery=ApplicationGallery(panel,rows);gallery.show();self.app.processEvents()
        self.assertFalse(gallery.tiles[0].check.isEnabled())
        gallery.tiles[1].check.setChecked(True);gallery.tiles[2].check.setChecked(True)
        self.assertEqual(gallery.count.text(),'2 selecionado(s)')
        gallery.search.setText('App 59');self.app.processEvents()
        self.assertEqual(sum(not tile.isHidden() for tile in gallery.tiles),1)
        gallery.search.setText('');self.assertEqual(sum(tile.check.isChecked() for tile in gallery.tiles),2)
        self.assertEqual(len(self.store.recent()),0);gallery.close()

    def test_cancel_during_batch_validation_prevents_publication(self):
        from therion.interface.autonomy_widgets import BatchReview
        import threading
        window,panel=self.open_panel();path=self.root/'New.exe';path.write_bytes(b'fixture')
        dialog=BatchReview(panel,[dict(name='Novo',path=str(path))]);dialog.show()
        gate=threading.Event();preview=panel.catalog.preview_many
        def delayed(rows):gate.wait(3);return preview(rows)
        with patch.object(panel.catalog,'preview_many',side_effect=delayed):
            dialog.publish();self.assertEqual(dialog.phase,'validating')
            dialog.reject();gate.set();self.wait(window)
        self.assertEqual(panel.catalog.entries(),[])
        self.assertFalse(dialog.isVisible())

    def test_batch_publication_waits_for_confirmation_before_closing(self):
        from therion.interface.autonomy_widgets import BatchReview
        import threading,time
        window,panel=self.open_panel();path=self.root/'New.exe';path.write_bytes(b'fixture')
        dialog=BatchReview(panel,[dict(name='Novo',path=str(path))]);dialog.show()
        gate=threading.Event();commit=panel.catalog.commit_many
        def delayed(proposal):gate.wait(3);return commit(proposal)
        with patch.object(panel.catalog,'commit_many',side_effect=delayed):
            dialog.publish()
            deadline=time.monotonic()+2
            while dialog.phase!='publishing' and time.monotonic()<deadline:
                self.app.processEvents();time.sleep(.01)
            try:
                self.assertEqual(dialog.phase,'publishing');dialog.reject()
                self.assertTrue(dialog.isVisible());self.assertFalse(dialog.cancel.isEnabled())
                self.assertTrue(dialog.fields[0][1].isReadOnly())
            finally:gate.set()
            self.wait(window)
        self.assertEqual(len(panel.catalog.entries()),1);self.assertFalse(dialog.isVisible())

    def test_memory_checkbox_cancel_grant_expire_renew_and_revoke(self):
        window,panel=self.open_panel()
        target=str(self.root/'Rascunhos');version='fixture-memory-scope'
        self.runtime._update(lambda section:section.update(procedure_memory=dict(root=target)))
        self.seed('remember_procedure',target,version)
        with patch.object(panel.procedures,'scope',return_value=(target,version,None)):
            panel.refresh();self.wait(window)
            before=deepcopy(self.config)
            with patch.object(panel,'confirm',return_value=False):panel.memory_check.setChecked(True)
            self.wait(window);self.assertEqual(before,self.config)
            with patch.object(panel,'confirm',return_value=True):panel.memory_check.setChecked(True)
            self.wait(window);self.assertTrue(panel.memory_check.isChecked())
            self.now+=timedelta(days=7);panel.refresh();self.wait(window)
            self.assertFalse(panel.memory_check.isChecked())
            with patch.object(panel,'confirm',return_value=True):panel.memory_check.setChecked(True)
            self.wait(window);self.assertTrue(panel.memory_check.isChecked())
            panel.memory_check.setChecked(False);self.wait(window)
            self.assertFalse(self.runtime.policies()[0].enabled)

    def test_memory_candidates_expose_individual_review_action(self):
        app=self.register();self.seed('open_app',app.id,implementation_version(self.runtime,app.as_dict()))
        window,panel=self.open_panel();panel.nav.setCurrentRow(2);self.app.processEvents()
        self.assertTrue(panel.memory_cards)
        card=next(iter(panel.memory_cards.values()))
        self.assertTrue(card.body.isVisible())
        self.assertEqual(card.actions.itemAt(0).widget().text(),'Revisar e guardar')

    def test_windows_buttons_keep_confirmation_and_backend_routing(self):
        from unittest.mock import MagicMock
        from PySide6.QtWidgets import QPushButton
        window,panel=self.open_panel();panel.nav.setCurrentRow(3)
        enable=next(b for b in panel.findChildren(QPushButton) if b.text()=='Habilitar')
        disable=next(b for b in panel.findChildren(QPushButton) if b.text()=='Desabilitar')
        shortcut=MagicMock()
        with patch('therion.interface.autonomy_panel.StartupShortcut',return_value=shortcut):
            with patch.object(panel,'confirm',return_value=False):enable.click()
            shortcut.set_enabled.assert_not_called()
            with patch.object(panel,'confirm',return_value=True):enable.click();self.wait(window)
            with patch.object(panel,'confirm',return_value=True):disable.click();self.wait(window)
        self.assertEqual([call.args for call in shortcut.set_enabled.call_args_list],[(True,),(False,)])

    def test_small_window_has_no_removed_buttons_or_clipped_row_controls(self):
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import QPoint
        app=self.register('Aplicativo '+('muito longo '*7))
        window,panel=self.open_panel();panel.resize(860,640);self.app.processEvents()
        names={b.text() for b in panel.findChildren(QPushButton)}
        self.assertFalse(names&{'Revogar','Autorizar por 7 dias','Usar simulação','Importar Obsidian existente',
            'Remover cadastro','Pausar toda autonomia','Retomar políticas vigentes','Atualizar'})
        card=panel.app_cards[app.id]
        for control in (card.check,card.remove):
            point=control.mapTo(panel,QPoint(control.width(),control.height()))
            self.assertLessEqual(point.x(),panel.width());self.assertLessEqual(point.y(),panel.height())


if __name__=='__main__':unittest.main()
