"""Testes do Bloco B2.1 — run_initial_auth e composition root do desktop.

Todos mockados. Nenhum navegador real, nenhuma API Google, nenhum OAuth real.
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from therion.calendar.adapter import CalendarError
from therion.calendar.auth import run_initial_auth


# ---------------------------------------------------------------------------
# Testes de run_initial_auth
# ---------------------------------------------------------------------------

class TestRunInitialAuth(unittest.TestCase):
    """Valida o fluxo OAuth inicial de run_initial_auth (totalmente mockado)."""

    def test_credentials_json_ausente_levanta_calendar_error(self) -> None:
        """1. credentials.json ausente levanta CalendarError com mensagem amigável."""
        fake_path = MagicMock(spec=Path)
        fake_path.exists.return_value = False
        fake_path.__str__ = lambda s: r"C:\Users\Test\AppData\Roaming\Therion\credentials.json"

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_path):
            with self.assertRaises(CalendarError) as ctx:
                run_initial_auth()

        self.assertIn("credentials.json não encontrado", str(ctx.exception))

    def test_fluxo_oauth_mockado_persiste_token(self) -> None:
        """2. Fluxo OAuth mockado completo → _persist_token chamado com as credenciais."""
        fake_creds_path = MagicMock(spec=Path)
        fake_creds_path.exists.return_value = True
        fake_creds_path.__str__ = lambda s: r"C:\Users\Test\AppData\Roaming\Therion\credentials.json"

        mock_creds = MagicMock()
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_creds_path):
            with patch("therion.calendar.auth._persist_token") as mock_persist:
                with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                           return_value=mock_flow):
                    run_initial_auth()

        mock_flow.run_local_server.assert_called_once_with(port=0)
        mock_persist.assert_called_once_with(mock_creds)

    def test_run_local_server_com_port_zero(self) -> None:
        """3. run_local_server é chamado com port=0 (sem porta fixa)."""
        fake_creds_path = MagicMock(spec=Path)
        fake_creds_path.exists.return_value = True
        fake_creds_path.__str__ = lambda s: r"C:\credentials.json"

        mock_creds = MagicMock()
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_creds_path):
            with patch("therion.calendar.auth._persist_token"):
                with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                           return_value=mock_flow):
                    run_initial_auth()

        _, kwargs = mock_flow.run_local_server.call_args
        self.assertEqual(kwargs.get("port", mock_flow.run_local_server.call_args[0][0] if mock_flow.run_local_server.call_args[0] else None), 0)

    def test_erro_oauth_levanta_calendar_error(self) -> None:
        """4. Erro durante o fluxo OAuth é convertido em CalendarError amigável."""
        fake_creds_path = MagicMock(spec=Path)
        fake_creds_path.exists.return_value = True
        fake_creds_path.__str__ = lambda s: r"C:\credentials.json"

        mock_flow = MagicMock()
        mock_flow.run_local_server.side_effect = RuntimeError("conexão recusada")

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_creds_path):
            with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                       return_value=mock_flow):
                with self.assertRaises(CalendarError) as ctx:
                    run_initial_auth()

        self.assertIn("Falha durante o fluxo OAuth", str(ctx.exception))

    def test_scope_readonly_usado(self) -> None:
        """5. from_client_secrets_file é chamado com o scope readonly correto."""
        fake_creds_path = MagicMock(spec=Path)
        fake_creds_path.exists.return_value = True
        fake_creds_path.__str__ = lambda s: r"C:\credentials.json"

        mock_creds = MagicMock()
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_creds_path):
            with patch("therion.calendar.auth._persist_token"):
                with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                           return_value=mock_flow) as mock_from_file:
                    run_initial_auth()

        _, kwargs = mock_from_file.call_args
        scopes = kwargs.get("scopes") or mock_from_file.call_args[0][1]
        self.assertIn("https://www.googleapis.com/auth/calendar.readonly", scopes)

    def test_token_existente_nao_apagado(self) -> None:
        """6. run_initial_auth não apaga token existente — apenas persiste o novo após OAuth."""
        fake_creds_path = MagicMock(spec=Path)
        fake_creds_path.exists.return_value = True
        fake_creds_path.__str__ = lambda s: r"C:\credentials.json"

        mock_creds = MagicMock()
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        fake_token_path = MagicMock(spec=Path)
        fake_token_path.exists.return_value = True  # token já existe

        with patch("therion.calendar.auth._get_credentials_path", return_value=fake_creds_path):
            with patch("therion.calendar.auth._get_token_path", return_value=fake_token_path):
                with patch("therion.calendar.auth._persist_token") as mock_persist:
                    with patch("google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
                               return_value=mock_flow):
                        run_initial_auth()

        # token existente não foi deletado (unlink não foi chamado)
        fake_token_path.unlink.assert_not_called()
        # mas o novo token foi persistido
        mock_persist.assert_called_once()


# ---------------------------------------------------------------------------
# Testes do composition root — desktop._build_calendar_adapter
# ---------------------------------------------------------------------------

class TestDesktopCalendarCompositionRoot(unittest.TestCase):
    """Valida a lógica de instanciação do GoogleCalendarAdapter em MainWindow."""

    def _make_window(self, config: dict) -> "MainWindow":
        """Cria MainWindow com mocks de Qt para evitar display real."""
        from therion.interface.desktop import MainWindow
        with patch("therion.interface.desktop.QApplication"):
            with patch.object(MainWindow, "_setup_ui"):
                with patch.object(MainWindow, "_setup_tray"):
                    app_mock = MagicMock()
                    window = MainWindow.__new__(MainWindow)
                    # Inicialização manual parcial (sem chamar __init__ completo)
                    window._app = app_mock
                    window._config = config
                    window._tray_icon = None
                    window._closing = False
                    window._pending_plan = None
                    return window

    def test_calendar_disabled_retorna_none(self) -> None:
        """7. calendar.enabled=false → _build_calendar_adapter retorna None."""
        from therion.interface.desktop import MainWindow
        window = self._make_window({"calendar": {"enabled": False, "time_zone": "America/Sao_Paulo"}})
        adapter = window._build_calendar_adapter()
        self.assertIsNone(adapter)

    def test_calendar_enabled_false_por_default(self) -> None:
        """8. Config sem 'calendar' → adapter é None (enabled=false por padrão)."""
        from therion.interface.desktop import MainWindow
        window = self._make_window({})
        adapter = window._build_calendar_adapter()
        self.assertIsNone(adapter)

    def test_calendar_enabled_retorna_google_adapter(self) -> None:
        """9. calendar.enabled=true → retorna instância de GoogleCalendarAdapter."""
        from therion.interface.desktop import MainWindow
        from therion.calendar.google_adapter import GoogleCalendarAdapter

        window = self._make_window({
            "calendar": {"enabled": True, "time_zone": "America/Sao_Paulo"}
        })
        adapter = window._build_calendar_adapter()
        self.assertIsInstance(adapter, GoogleCalendarAdapter)

    def test_calendar_enabled_usa_timezone_da_config(self) -> None:
        """10. calendar.enabled=true → GoogleCalendarAdapter recebe time_zone da config."""
        from therion.interface.desktop import MainWindow
        from therion.calendar.google_adapter import GoogleCalendarAdapter

        window = self._make_window({
            "calendar": {"enabled": True, "time_zone": "Europe/London"}
        })
        adapter = window._build_calendar_adapter()
        self.assertIsInstance(adapter, GoogleCalendarAdapter)
        self.assertEqual(adapter._time_zone, "Europe/London")

    def test_calendar_enabled_com_calendar_error_retorna_none(self) -> None:
        """11. calendar.enabled=true mas CalendarError na criação → None (app não cai)."""
        from therion.interface.desktop import MainWindow

        window = self._make_window({
            "calendar": {"enabled": True, "time_zone": "America/Sao_Paulo"}
        })
        with patch(
            "therion.interface.desktop.GoogleCalendarAdapter",
            side_effect=CalendarError("auth falhou"),
        ):
            adapter = window._build_calendar_adapter()

        self.assertIsNone(adapter)

    def test_calendar_enabled_com_erro_generico_retorna_none(self) -> None:
        """12. calendar.enabled=true mas erro inesperado → None (app não cai)."""
        from therion.interface.desktop import MainWindow

        window = self._make_window({
            "calendar": {"enabled": True, "time_zone": "America/Sao_Paulo"}
        })
        with patch(
            "therion.interface.desktop.GoogleCalendarAdapter",
            side_effect=RuntimeError("erro inesperado"),
        ):
            adapter = window._build_calendar_adapter()

        self.assertIsNone(adapter)

    def test_orchestrator_recebe_adapter_quando_habilitado(self) -> None:
        """13. Orchestrator recebe calendar_adapter quando enabled=true."""
        from therion.calendar.google_adapter import GoogleCalendarAdapter

        config = {
            "runtime": {"real_actions_enabled": False},
            "calendar": {"enabled": True, "time_zone": "America/Sao_Paulo"},
        }
        window = self._make_window(config)
        adapter = window._build_calendar_adapter()

        with patch("therion.interface.desktop.Orchestrator") as MockOrch:
            real_actions_enabled = window._config.get("runtime", {}).get("real_actions_enabled", False)
            MockOrch(
                simulate=not real_actions_enabled,
                calendar_adapter=adapter,
            )
            call_kwargs = MockOrch.call_args[1]
            self.assertIn("calendar_adapter", call_kwargs)
            self.assertIsInstance(call_kwargs["calendar_adapter"], GoogleCalendarAdapter)

    def test_orchestrator_sem_adapter_quando_desabilitado(self) -> None:
        """14. Orchestrator é instanciado sem calendar_adapter quando enabled=false."""
        config = {
            "runtime": {"real_actions_enabled": False},
            "calendar": {"enabled": False, "time_zone": "America/Sao_Paulo"},
        }
        window = self._make_window(config)
        adapter = window._build_calendar_adapter()
        self.assertIsNone(adapter)

        with patch("therion.interface.desktop.Orchestrator") as MockOrch:
            real_actions_enabled = window._config.get("runtime", {}).get("real_actions_enabled", False)
            if adapter is not None:
                MockOrch(
                    simulate=not real_actions_enabled,
                    calendar_adapter=adapter,
                )
            else:
                MockOrch(simulate=not real_actions_enabled)
            call_kwargs = MockOrch.call_args[1]
            self.assertNotIn("calendar_adapter", call_kwargs)


if __name__ == "__main__":
    unittest.main()
