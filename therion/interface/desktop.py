"""Interface desktop mínima para Therion V1."""

import html
import sys
from pathlib import Path
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
    QFrame,
    QLabel,
    QSizePolicy,
    QSpacerItem,
)
from PySide6.QtGui import QAction, QKeyEvent, QFont, QIcon
from PySide6.QtCore import Qt, Signal

_ICONE_PATH = Path(__file__).resolve().parent.parent / "assets" / "icone.png"

from therion.calendar.adapter import CalendarError
from therion.calendar.google_adapter import GoogleCalendarAdapter
from therion.config import load_config
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator, Plan
from therion.governance.confirmation import ConfirmationHandler


# ---------------------------------------------------------------------------
# Paleta de cores do Therion
# ---------------------------------------------------------------------------
_BG_PRIMARY = "#0b0b0b"
_BG_SECONDARY = "#0e0e0e"
_BG_INPUT = "#1a1a1a"
_ACCENT = "#f97316"
_ACCENT_HOVER = "#fb923c"
_BORDER = "#1f1f1f"
_TEXT_PRIMARY = "#f5f5f5"
_TEXT_SECONDARY = "#cfcfcf"
_TEXT_MUTED = "#8a8a8a"
_ORBE_IDLE = "#7c3f10"
_ORBE_THINKING = "#9a5a17"
_ORBE_RESPONDING = "#c2410c"
_ORBE_CONFIRM = "#f59e0b"
_ORBE_EXECUTING = "#f97316"
_ORBE_SUCCESS = "#22c55e"
_ORBE_ERROR = "#ef4444"

_MSG_USER_BG = "#21170e"
_MSG_USER_FG = "#f5f5f5"
_MSG_THERION_BG = "#171717"
_MSG_THERION_FG = "#f5f5f5"

# Mapeamento explícito: status do OrchestrationResult → estado visual do orbe.
_ORBE_STATUS_MAP: dict[str, str] = {
    "awaiting_confirmation": "awaiting_confirmation",
    "success": "success",
    "executed_simulated": "success",
    "cancelled": "idle",
    "unknown_intent": "idle",
    "forbidden": "error",
    "execution_failed": "error",
    "verification_failed": "error",
}

_ORBE_STATES: dict[str, tuple[str, str]] = {
    "idle": (_ORBE_IDLE, "Pronto"),
    "thinking": (_ORBE_THINKING, "Pensando..."),
    "responding": (_ORBE_RESPONDING, "Respondendo"),
    "awaiting_confirmation": (_ORBE_CONFIRM, "Aguardando confirmação"),
    "executing": (_ORBE_EXECUTING, "Executando..."),
    "success": (_ORBE_SUCCESS, "Concluído"),
    "error": (_ORBE_ERROR, "Erro"),
}

# ---------------------------------------------------------------------------
# Estilo global (aplicado no main)
# ---------------------------------------------------------------------------
STYLESHEET = (
    "QMainWindow, QWidget {"
    "  background-color: " + _BG_PRIMARY + ";"
    "  color: " + _TEXT_PRIMARY + ";"
    "}"
    "#topBar {"
    "  background-color: " + _BG_PRIMARY + ";"
    "  border: none;"
    "}"
    "#topBar QLabel {"
    "  color: " + _TEXT_PRIMARY + ";"
    "  font-size: 15px;"
    "  font-weight: bold;"
    "}"
    "#btnClear, #btnMinimize, #btnQuit {"
    "  background-color: transparent;"
    "  color: " + _TEXT_SECONDARY + ";"
    "  border: none;"
    "  padding: 4px 8px;"
    "  font-size: 13px;"
    "}"
    "#btnClear:hover, #btnMinimize:hover {"
    "  color: " + _ACCENT_HOVER + ";"
    "  background-color: " + _BG_INPUT + ";"
    "}"
    "#btnQuit:hover {"
    "  color: #e74c3c;"
    "  background-color: " + _BG_INPUT + ";"
    "}"
    "#orbeFrame { background-color: transparent; }"
    "#orbe {"
    "  background-color: " + _ORBE_IDLE + ";"
    "  border-radius: 28px;"
    "  min-width: 56px; max-width: 56px;"
    "  min-height: 56px; max-height: 56px;"
    "}"
    "#orbeLabel {"
    "  color: " + _TEXT_PRIMARY + ";"
    "  font-size: 10px;"
    "  font-weight: bold;"
    "  background: transparent;"
    "}"
    "#history {"
    "  background-color: " + _BG_PRIMARY + ";"
    "  color: " + _TEXT_PRIMARY + ";"
    "  border: none;"
    "  padding: 12px 16px;"
    "  font-size: 13px;"
    "}"
    "#history QWidget { background-color: " + _BG_PRIMARY + "; }"
    "#input {"
    "  background-color: " + _BG_INPUT + ";"
    "  color: " + _TEXT_PRIMARY + ";"
    "  border: 1px solid " + _BORDER + ";"
    "  border-radius: 10px;"
    "  padding: 9px 12px;"
    "  font-size: 13px;"
    "}"
    "#input:focus { border: 1px solid " + _ACCENT + "; }"
    "#btnSend {"
    "  background-color: " + _ACCENT + ";"
    "  color: " + _TEXT_PRIMARY + ";"
    "  border: none;"
    "  border-radius: 8px;"
    "  padding: 8px 16px;"
    "  font-size: 13px;"
    "  font-weight: bold;"
    "  min-width: 60px;"
    "}"
    "#btnSend:hover { background-color: " + _ACCENT_HOVER + "; }"
    "#btnSend:pressed { background-color: #c2410c; }"
    "#confirmPanel {"
    "  background-color: " + _BG_SECONDARY + ";"
    "  border: none;"
    "  border-radius: 12px;"
    "  margin: 6px 16px;"
    "}"
    "#confirmTitle {"
    "  color: " + _ORBE_CONFIRM + ";"
    "  font-size: 12px;"
    "  font-weight: bold;"
    "  background: transparent;"
    "}"
    "#confirmDescription {"
    "  color: " + _TEXT_PRIMARY + ";"
    "  font-size: 11px;"
    "  background: transparent;"
    "}"
    "#btnConfirm {"
    "  background-color: " + _ACCENT + ";"
    "  color: #0b0b0b;"
    "  border: none;"
    "  border-radius: 6px;"
    "  padding: 6px 14px;"
    "  font-size: 12px;"
    "  font-weight: bold;"
    "}"
    "#btnConfirm:hover { background-color: " + _ACCENT_HOVER + "; }"
    "#btnCancel {"
    "  background-color: " + _BG_INPUT + ";"
    "  color: " + _TEXT_SECONDARY + ";"
    "  border: none;"
    "  border-radius: 6px;"
    "  padding: 6px 14px;"
    "  font-size: 12px;"
    "}"
    "#btnCancel:hover { color: " + _ACCENT_HOVER + "; }"
)


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
        self._therion_icon = self._load_icon()
        real_actions_enabled = self._config.get("runtime", {}).get("real_actions_enabled", False)
        calendar_adapter = self._build_calendar_adapter()
        ai_core = self._build_ai_core()
        orch_kwargs: dict = {"simulate": not real_actions_enabled}
        if calendar_adapter is not None:
            orch_kwargs["calendar_adapter"] = calendar_adapter
        if ai_core is not None:
            orch_kwargs["ai_core"] = ai_core
        self._orchestrator = Orchestrator(**orch_kwargs)
        self._confirmation_handler = ConfirmationHandler()
        self._pending_plan: Optional[Plan] = None
        if not self._therion_icon.isNull():
            self.setWindowIcon(self._therion_icon)
        self._setup_ui()
        self._setup_tray()

    def _load_icon(self) -> QIcon:
        """Carrega o ícone oficial do Therion do asset PNG; retorna QIcon vazio se ausente."""
        if _ICONE_PATH.is_file():
            return QIcon(str(_ICONE_PATH))
        return QIcon()

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

    def _build_ai_core(self) -> Optional[AICore]:
        """Instancia AICore com OllamaProvider se ai.enabled=true; None caso contrário."""
        ai_config = self._config.get("ai", {})
        if not ai_config.get("enabled", False):
            return None

        model = ai_config.get("model", "qwen3:4b-instruct")
        timeout_seconds = ai_config.get("timeout_seconds", 90)
        provider = OllamaProvider(model=model, timeout=timeout_seconds)
        available_intents = [
            "abrir aplicativo",
            "listar aliases",
            "buscar segundo cérebro",
            "calendário hoje",
            "criar evento calendário",
        ]
        return AICore(provider=provider, available_intents=available_intents)

    def _setup_ui(self) -> None:
        """Configura os widgets da interface com tema escuro."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Barra superior ---
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(44)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 0, 14, 0)
        top_layout.setSpacing(8)

        lbl_title = QLabel("THERION")
        lbl_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        top_layout.addWidget(lbl_title)
        top_layout.addSpacerItem(
            QSpacerItem(
                20, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        self._clear_button = QPushButton("Limpar")
        self._clear_button.setObjectName("btnClear")
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.clicked.connect(self._clear_conversation)
        top_layout.addWidget(self._clear_button)

        btn_min = QPushButton("\u2014")
        btn_min.setObjectName("btnMinimize")
        btn_min.setCursor(Qt.PointingHandCursor)
        btn_min.setFixedWidth(28)
        btn_min.clicked.connect(self._minimize_window)
        top_layout.addWidget(btn_min)

        btn_quit = QPushButton("X")
        btn_quit.setObjectName("btnQuit")
        btn_quit.setCursor(Qt.PointingHandCursor)
        btn_quit.setFixedWidth(28)
        btn_quit.clicked.connect(self._quit_application)
        top_layout.addWidget(btn_quit)

        layout.addWidget(top_bar)

        # --- Orbe visual + estado ---
        orbe_container = QVBoxLayout()
        orbe_container.setAlignment(Qt.AlignCenter)
        orbe_container.setContentsMargins(0, 12, 0, 4)
        orbe_container.setSpacing(4)

        self._orbe = QFrame()
        self._orbe.setObjectName("orbe")
        self._orbe.setFixedSize(56, 56)
        self._orbe.setStyleSheet(
            f"background-color: {_ORBE_IDLE}; border-radius: 28px;"
        )
        orbe_container.addWidget(self._orbe, alignment=Qt.AlignCenter)

        self._orbe_label = QLabel("Pronto")
        self._orbe_label.setObjectName("orbeLabel")
        orbe_container.addWidget(self._orbe_label, alignment=Qt.AlignCenter)

        layout.addLayout(orbe_container)

        # --- Histórico ---
        self._history = QTextEdit()
        self._history.setObjectName("history")
        self._history.setReadOnly(True)
        layout.addWidget(self._history)

        # --- Painel de confirmação ---
        self._confirm_panel = QFrame()
        self._confirm_panel.setObjectName("confirmPanel")
        self._confirm_panel.setVisible(False)
        confirm_layout = QHBoxLayout(self._confirm_panel)
        confirm_layout.setContentsMargins(14, 8, 14, 8)
        confirm_layout.setSpacing(12)

        confirm_content = QVBoxLayout()
        confirm_content.setSpacing(2)
        self._confirm_title = QLabel("Confirmação necessária")
        self._confirm_title.setObjectName("confirmTitle")
        confirm_content.addWidget(self._confirm_title)

        self._confirm_description = QLabel("")
        self._confirm_description.setObjectName("confirmDescription")
        self._confirm_description.setTextFormat(Qt.PlainText)
        self._confirm_description.setWordWrap(True)
        confirm_content.addWidget(self._confirm_description)
        confirm_layout.addLayout(confirm_content, 1)

        self._btn_confirm = QPushButton("Confirmar")
        self._btn_confirm.setObjectName("btnConfirm")
        self._btn_confirm.clicked.connect(self._on_confirm)
        confirm_layout.addWidget(self._btn_confirm)

        self._btn_cancel = QPushButton("Cancelar")
        self._btn_cancel.setObjectName("btnCancel")
        self._btn_cancel.clicked.connect(self._on_cancel)
        confirm_layout.addWidget(self._btn_cancel)
        layout.addWidget(self._confirm_panel)

        # --- Input ---
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(16, 8, 16, 8)
        input_layout.setSpacing(10)
        self._input = ConversationInput()
        self._input.setObjectName("input")
        self._input.submit.connect(self._send_command)
        input_layout.addWidget(self._input)

        self._send_button = QPushButton("Enviar")
        self._send_button.setObjectName("btnSend")
        self._send_button.clicked.connect(self._send_command)
        input_layout.addWidget(self._send_button)

        layout.addLayout(input_layout)

        self._update_clear_button_state()

    def _setup_tray(self) -> None:
        """Configura o System Tray se disponível."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("Aviso: System Tray não disponível neste ambiente.")
            return

        # Cria o ícone do tray (ícone oficial ou fallback do Qt)
        self._tray_icon = QSystemTrayIcon(self)
        if not self._therion_icon.isNull():
            self._tray_icon.setIcon(self._therion_icon)
        else:
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

    def _minimize_window(self) -> None:
        """Minimiza a janela normalmente."""
        self.showMinimized()

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

        self._update_orbe("thinking")

        try:
            result = self._orchestrator.process_command(command)
        except Exception:
            self._update_orbe("error")
            self._append("Therion", "Ocorreu um erro inesperado ao processar o comando.")
            return

        self._append("Therion", result.message)

        if result.status == "awaiting_confirmation" and result.plan is not None:
            self._pending_plan = result.plan
            self._update_orbe("awaiting_confirmation")
        else:
            self._pending_plan = None
            orbe_state = _ORBE_STATUS_MAP.get(result.status, "idle")
            self._update_orbe(orbe_state)

        self._update_clear_button_state()
        self._update_confirm_panel()

    def _handle_confirmation(self, response: str) -> None:
        """Processa resposta de confirmação."""
        self._input.clear()
        self._append("Você", response)

        confirmed = self._confirmation_handler.evaluate_response(response)

        if confirmed is None:
            self._append("Therion", "Resposta não reconhecida. Responda 'sim' ou 'não'.")
            return

        if confirmed:
            self._update_orbe("executing")

        try:
            final_result = self._orchestrator.confirm_and_execute(
                self._pending_plan, confirmed=confirmed
            )
        except Exception:
            self._pending_plan = None
            self._update_orbe("error")
            self._append("Therion", "Ocorreu um erro inesperado ao processar a confirmação.")
            self._update_clear_button_state()
            self._update_confirm_panel()
            return

        self._pending_plan = None
        self._append("Therion", final_result.message)
        orbe_state = _ORBE_STATUS_MAP.get(final_result.status, "idle")
        self._update_orbe(orbe_state)
        self._update_clear_button_state()
        self._update_confirm_panel()

    def _append(self, sender: str, text: str) -> None:
        """Adiciona mensagem ao histórico com formatação visual diferenciada.

        Segurança: todo conteúdo de texto é escapado via html.escape()
        antes de envolver em tags HTML estruturais.
        """
        safe_text = html.escape(text).replace("\n", "<br>")

        if sender == "Você":
            block = (
                '<table width="100%" cellspacing="0" cellpadding="0" '
                'style="margin:8px 0;"><tr>'
                '<td align="right">'
                '<span style="'
                "color:" + _ACCENT_HOVER + ";"
                "font-size:11px;"
                "font-weight:bold;"
                '">Você</span><br>'
                '<table align="right" cellspacing="0" cellpadding="0" '
                'style="'
                "width:auto;"
                "max-width:72%;"
                "background-color:" + _MSG_USER_BG + ";"
                "border:1px solid #6b3a14;"
                "border-radius:10px;"
                '"><tr><td style="'
                "color:" + _MSG_USER_FG + ";"
                "padding:10px 14px;"
                "font-size:13px;"
                '">' + safe_text + '</td></tr></table>'
                '</td></tr></table>'
            )
        else:
            block = (
                '<table width="100%" cellspacing="0" cellpadding="0" '
                'style="margin:8px 0;"><tr>'
                '<td align="left">'
                '<span style="'
                "color:" + _ACCENT_HOVER + ";"
                "font-size:11px;"
                "font-weight:bold;"
                '">Therion</span><br>'
                '<table align="left" cellspacing="0" cellpadding="0" '
                'style="'
                "width:auto;"
                "max-width:72%;"
                "background-color:" + _MSG_THERION_BG + ";"
                "border:1px solid #242424;"
                "border-radius:10px;"
                '"><tr><td style="'
                "color:" + _MSG_THERION_FG + ";"
                "padding:10px 14px;"
                "font-size:13px;"
                '">' + safe_text + '</td></tr></table>'
                '</td></tr></table>'
            )

        self._history.append(block)
        self._history.verticalScrollBar().setValue(
            self._history.verticalScrollBar().maximum()
        )

    def _clear_conversation(self) -> None:
        """Limpa apenas o histórico visual da conversa."""
        self._history.clear()

    def _update_clear_button_state(self) -> None:
        """Habilita/desabilita o botão Limpar conforme _pending_plan."""
        self._clear_button.setEnabled(self._pending_plan is None)

    def _on_confirm(self) -> None:
        """Botão Confirmar: reutiliza fluxo existente de confirmação."""
        self._handle_confirmation("sim")

    def _on_cancel(self) -> None:
        """Botão Cancelar: reutiliza fluxo existente de confirmação."""
        self._handle_confirmation("não")

    def _update_confirm_panel(self) -> None:
        """Mostra/esconde o painel de confirmação conforme _pending_plan."""
        visible = self._pending_plan is not None
        if hasattr(self, "_confirm_panel"):
            self._confirm_panel.setVisible(visible)
            if visible and hasattr(self, "_confirm_description"):
                desc = getattr(self._pending_plan, "description", None) or ""
                self._confirm_description.setText(
                    str(desc) if desc else "Deseja prosseguir com esta ação?"
                )
            if visible and hasattr(self, "_history"):
                scrollbar = self._history.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

    def _update_orbe(self, state: str) -> None:
        """Atualiza a aparência do orbe e o label de estado.

        Não executa lógica de negócio — apenas mudanças visuais.
        Resiliente quando widgets ainda não existem (ex: testes com _setup_ui mockado).
        """
        color, text = _ORBE_STATES.get(state, (_ORBE_IDLE, "Pronto"))
        if hasattr(self, "_orbe"):
            self._orbe.setStyleSheet(
                f"background-color: {color}; border-radius: 28px;"
            )
        if hasattr(self, "_orbe_label"):
            self._orbe_label.setText(text)

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
