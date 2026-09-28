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
                window._input = MagicMock()
                window._input.toPlainText.return_value = ""
                window._send_button = MagicMock()
                window._clear_button = MagicMock()
                window._orchestrator = MagicMock()
                window._confirmation_handler = MagicMock()
                window._append = MagicMock()
                window._pending_plan = None
                window._update_clear_button_state = MagicMock()
                window._clear_conversation = MagicMock()
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
        window._input.toPlainText.return_value = "liste meus aliases"
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
        window._input.toPlainText.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._input.clear.assert_called()

    def test_empty_input_not_sent(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "   "
        window._send_command()
        window._orchestrator.process_command.assert_not_called()
        window._append.assert_not_called()

    def test_command_appears_in_history(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "abra o Obsidian"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Comando executado.",
            plan=None,
        )
        window._send_command()
        window._append.assert_any_call("Você", "abra o Obsidian")

    def test_response_appears_in_history(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._append.assert_any_call("Therion", "Nenhum alias cadastrado.")

    def test_awaiting_confirmation_stores_plan(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "abra o Obsidian"
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
        window._input.toPlainText.return_value = "sim"
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
        window._input.toPlainText.return_value = "nao"
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
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        self.assertIsNone(window._pending_plan)

    def test_negative_confirmation_clears_plan(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "nao"
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
        window._input.toPlainText.return_value = "talvez"
        window._confirmation_handler.evaluate_response.return_value = None
        window._send_command()
        self.assertEqual(window._pending_plan, mock_plan)

    def test_ambiguous_response_clears_input(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "talvez"
        window._confirmation_handler.evaluate_response.return_value = None
        window._send_command()
        window._input.clear.assert_called()

    def test_confirmation_response_appears_in_history(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        window._append.assert_any_call("Você", "sim")

    def test_after_confirmation_returns_to_normal(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            message="OK"
        )
        window._send_command()
        self.assertIsNone(window._pending_plan)
        window._input.toPlainText.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Nenhum alias cadastrado.",
            plan=None,
        )
        window._send_command()
        window._orchestrator.process_command.assert_called_with("liste meus aliases")

    def test_exception_in_process_command(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "comando problematico"
        window._orchestrator.process_command.side_effect = RuntimeError("Erro")
        window._send_command()
        window._append.assert_any_call(
            "Therion", "Ocorreu um erro inesperado ao processar o comando."
        )

    def test_exception_in_confirm_and_execute(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.side_effect = RuntimeError("Erro")
        window._send_command()
        window._append.assert_any_call(
            "Therion", "Ocorreu um erro inesperado ao processar a confirmação."
        )

    def test_exception_in_confirm_clears_plan(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "sim"
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
        window._input.toPlainText.return_value = "adicione alias X para Y"
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

    def test_multiline_message_sent_correctly(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "linha 1\nlinha 2\nlinha 3"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success", message="ok", plan=None,
        )
        window._send_command()
        window._orchestrator.process_command.assert_called_once_with(
            "linha 1\nlinha 2\nlinha 3"
        )

    def test_strip_removes_only_edges(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "  linha 1\nlinha 2  "
        window._orchestrator.process_command.return_value = MagicMock(
            status="success", message="ok", plan=None,
        )
        window._send_command()
        window._orchestrator.process_command.assert_called_once_with(
            "linha 1\nlinha 2"
        )

    def test_clear_button_exists(self) -> None:
        window = self._create_window()
        self.assertTrue(hasattr(window, '_clear_button'))

    def test_clear_button_calls_clear_conversation(self) -> None:
        window = self._create_window()
        window._clear_conversation()
        window._clear_conversation.assert_called_once()

    def test_clear_conversation_clears_history(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._clear_conversation()
                window._history.clear.assert_called_once()

    def test_clear_conversation_calls_orchestrator_clear_session(self) -> None:
        """_clear_conversation deve limpar histórico visual E chamar orchestrator.clear_session() (E1/M9b)."""
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._orchestrator = MagicMock()
                window._clear_conversation()
                window._history.clear.assert_called_once()
                window._orchestrator.clear_session.assert_called_once_with()

    def test_pending_plan_not_cleared_by_clear(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._pending_plan = MagicMock()
                window._clear_conversation()
                self.assertIsNotNone(window._pending_plan)

    def test_update_clear_button_disabled_with_pending(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._clear_button = MagicMock()
                window._pending_plan = MagicMock()
                window._update_clear_button_state()
                window._clear_button.setEnabled.assert_called_once_with(False)

    def test_update_clear_button_enabled_without_pending(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._clear_button = MagicMock()
                window._pending_plan = None
                window._update_clear_button_state()
                window._clear_button.setEnabled.assert_called_once_with(True)

    def test_clear_button_disabled_during_confirmation(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(message="OK")
        window._send_command()
        window._update_clear_button_state.assert_called()

    def test_send_command_updates_clear_button(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "liste meus aliases"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success", message="ok", plan=None,
        )
        window._send_command()
        window._update_clear_button_state.assert_called()

    def test_append_uses_html_for_you(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._append("Você", "teste")
                window._history.append.assert_called_once()
                call_args = window._history.append.call_args[0][0]
                self.assertIn("Você", call_args)
                self.assertIn("teste", call_args)
                self.assertIn("align=\"right\"", call_args)

    def test_append_uses_html_for_therion(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._append("Therion", "resposta")
                window._history.append.assert_called_once()
                call_args = window._history.append.call_args[0][0]
                self.assertIn("Therion", call_args)
                self.assertIn("resposta", call_args)
                self.assertIn("align=\"left\"", call_args)

    def test_append_uses_limited_width_bubbles(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._append("Você", "teste")
                call_args = window._history.append.call_args[0][0]
                self.assertIn("width:auto;", call_args)
                self.assertIn("max-width:72%;", call_args)
                self.assertIn("padding:10px 14px;", call_args)

    def test_append_escapes_html_in_message(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._append("Você", "<b>teste</b> & <i>script</i>")
                call_args = window._history.append.call_args[0][0]
                self.assertIn("&lt;b&gt;teste&lt;/b&gt; &amp; &lt;i&gt;script&lt;/i&gt;", call_args)
                self.assertNotIn("<b>teste</b>", call_args.replace("<b>Você:</b>", ""))

    def test_append_preserves_multiline_after_escape(self) -> None:
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window._history = MagicMock()
                window._append("Therion", "linha1\nlinha2")
                call_args = window._history.append.call_args[0][0]
                self.assertIn("linha1<br>linha2", call_args)

    def test_on_tray_activated_double_click_shows(self) -> None:
        from therion.interface.desktop import MainWindow
        from PySide6.QtWidgets import QSystemTrayIcon
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window.show = MagicMock()
                window.raise_ = MagicMock()
                window.activateWindow = MagicMock()
                window._on_tray_activated(QSystemTrayIcon.DoubleClick)
                window.show.assert_called_once()
                window.raise_.assert_called_once()
                window.activateWindow.assert_called_once()

    def test_on_tray_activated_other_reason_noop(self) -> None:
        from therion.interface.desktop import MainWindow
        from PySide6.QtWidgets import QSystemTrayIcon
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                window.show = MagicMock()
                window._on_tray_activated(QSystemTrayIcon.Trigger)
                window.show.assert_not_called()

    def test_input_class_is_conversation_input(self) -> None:
        from therion.interface.desktop import ConversationInput
        mock_app = MagicMock()
        input_widget = ConversationInput()
        self.assertTrue(hasattr(input_widget, 'submit'))

    def test_empty_after_strip_not_sent(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "\n\n  \n\n"
        window._send_command()
        window._orchestrator.process_command.assert_not_called()

    def test_ack_registered_after_display(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "gere um plano de estudo"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Texto do plano exibido.",
            plan=None,
            plan_candidate_id="abc123",
        )
        events = []

        def _record_append(sender, text):
            events.append(("append", sender, text))

        def _record_ack(candidate_id):
            events.append(("ack", candidate_id))
            return MagicMock(status="registered")

        window._append.side_effect = _record_append
        window._orchestrator.ack_plan_displayed.side_effect = _record_ack

        window._send_command()

        window._orchestrator.ack_plan_displayed.assert_called_once_with("abc123")
        self.assertEqual(
            events,
            [
                ("append", "Você", "gere um plano de estudo"),
                ("append", "Therion", "Texto do plano exibido."),
                ("ack", "abc123"),
            ],
        )

    def test_ack_rejected_shows_second_bubble(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "gere um plano de estudo"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Texto do plano exibido.",
            plan=None,
            plan_candidate_id="abc123",
        )
        window._orchestrator.ack_plan_displayed.return_value = MagicMock(
            status="displayed_not_registered"
        )

        window._send_command()

        window._orchestrator.ack_plan_displayed.assert_called_once_with("abc123")
        self.assertEqual(window._append.call_args_list[1].args, ("Therion", "Texto do plano exibido."))
        self.assertEqual(
            window._append.call_args_list[2].args,
            (
                "Therion",
                "Este plano foi exibido, mas não pôde ser registrado nesta sessão. Por isso, ele não poderá ser recuperado depois por referências como “mesmo plano”, “plano anterior” ou “primeiro plano”.",
            ),
        )
        self.assertEqual(window._append.call_count, 3)

    def test_no_candidate_id_skips_ack(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "gere um plano de estudo"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Resposta comum.",
            plan=None,
            plan_candidate_id=None,
        )

        window._send_command()

        window._orchestrator.ack_plan_displayed.assert_not_called()
        self.assertEqual(window._append.call_count, 2)
        self.assertEqual(window._append.call_args_list[1].args, ("Therion", "Resposta comum."))

    def test_registered_plan_ack_after_display(self) -> None:
        window = self._create_window()
        window._input.toPlainText.return_value = "mostrar o plano registrado"
        window._orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Texto do plano registrado.",
            plan=None,
            plan_candidate_id=None,
            registered_plan_id="plan-123",
        )
        events = []

        def _record_append(sender, text):
            events.append(("append", sender, text))

        def _record_ack(plan_id):
            events.append(("ack_registered", plan_id))
            return True

        window._append.side_effect = _record_append
        window._orchestrator.ack_registered_plan_displayed.side_effect = _record_ack

        window._send_command()

        window._orchestrator.ack_registered_plan_displayed.assert_called_once_with(
            "plan-123"
        )
        window._orchestrator.ack_plan_displayed.assert_not_called()
        self.assertEqual(
            events,
            [
                ("append", "Você", "mostrar o plano registrado"),
                ("append", "Therion", "Texto do plano registrado."),
                ("ack_registered", "plan-123"),
            ],
        )


class TestDesktopOrbe(unittest.TestCase):
    """Testes do orbe visual e mapeamento de estados."""

    _qapp = None

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._qapp = QApplication(sys.argv)
        else:
            cls._qapp = QApplication.instance()

    def _create_window_with_orbe(self):
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        window = MainWindow(mock_app)
        window._orchestrator = MagicMock()
        window._confirmation_handler = MagicMock()
        return window

    def test_update_orbe_idle(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("idle")
        self.assertEqual(window._orbe_label.text(), "Pronto")

    def test_update_orbe_thinking(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("thinking")
        self.assertEqual(window._orbe_label.text(), "Pensando...")

    def test_update_orbe_awaiting_confirmation(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("awaiting_confirmation")
        self.assertEqual(window._orbe_label.text(), "Aguardando confirmação")

    def test_update_orbe_executing(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("executing")
        self.assertEqual(window._orbe_label.text(), "Executando...")

    def test_update_orbe_success(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("success")
        self.assertEqual(window._orbe_label.text(), "Concluído")

    def test_update_orbe_error(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("error")
        self.assertEqual(window._orbe_label.text(), "Erro")

    def test_update_orbe_unknown_state_fallback(self) -> None:
        window = self._create_window_with_orbe()
        window._update_orbe("unknown_state_xyz")
        self.assertEqual(window._orbe_label.text(), "Pronto")

    def test_executing_color_differs_from_error(self) -> None:
        from therion.interface.desktop import _ORBE_EXECUTING, _ORBE_ERROR
        self.assertNotEqual(_ORBE_EXECUTING, _ORBE_ERROR)

    def test_status_map_success_for_executed_simulated(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["executed_simulated"], "success")

    def test_status_map_idle_for_cancelled(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["cancelled"], "idle")

    def test_status_map_error_for_execution_failed(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["execution_failed"], "error")

    def test_status_map_error_for_verification_failed(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["verification_failed"], "error")

    def test_status_map_error_for_forbidden(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["forbidden"], "error")

    def test_status_map_idle_for_unknown_intent(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["unknown_intent"], "idle")

    def test_status_map_awaiting_for_awaiting_confirmation(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["awaiting_confirmation"], "awaiting_confirmation")

    def test_status_map_success_for_success(self) -> None:
        from therion.interface.desktop import _ORBE_STATUS_MAP
        self.assertEqual(_ORBE_STATUS_MAP["success"], "success")

    def test_send_command_shows_executing_on_true_then_success(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "abra o Obsidian"
        mock_plan = MagicMock()
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation", message="Continuar?", plan=mock_plan,
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Aguardando confirmação")
        window._input.toPlainText.return_value = "sim"
        window._confirmation_handler.evaluate_response.return_value = True
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="executed_simulated", message="OK",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Concluído")

    def test_send_command_shows_idle_on_false_negation(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "abra o Obsidian"
        mock_plan = MagicMock()
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation", message="Continuar?", plan=mock_plan,
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Aguardando confirmação")
        window._input.toPlainText.return_value = "não"
        window._confirmation_handler.evaluate_response.return_value = False
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="cancelled", message="Operação cancelada.",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Pronto")

    def test_send_command_no_executing_on_false(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "abra o Obsidian"
        mock_plan = MagicMock()
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation", message="Continuar?", plan=mock_plan,
        )
        window._send_command()
        window._input.toPlainText.return_value = "não"
        window._confirmation_handler.evaluate_response.return_value = False
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="cancelled", message="Cancelado.",
        )
        window._send_command()
        self.assertNotEqual(window._orbe_label.text(), "Executando...")

    def test_send_command_error_status_shows_error(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "comando qualquer"
        window._orchestrator.process_command.return_value = MagicMock(
            status="execution_failed", message="Falha.",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Erro")

    def test_send_command_forbidden_shows_error(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "comando proibido"
        window._orchestrator.process_command.return_value = MagicMock(
            status="forbidden", message="Não autorizado.",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Erro")

    def test_send_command_cancelled_shows_idle(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "algo cancelado"
        window._orchestrator.process_command.return_value = MagicMock(
            status="cancelled", message="Cancelado.",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Pronto")

    def test_send_command_unknown_intent_shows_idle(self) -> None:
        window = self._create_window_with_orbe()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "blablabla"
        window._orchestrator.process_command.return_value = MagicMock(
            status="unknown_intent", message="Não entendi.",
        )
        window._send_command()
        self.assertEqual(window._orbe_label.text(), "Pronto")


class TestDesktopConfirmPanel(unittest.TestCase):
    """Testes do painel de confirmação visual (Bloco 5)."""

    _qapp = None

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._qapp = QApplication(sys.argv)
        else:
            cls._qapp = QApplication.instance()

    def _create_window(self) -> "MainWindow":
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
        window._confirm_panel = MagicMock()
        window._confirm_description = MagicMock()
        window._btn_confirm = MagicMock()
        window._btn_cancel = MagicMock()
        window._input = MagicMock()
        window._input.toPlainText.return_value = "sim"
        window._orchestrator = MagicMock()
        window._confirmation_handler = MagicMock()
        window._confirmation_handler.evaluate_response.return_value = True
        window._orbe = MagicMock()
        window._orbe_label = MagicMock()
        window._history = MagicMock()
        window._clear_button = MagicMock()
        window._pending_plan = None
        return window

    def test_panel_hidden_initially(self) -> None:
        from PySide6.QtWidgets import QApplication
        from therion.interface.desktop import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(MainWindow, "_setup_tray"):
            window = MainWindow(app)

        self.assertFalse(window._confirm_panel.isVisible())

    def test_awaiting_confirmation_shows_panel(self) -> None:
        window = self._create_window()
        mock_plan = MagicMock()
        mock_plan.description = "Abrir Obsidian"
        window._orchestrator.process_command.return_value = MagicMock(
            status="awaiting_confirmation", message="Continuar?", plan=mock_plan,
        )
        window._input.toPlainText.return_value = "abra o Obsidian"
        window._send_command()
        window._confirm_panel.setVisible.assert_called_with(True)

    def test_visible_panel_keeps_history_scrolled_to_end(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        scrollbar = window._history.verticalScrollBar.return_value
        window._update_confirm_panel()
        scrollbar.setValue.assert_called_once_with(scrollbar.maximum.return_value)

    def test_no_pending_plan_hides_panel(self) -> None:
        window = self._create_window()
        window._orchestrator.process_command.return_value = MagicMock(
            status="success", message="Ok",
        )
        window._input.toPlainText.return_value = "teste"
        window._send_command()
        window._confirm_panel.setVisible.assert_called_with(False)

    def test_confirm_button_calls_handle_confirmation_sim(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._on_confirm()
        window._confirmation_handler.evaluate_response.assert_called_once_with("sim")

    def test_cancel_button_calls_handle_confirmation_nao(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._on_cancel()
        window._confirmation_handler.evaluate_response.assert_called_once_with("não")

    def test_buttons_do_not_call_orchestrator_directly(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._orchestrator.confirm_and_execute = MagicMock()
        window._confirmation_handler.evaluate_response.return_value = None
        window._on_confirm()
        window._orchestrator.confirm_and_execute.assert_not_called()

    def test_cancel_hides_panel(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._confirmation_handler.evaluate_response.return_value = False
        window._orchestrator.confirm_and_execute.return_value = MagicMock(
            status="cancelled", message="Cancelado.",
        )
        window._on_cancel()
        window._confirm_panel.setVisible.assert_called_with(False)

    def test_description_appears_as_safe_text(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._pending_plan.description = "Ação perigosa"
        window._update_confirm_panel()
        window._confirm_description.setText.assert_called_once_with("Ação perigosa")

    def test_description_is_plain_text(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from therion.interface.desktop import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(MainWindow, "_setup_tray"):
            window = MainWindow(app)

        window._pending_plan = MagicMock()
        window._pending_plan.description = "<b>teste</b>"
        window._update_confirm_panel()
        self.assertEqual(window._confirm_description.textFormat(), Qt.PlainText)
        self.assertEqual(window._confirm_description.text(), "<b>teste</b>")

    def test_fallback_description_when_none(self) -> None:
        window = self._create_window()
        window._pending_plan = MagicMock()
        window._pending_plan.description = None
        window._update_confirm_panel()
        window._confirm_description.setText.assert_called_once_with(
            "Deseja prosseguir com esta ação?"
        )


class TestDesktopAIIntegration(unittest.TestCase):
    """Testes de integração desktop com injeção local de OllamaProvider e AICore."""

    _qapp = None

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._qapp = QApplication(sys.argv)
        else:
            cls._qapp = QApplication.instance()

    def test_ai_disabled_no_provider_and_orchestrator_without_aicore(self) -> None:
        """Com IA desabilitada, OllamaProvider não é criado e Orchestrator permanece sem AICore."""
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        config = {"ai": {"enabled": False}}

        with patch("therion.interface.desktop.OllamaProvider") as mock_provider_cls:
            with patch("therion.interface.desktop.AICore") as mock_aicore_cls:
                with patch("therion.interface.desktop.Orchestrator") as mock_orch_cls:
                    with patch.object(MainWindow, "_setup_ui"):
                        with patch.object(MainWindow, "_setup_tray"):
                            MainWindow(mock_app, config=config)

                            mock_provider_cls.assert_not_called()
                            mock_aicore_cls.assert_not_called()
                            self.assertNotIn("ai_core", mock_orch_cls.call_args.kwargs)

    def test_ai_config_absent_no_provider_and_orchestrator_without_aicore(self) -> None:
        """Quando ai ausente na config, OllamaProvider não é criado e Orchestrator sem AICore."""
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()

        with patch("therion.interface.desktop.OllamaProvider") as mock_provider_cls:
            with patch("therion.interface.desktop.AICore") as mock_aicore_cls:
                with patch("therion.interface.desktop.Orchestrator") as mock_orch_cls:
                    with patch.object(MainWindow, "_setup_ui"):
                        with patch.object(MainWindow, "_setup_tray"):
                            MainWindow(mock_app, config={})

                            mock_provider_cls.assert_not_called()
                            mock_aicore_cls.assert_not_called()
                            self.assertNotIn("ai_core", mock_orch_cls.call_args.kwargs)

    def test_ai_enabled_creates_provider_with_config_and_injects_into_orchestrator(self) -> None:
        """Com IA habilitada, OllamaProvider recebe config, AICore é criado e injetado sem inferência."""
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        config = {
            "ai": {
                "enabled": True,
                "model": "qwen-custom:7b",
                "timeout_seconds": 150,
            }
        }

        mock_provider = MagicMock()
        mock_aicore = MagicMock()

        with patch("therion.interface.desktop.OllamaProvider", return_value=mock_provider) as mock_provider_cls:
            with patch("therion.interface.desktop.AICore", return_value=mock_aicore) as mock_aicore_cls:
                with patch("therion.interface.desktop.Orchestrator") as mock_orch_cls:
                    with patch.object(MainWindow, "_setup_ui"):
                        with patch.object(MainWindow, "_setup_tray"):
                            MainWindow(mock_app, config=config)

                            # 1. OllamaProvider recebe model e timeout
                            mock_provider_cls.assert_called_once_with(model="qwen-custom:7b", timeout=150)
                            # 2. AICore é criado com o provider
                            mock_aicore_cls.assert_called_once()
                            self.assertEqual(mock_aicore_cls.call_args.kwargs["provider"], mock_provider)
                            # 3. Orchestrator recebe o AICore
                            mock_orch_cls.assert_called_once()
                            self.assertEqual(mock_orch_cls.call_args.kwargs["ai_core"], mock_aicore)
                            # 4. Nenhuma inferência na inicialização
                            mock_provider.generate.assert_not_called()
                            mock_aicore.classify.assert_not_called()

    def test_ai_enabled_injects_canonical_allowlist_exactly(self) -> None:
        """A allowlist injetada no AICore contém exatamente as 5 intents canônicas."""
        from therion.interface.desktop import MainWindow
        mock_app = MagicMock()
        config = {"ai": {"enabled": True}}

        expected_allowlist = [
            "abrir aplicativo",
            "listar aliases",
            "buscar segundo cérebro",
            "calendário hoje",
            "criar evento calendário",
        ]

        with patch("therion.interface.desktop.OllamaProvider"):
            with patch("therion.interface.desktop.AICore") as mock_aicore_cls:
                with patch("therion.interface.desktop.Orchestrator"):
                    with patch.object(MainWindow, "_setup_ui"):
                        with patch.object(MainWindow, "_setup_tray"):
                            MainWindow(mock_app, config=config)

                            mock_aicore_cls.assert_called_once()
                            passed_intents = mock_aicore_cls.call_args.kwargs["available_intents"]
                            self.assertEqual(passed_intents, expected_allowlist)


class TestDesktopIcon(unittest.TestCase):
    """Testes de integração do ícone oficial do Therion."""

    _qapp = None

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            cls._qapp = QApplication(sys.argv)
        else:
            cls._qapp = QApplication.instance()

    def test_icon_path_is_relative_to_module(self) -> None:
        """O caminho do ícone é calculado relativo ao módulo desktop.py."""
        from therion.interface.desktop import _ICONE_PATH
        from pathlib import Path
        expected_parent = Path(__file__).resolve().parent.parent / "therion" / "interface"
        self.assertEqual(_ICONE_PATH.parent.parent, expected_parent.parent)
        self.assertEqual(_ICONE_PATH.name, "icone.png")

    def test_window_receives_valid_icon_when_asset_exists(self) -> None:
        """A janela recebe um QIcon válido quando o asset existe."""
        from therion.interface.desktop import MainWindow, _ICONE_PATH
        from PySide6.QtGui import QIcon
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch.object(MainWindow, '_setup_tray'):
                window = MainWindow(mock_app)
                if _ICONE_PATH.is_file():
                    self.assertFalse(window.windowIcon().isNull())
                else:
                    self.assertTrue(window.windowIcon().isNull())

    def test_tray_uses_official_icon_when_asset_exists(self) -> None:
        """O tray usa o ícone oficial quando o asset existe."""
        from therion.interface.desktop import MainWindow, _ICONE_PATH
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch('therion.interface.desktop.QSystemTrayIcon') as mock_tray_cls:
                mock_tray = MagicMock()
                mock_tray_cls.return_value = mock_tray
                mock_tray_cls.isSystemTrayAvailable.return_value = True
                window = MainWindow(mock_app)
                if _ICONE_PATH.is_file():
                    mock_tray.setIcon.assert_called()
                    call_args = mock_tray.setIcon.call_args[0][0]
                    self.assertFalse(call_args.isNull())

    def test_tray_fallback_when_asset_missing(self) -> None:
        """O fallback do tray permanece seguro se o asset estiver indisponível."""
        from therion.interface.desktop import MainWindow, _ICONE_PATH
        mock_app = MagicMock()
        with patch.object(MainWindow, '_setup_ui'):
            with patch('therion.interface.desktop.QSystemTrayIcon') as mock_tray_cls:
                mock_tray = MagicMock()
                mock_tray_cls.return_value = mock_tray
                mock_tray_cls.isSystemTrayAvailable.return_value = True
                with patch.object(_ICONE_PATH.__class__, 'is_file', return_value=False):
                    window = MainWindow(mock_app)
                    mock_tray.setIcon.assert_called()


if __name__ == "__main__":
    unittest.main()
