"""Painel Qt com configuração e estado fictícios; nenhuma ativação pessoal."""
import time
import unittest
from unittest.mock import patch,MagicMock
from pathlib import Path

from tests import test_autonomy_v4 as fixtures


class PanelTests(unittest.TestCase):
    setUp=fixtures.AutonomyTests.setUp
    tearDown=fixtures.AutonomyTests.tearDown
    write=fixtures.AutonomyTests.write
    seed=fixtures.AutonomyTests.seed

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def window(self):
        from therion.interface.desktop import MainWindow
        with patch.object(MainWindow,'_setup_tray'):
            window=MainWindow(self.app,self.config,autonomy_runtime=self.runtime,log_dir=str(self.root/'logs'))
        window._v4_timer.stop();window._memory_timer.stop()
        self.addCleanup(lambda:window._orchestrator.close())
        self.addCleanup(lambda:window.deleteLater())
        return window

    def wait(self,window):
        deadline=time.monotonic()+8
        idle=0
        while time.monotonic()<deadline:
            self.app.processEvents();time.sleep(0.01)
            if window._v4_worker is None:
                idle+=1
                if idle>=4:return
            else:idle=0
        self.fail('O trabalho Qt não terminou.')

    def test_panel_has_four_pilots_without_granting_permissions(self):
        window=self.window();window._show_autonomy();panel=window._autonomy_panel
        self.wait(window)
        self.assertEqual(panel.nav.count(),4)
        self.assertEqual(self.runtime.policies(),[])
        panel.close();window._pause_autonomy()
        self.assertEqual(self.store.state('paused'),'1')

    def test_panel_worker_can_chain_next_job_without_losing_result(self):
        window=self.window();window._show_autonomy();panel=window._autonomy_panel
        observed=[]
        panel.job(lambda:'first',lambda value:panel.job(lambda:'second',observed.append))
        self.wait(window)
        self.assertEqual(observed,['second'])
        panel.close()

    def test_panel_app_test_is_simulated_and_supervised(self):
        from therion.autonomy.apps import ApplicationCatalog
        path=self.root/'Editor.exe';path.write_bytes(b'fixture')
        app=ApplicationCatalog(self.runtime).register('Editor',str(path))
        window=self.window();window._show_autonomy();panel=window._autonomy_panel
        self.wait(window)
        with patch.object(panel,'confirm',return_value=True):
            panel.open_app(app.id);self.wait(window)
        rows=self.store.recent();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0].mode,'simulation')
        self.assertIn('Simulei',panel.feedback.text())
        panel.close()

    def test_embedded_autonomy_keeps_conversation_and_uses_internal_details(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        window=self.window();window._select_interface('constellation',persist=False)
        window.show();self.app.processEvents()
        with patch.object(window,'_end_conversation') as end:
            window._show_autonomy();end.assert_not_called()
        panel=window._autonomy_panel;self.wait(window)
        d=window._dashboard
        self.assertIs(panel,d.surfaces.views['autonomy']);self.assertFalse(panel.isWindow())
        self.assertEqual(self.runtime.policies(),[])
        answers=[]
        def cancel():
            dialog=d.surfaces.modals[-1][0]
            answers.append(not dialog.isWindow());dialog.reject()
        QTimer.singleShot(0,cancel)
        self.assertFalse(panel.confirm('Exemplo fictício'))
        self.assertEqual(answers,[True]);self.assertEqual(self.runtime.policies(),[])
        d.workspace.panels['autonomy'].dismiss();self.app.processEvents()
        self.assertFalse(panel.timer.isActive())
        d.cancel()
        for worker in list(d.workers.values()):worker.wait(3000)
        window._closing=True;window.close();QApplication.processEvents()

    def test_native_panel_snapshot(self):
        window=self.window();window._show_autonomy();panel=window._autonomy_panel
        self.wait(window)
        destination=Path(__file__).resolve().parents[1]/'tmp'/'v4-tests'/'panel.png'
        self.assertTrue(panel.grab().save(str(destination)))
        panel.close()

    def test_declining_routine_grant_never_enables_existing_policy(self):
        window=self.window()
        service=window._routine_service
        spec=service.configure('daily_summary',8,0)
        version=service.version(spec)
        self.seed('daily_summary',spec.id,version)
        self.runtime.grant('daily_summary',spec.id,version,'Fixture visual')
        window._show_autonomy();panel=window._autonomy_panel
        self.wait(window)
        with patch.object(panel,'confirm',return_value=False):panel.toggle_routine('daily_summary',True)
        self.wait(window)
        self.assertFalse(service.entries()[0].enabled)
        panel.close()


if __name__=='__main__':unittest.main()
