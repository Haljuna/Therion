"""Interface desktop mínima para Therion V1."""

import html
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
    QPlainTextEdit,
    QPushButton,
)
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtCore import Qt, Signal

from therion.calendar.adapter import CalendarError
from therion.calendar.google_adapter import GoogleCalendarAdapter
from therion.config import load_config
from therion.core.orchestrator import Orchestrator, Plan
from therion.governance.confirmation import ConfirmationHandler


class ConversationInput(QPlainTextEdit):
    """Campo de entrada multilinha: Enter envia, Shift+Enter insere quebra."""

    submit = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Digite seu comando aqui...")
        self.setFixedHeight(60)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submit.emit()
        else:
            super().keyPressEvent(event)


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
        calendar_adapter = self._build_calendar_adapter()
        if calendar_adapter is not None:
            self._orchestrator = Orchestrator(
                simulate=not real_actions_enabled,
                calendar_adapter=calendar_adapter,
            )
        else:
            self._orchestrator = Orchestrator(simulate=not real_actions_enabled)
        self._confirmation_handler = ConfirmationHandler()
        self._pending_plan: Optional[Plan] = None
        self._setup_ui()
        self._setup_tray()

    def _build_calendar_adapter(self) -> "GoogleCalendarAdapter | None":
        """Instancia GoogleCalendarAdapter se calendar.enabled=true; None caso contrário.

        Falhas de autenticação são isoladas: aviso no terminal, app continua sem adapter.
        """
        cal_config = self._config.get("calendar", {})
        if not cal_config.get("enabled", False):
            return None

        time_zone = cal_config.get("time_zone", "America/Sao_Paulo")
        try:
            return GoogleCalendarAdapter(time_zone=time_zone)
        except CalendarError as e:
            print(f"[Therion] Aviso: calendário desativado por falha de autenticação: {e}")
            return None
        except Exception as e:
            print(f"[Therion] Aviso: erro inesperado ao inicializar calendário: {e}")
            return None

    def _setup_ui(self) -> None:
        """Configura os widgets da interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._history = QTextEdit()
        self._history.setReadOnly(True)
        layout.addWidget(self._history)

        input_layout = QHBoxLayout()
        self._input = ConversationInput()
        self._input.submit.connect(self._send_command)
        input_layout.addWidget(self._input)

        self._send_button = QPushButton("Enviar")
        self._send_button.clicked.connect(self._send_command)
        input_layout.addWidget(self._send_button)

        self._clear_button = QPushButton("Limpar conversa")
        self._clear_button.clicked.connect(self._clear_conversation)
        input_layout.addWidget(self._clear_button)

        layout.addLayout(input_layout)

        self._update_clear_button_state()

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
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _show_window(self) -> None:
        """Mostra e traz a janela para frente."""
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: int) -> None:
        """Trata ativações do ícone da bandeja."""
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _send_command(self) -> None:
        """Envia o comando digitado para o Orchestrator."""
        command = self._input.toPlainText().strip()
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

        self._update_clear_button_state()

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
            self._update_clear_button_state()
            return

        self._pending_plan = None
        self._append("Therion", final_result.message)
        self._update_clear_button_state()

    def _append(self, sender: str, text: str) -> None:
        """Adiciona mensagem ao histórico."""
        prefix = "<b>Você:</b>" if sender == "Você" else "<b>Therion:</b>"
        safe_text = html.escape(text).replace("\n", "<br>")
        block = f"{prefix}<br>{safe_text}"
        self._history.append(block)

    def _clear_conversation(self) -> None:
        """Limpa apenas o histórico visual da conversa."""
        self._history.clear()

    def _update_clear_button_state(self) -> None:
        """Habilita/desabilita o botão Limpar conforme _pending_plan."""
        self._clear_button.setEnabled(self._pending_plan is None)

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