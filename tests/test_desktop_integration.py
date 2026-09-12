"""Testes de integração da interface desktop com configuração."""

import sys
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
import unittest


class TestDesktopIntegration(unittest.TestCase):
    """Testes de integração desktop + config (sem GUI real)."""

    def setUp(self) -> None:
        """Configura ambiente isolado."""
        self.temp_dir = tempfile.mkdtemp(prefix="therion_desktop_test_")

    def tearDown(self) -> None:
        """Limpa arquivos temporários."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_main_with_config(self, config_data: dict) -> tuple[bool, MagicMock]:
        """Executa main() mockado com config específica; retorna (show_called, mock_window)."""
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

                    show_called = mock_window.show.called
                    return show_called, mock_window

    def test_start_minimized_false_mostra_janela(self) -> None:
        """start_minimized=False deve chamar window.show()."""
        config = {"ui": {"start_minimized": False}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called, "Janela deve ser mostrada quando start_minimized=False")

    def test_start_minimized_true_nao_mostra_janela(self) -> None:
        """start_minimized=True NÃO deve chamar window.show()."""
        config = {"ui": {"start_minimized": True}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertFalse(show_called, "Janela NÃO deve ser mostrada quando start_minimized=True")

    def test_config_ausente_usa_fallback_false(self) -> None:
        """Config ausente/None deve usar fallback start_minimized=False."""
        config = {"ui": {}, "aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called, "Fallback deve ser False quando ui.start_minimized ausente")

    def test_config_ui_ausente_usa_fallback_false(self) -> None:
        """Seção ui ausente deve usar fallback start_minimized=False."""
        config = {"aliases": {}, "allowed_apps": []}
        show_called, _ = self._run_main_with_config(config)
        self.assertTrue(show_called, "Fallback deve ser False quando seção ui ausente")

    def test_load_config_consumido_corretamente(self) -> None:
        """Verifica que main() consome o valor retornado por load_config."""
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
                    # Verifica que o retorno foi usado (sem erro)


if __name__ == "__main__":
    unittest.main()