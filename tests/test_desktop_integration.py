"""Testes de integracao da interface desktop com configuracao."""

import sys
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
import unittest


class TestDesktopIntegration(unittest.TestCase):
    """Testes de integracao desktop + config (sem GUI real)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="therion_desktop_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_main_with_config(self, config_data: dict) -> tuple[bool, MagicMock]:
        with patch("therion.interface.desktop.load_config", return_value=config_data):
            with patch("therion.interface.desktop.QApplication") as mock_app_class:
                with patch("therion.interface.desktop.MainWindow") as mock_window_class:
                    mock_app = MagicMock()
                    mock_app.exec.return_value = 0
                    mock_app_class.return_value = mock_app
                    mock_window = MagicMock()
                    mock_window_class.return_value = mock_window
                    from therion.interface.desktop import main
                    main()
                    return mock_window.show.called, mock_window

    def test_start_minimized_false_mostra_janela(self) -> None:
        config = {"ui": {"start_minimized": False}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called)

    def test_start_minimized_true_nao_mostra_janela(self) -> None:
        config = {"ui": {"start_minimized": True}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertFalse(show_called)

    def test_config_ausente_usa_fallback_false(self) -> None:
        config = {"ui": {}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called)

    def test_config_ui_ausente_usa_fallback_false(self) -> None:
        config = {"aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called)

    def test_load_config_consumido_corretamente(self) -> None:
        config = {"ui": {"start_minimized": True}, "aliases": {}, "allowed_apps": []}
        with patch("therion.interface.desktop.load_config", return_value=config) as mock_load:
            with patch("therion.interface.desktop.QApplication") as mock_app_class:
                with patch("therion.interface.desktop.MainWindow"):
                    mock_app = MagicMock()
                    mock_app.exec.return_value = 0
                    mock_app_class.return_value = mock_app
                    from therion.interface.desktop import main
                    main()
                    mock_load.assert_called_once()


class TestDesktopOrchestratorIntegration(unittest.TestCase):
    """Testes de integracao desktop com Orchestrator (sem GUI real)."""

    _qapp = None

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        import sys
        if QApplication.instance() is None:
            cls._qapp = QApplication(sys.argv)
        else:
            cls._qapp = QApplication.instance()

    def _create_window(self):
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._history.toPlainText.return_value = ""
                window._input = MagicMock()
                window._input.text.return_value = ""
                window._send_button = MagicMock()
                window._orchestrator = MagicMock()
                window._confirmation_handler = MagicMock()
                window._append = MagicMock()
                window._pending_plan = None
                return window

    def test_orchestrator_instantiated(self) -> None:
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        with patch('therion.interface.desktop.Orchestrator') as mock_orch:
            with patch.object(MainWindow, '_setup_ui'):
                with patch.object(MainWindow, '_setup_tray'):
                    window = MainWindow(mock_app)
                    mock_orch.assert_called_once_with(simulate=True)

    def test_orchestrator_default_simulate_true(self) -> None:
        """Config padrão (sem runtime) deve resultar em simulate=True."""
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        with patch('therion.interface.desktop.Orchestrator') as mock_orch:
            with patch.object(MainWindow, '_setup_ui'):
                with patch.object(MainWindow, '_setup_tray'):
                    window = MainWindow(mock_app, config={})
                    mock_orch.assert_called_once_with(simulate=True)

    def test_orchestrator_real_actions_disabled_simulate_true(self) -> None:
        """real_actions_enabled=False deve resultar em simulate=True."""
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        config = {"runtime": {"real_actions_enabled": False}}
        with patch('therion.interface.desktop.Orchestrator') as mock_orch:
            with patch.object(MainWindow, '_setup_ui'):
                with patch.object(MainWindow, '_setup_tray'):
                    window = MainWindow(mock_app, config=config)
                    mock_orch.assert_called_once_with(simulate=True)

    def test_orchestrator_real_actions_enabled_simulate_false(self) -> None:
        """real_actions_enabled=True deve resultar em simulate=False."""
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        config = {"runtime": {"real_actions_enabled": True}}
        with patch('therion.interface.desktop.Orchestrator') as mock_orch:
            with patch.object(MainWindow, '_setup_ui'):
                with patch.object(MainWindow, '_setup_tray'):
                    window = MainWindow(mock_app, config=config)
                    mock_orch.assert_called_once_with(simulate=False)

    def test_widgets_exist(self) -> None:
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui') as mock_ui:
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                mock_ui.assert_called_once()

    def test_send_button_triggers_flow(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._append.assert_any_call("Você", "liste meus aliases")
        window._append.assert_any_call("Therion", "Nenhum alias cadastrado.")

    def test_enter_sends_command(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._input.clear.assert_called()

    def test_empty_input_not_sent(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "   "
        window._send_command()
        window._orchestrator.process_command.assert_not_called()
        window._append.assert_not_called()

    def test_command_appears_in_history(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "abra o Obsidian"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Comando executado.",
            plan=None,
        )
        window._send_command()
        window._append.assert_any_call("Você", "abra o Obsidian")

    def test_response_appears_in_history(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._append.assert_any_call("Therion", "Nenhum alias cadastrado.")

    def test_awaiting_confirmation_stores_plan(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "abra o Obsidian"
        mock_plan = MagicMock()
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation",
            message="Continuar? [s/n]",
            plan=mock_plan,
        )
        window._send_command()
        self.assertEqual(window._pending_plan, mock_plan)

    def test_sim_executes_confirm_and_execute(self) -> None:
        window = self._create_window()
        mock_plan = MagicMock()
        window._pending_plan = mock_plan
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="executed_simulated",
            message="Comando executado em modo simulado.",
        )
        window._send_command()
        window._orchestrator.confirm_and_execute.assert_called_once_with(
            mock_plan, confirmed=True
        )

    def test_nao_executes_confirm_and_execute(self) -> None:
        window = self._create_window()
        mock_plan = MagicMock()
        window._pending_plan = mock_plan
        window._input.text.return_value = "nao"
        window._confirmation_handler.evaluate_response.return_value = False
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="cancelled",
            message="Operacao cancelada.",
        )
        window._send_command()
        window._orchestrator.confirm_and_execute.assert_called_once_with(
            mock_plan, confirmed=False
        )

    def test_positive_confirmation_clears_plan(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        self.assertIsNone(window._pending_plan)

    def test_negative_confirmation_clears_plan(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "nao"
        window._confirmation_handler.evaluate_response.return_value = False
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        self.assertIsNone(window._pending_plan)

    def test_ambiguous_response_maintains_plan(self) -> None:
        window = self._create_window()
        mock_plan = MagicMock()
        window._pending_plan = mock_plan
        window._input.text.return_value = "talvez"
        window._confirmation_handler.evaluate_response.return_value = None
        window._send_command()
        self.assertEqual(window._pending_plan, mock_plan)

    def test_ambiguous_response_clears_input(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "talvez"
        window._confirmation_handler.evaluate_response.return_value = None
        window._send_command()
        window._input.clear.assert_called()

    def test_confirmation_response_appears_in_history(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        window._append.assert_any_call("Você", "sim")

    def test_after_confirmation_returns_to_normal(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        self.assertIsNone(window._pending_plan)
        window._input.text.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._orchestrator.process_command.assert_called_with("liste meus aliases")

    def test_exception_in_process_command(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "comando problematico"
        window._orchestrator.process_command.side_effect = RuntimeError("Erro")
        window._send_command()
        window._append.assert_any_call(
            "Therion", "Ocorreu um erro inesperado ao processar o comando."
        )

    def test_exception_in_confirm_and_execute(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.side_effect = RuntimeError("Erro")
        window._send_command()
        window._append.assert_any_call(
            "Therion", "Ocorreu um erro inesperado ao processar a confirmação."
        )

    def test_exception_in_confirm_clears_plan(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.text.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.side_effect = RuntimeError("Erro")
        window._send_command()
        self.assertIsNone(window._pending_plan)

    def test_simulate_true_persists(self) -> None:
        from therion.interface.desktop import MainWindow

        mock_app = MagicMock()
        with patch('therion.interface.desktop.Orchestrator') as mock_orch:
            with patch.object(MainWindow, '_setup_ui'):
                with patch.object(MainWindow, '_setup_tray'):
                    window = MainWindow(mock_app)
                    mock_orch.assert_called_with(simulate=True)

    def test_internal_flows_not_duplicated(self) -> None:
        window = self._create_window()
        window._input.text.return_value = "adicione alias X para Y"
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation",
            message="Qual o alvo?",
            plan=None,
        )
        window._send_command()
        window._orchestrator.process_command.assert_called_once_with(
            "adicione alias X para Y"
        )
        self.assertIsNone(window._pending_plan)


if __name__ == "__main__":
    unittest.main()
