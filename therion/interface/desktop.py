"""Interface desktop mínima para Therion V1."""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt

from therion.config import load_config


class MainWindow(QMainWindow):
    """Janela principal mínima do Therion."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.setWindowTitle("Therion")
        self.resize(800, 600)
        self._app = app
        self._tray_icon: QSystemTrayIcon | None = None
        self._closing = False
        self._setup_tray()

    def _setup_tray(self) -> None:
        """Configura o System Tray se disponível."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("Aviso: System Tray não disponível neste ambiente.")
            return

        # Cria o ícone do tray (usa ícone padrão do Qt)
        self._tray_icon = QSystemTrayIcon(self)
        style = self.style()
        if style:
            icon = style.standardIcon(style.StandardPixmap.SP_ComputerIcon)
            self._tray_icon.setIcon(icon)

        # Cria menu de contexto
        tray_menu = QMenu(self)

        action_show = QAction("Abrir Therion", self)
        action_show.triggered.connect(self._show_window)
        tray_menu.addAction(action_show)

        action_quit = QAction("Encerrar Therion", self)
        action_quit.triggered.connect(self._quit_application)
        tray_menu.addAction(action_quit)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.setToolTip("Therion")
        self._tray_icon.show()

    def _show_window(self) -> None:
        """Mostra e traz a janela para frente."""
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_application(self) -> None:
        """Encerra a aplicação de forma limpa (ação explícita do menu)."""
        self._closing = True
        if self._tray_icon:
            self._tray_icon.hide()
        self._app.quit()

    def closeEvent(self, event) -> None:
        """Oculta a janela para a bandeja (não encerra a aplicação)."""
        if self._closing:
            if self._tray_icon:
                self._tray_icon.hide()
            super().closeEvent(event)
            return

        if self._tray_icon and self._tray_icon.isVisible():
            event.ignore()
            self.hide()
        else:
            if self._tray_icon:
                self._tray_icon.hide()
            super().closeEvent(event)


def main() -> int:
    """Ponto de entrada da aplicação desktop."""
    app = QApplication(sys.argv)
    config = load_config()
    window = MainWindow(app)
    if not config.get("ui", {}).get("start_minimized", False):
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())