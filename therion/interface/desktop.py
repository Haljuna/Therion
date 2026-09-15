"""Interface desktop mínima para Therion V1."""

import sys
from typing import Optional

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSystemTrayIcon,
    QMenu,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
)
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt

from therion.config import load_config
from therion.core.orchestrator import Orchestrator, Plan
from therion.governance.confirmation import ConfirmationHandler


class MainWindow(QMainWindow):
    """Janela principal mínima do Therion."""

    def __init__(self, app: QApplication, config: dict | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Therion")
        self.resize(800, 600)
        self._app = app
        self._config = config or {}
        self._tray_icon: QSystemTrayIcon | None = None
        self._closing = False
        real_actions_enabled = self._config.get("runtime", {}).get("real_actions_enabled", False)
        self._orchestrator = Orchestrator(simulate=not real_actions_enabled)
        self._confirmation_handler = ConfirmationHandler()
        self._pending_plan: Optional[Plan] = None
        self._setup_ui()
        self._setup_tray()

    def _setup_ui(self) -> None:
        """Configura os widgets da interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        layout.addWidget(self._history)

        input_layout = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Digite seu comando aqui...")
        self._input.returnPressed.connect(self._send_command)
        input_layout.addWidget(self._input)

        self._send_button = QPushButton("Enviar")
        self._send_button.clicked.connect(self._send_command)
        input_layout.addWidget(self._send_button)

        layout.addLayout(input_layout)

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

    def _send_command(self) -> None:
        """Envia o comando digitado para o Orchestrator."""
        command = self._input.text().strip()
        if not command:
            return

        if self._pending_plan is not None:
            self._handle_confirmation(command)
            return

        self._append("Você", command)
        self._input.clear()

        try:
            result = self._orchestrator.process_command(command)
        except Exception:
            self._append("Therion", "Ocorreu um erro inesperado ao processar o comando.")
            return

        self._append("Therion", result.message)

        if result.status == "awaiting_confirmation" and result.plan is not None:
            self._pending_plan = result.plan
        else:
            self._pending_plan = None

    def _handle_confirmation(self, response: str) -> None:
        """Processa resposta de confirmação."""
        self._input.clear()
        self._append("Você", response)

        confirmed = self._confirmation_handler.evaluate_response(response)

        if confirmed is None:
            self._append("Therion", "Resposta não reconhecida. Responda 'sim' ou 'não'.")
            return

        try:
            final_result = self._orchestrator.confirm_and_execute(
                self._pending_plan, confirmed=confirmed
            )
        except Exception:
            self._pending_plan = None
            self._append("Therion", "Ocorreu um erro inesperado ao processar a confirmação.")
            return

        self._pending_plan = None
        self._append("Therion", final_result.message)

    def _append(self, sender: str, text: str) -> None:
        """Adiciona mensagem ao histórico."""
        prefix = "Você:" if sender == "Você" else "Therion:"
        current = self._history.toPlainText()
        if current:
            new_text = f"{current}\n\n{prefix}\n{text}"
        else:
            new_text = f"{prefix}\n{text}"
        self._history.setPlainText(new_text)
        self._history.verticalScrollBar().setValue(
            self._history.verticalScrollBar().maximum()
        )

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
    window = MainWindow(app, config)
    if not config.get("ui", {}).get("start_minimized", False):
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())