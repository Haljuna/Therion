"""Interface desktop mínima para Therion V1."""

import html
import os
import sys
import threading
import time
from therion.voice.echo import strip_spoken_echo_prefix
from dataclasses import replace
from datetime import datetime, timedelta
from therion.logging.conversation_log import ConversationLog
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
from PySide6.QtGui import QAction, QKeyEvent, QFont, QIcon, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QEvent
from shiboken6 import isValid
from .surface_dialogs import MessageBox as QMessageBox

_ICONE_PATH = Path(__file__).resolve().parent.parent / "assets" / "therion-orb.ico"
_WAKE_SOUND_PATH = Path(__file__).resolve().parent.parent / "assets" / "wake.wav"

from therion.calendar.adapter import CalendarError
from therion.calendar.google_adapter import GoogleCalendarAdapter
from therion.config import load_config, save_config
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import OrchestrationResult, Orchestrator, Plan
from therion.context.second_brain import SecondBrainReader
from therion.memory.runtime import KnowledgeRuntime
from therion.interface.native_accessibility import prepare_native_accessibility
from therion.interface.mini_orb import MiniOrb
from therion.governance.confirmation import ConfirmationHandler
from therion.voice.capture import AudioCaptureService
from therion.voice.pipeline import VoicePipeline
from therion.voice.cycle import VoiceCycle
from therion.voice.service import VoiceModelService
from therion.voice.preparation import VoicePreparation
from therion.voice.transcription import VoiceTranscriptionService
from therion.voice.wake import WakeListener


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
    "ai_unavailable": "error",
    "ai_timeout": "error",
    "ai_invalid_response": "error",
    "partial":"partial",
    "uncertain":"uncertain",
    "clarification":"clarification",
}

_ORBE_STATES: dict[str, tuple[str, str]] = {
    "listening": (_ORBE_IDLE, "Ouvindo"),
    "idle": (_ORBE_IDLE, "Pronto"),
    "thinking": (_ORBE_THINKING, "Pensando..."),
    "responding": (_ORBE_RESPONDING, "Respondendo"),
    "awaiting_confirmation": (_ORBE_CONFIRM, "Aguardando confirmação"),
    "executing": (_ORBE_EXECUTING, "Executando..."),
    "success": (_ORBE_SUCCESS, "Concluído"),
    "error": (_ORBE_ERROR, "Erro"),
    "partial": (_ACCENT, "Parcial"),
    "uncertain": ("#eab308", "Resultado incerto"),
    "clarification": (_ORBE_IDLE, "Aguardando sua resposta"),
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
    "#btnVoice {"
    "  background-color: " + _BG_INPUT + ";"
    "  color: " + _TEXT_SECONDARY + ";"
    "  border: 1px solid " + _BORDER + ";"
    "  border-radius: 8px;"
    "  padding: 8px 14px;"
    "  font-size: 13px;"
    "  font-weight: bold;"
    "}"
    "#btnVoice:hover { color: " + _ACCENT_HOVER + "; border: 1px solid " + _ACCENT + "; }"
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


CONVERSATION_WINDOW_SECONDS = 8.0


def log_autonomy_error(error, path=None):
    """Traceback só no PC: a tela mostra o tipo; aqui fica a causa (21/11: "TypeError" sem rastro)."""
    import traceback
    path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Therion' / 'logs' / 'autonomia-erros.txt'
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding='utf-8', errors='replace')[-20000:] if path.exists() else ''
        path.write_text(old + f'--- {datetime.now():%d/%m/%Y %H:%M:%S}\n' + ''.join(traceback.format_exception(error)), encoding='utf-8')
    except OSError:
        pass   # registrar não pode derrubar as rotinas


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


class _CommandWorker(QThread):
    """Executa somente o Orchestrator, sem acessar widgets Qt."""

    presentation_requested = Signal(str,object)

    def __init__(self, orchestrator: Orchestrator, command: str) -> None:
        super().__init__()
        self._orchestrator = orchestrator
        self._command = command
        self.session_id = orchestrator.session_id if isinstance(orchestrator, Orchestrator) else None
        self.confirmation_id = orchestrator.confirmation_id if isinstance(orchestrator, Orchestrator) else None
        self.knowledge_policy_epoch = getattr(orchestrator, '_knowledge_policy_epoch', 0)
        self.conversation_generation = None
        self.cancelled = threading.Event()
        self.result: OrchestrationResult | None = None
        self.failed = False

    def run(self) -> None:
        try:
            if isinstance(self._orchestrator, Orchestrator):
                self.result = self._orchestrator.process_session_command(
                    self._command, self.session_id, self.confirmation_id, self.cancelled,self.presentation_requested.emit)
            else:
                self.result = self._orchestrator.process_command(self._command)
        except Exception:
            self.failed = True


class _ConfirmationWorker(QThread):
    """Executa a confirmação no Orchestrator sem acessar widgets Qt."""

    def __init__(self, orchestrator: Orchestrator, plan: Plan, confirmed: bool) -> None:
        super().__init__()
        self._orchestrator = orchestrator
        self._plan = plan
        self._confirmed = confirmed
        self.session_id = orchestrator.session_id if isinstance(orchestrator, Orchestrator) else None
        self.confirmation_id = orchestrator.confirmation_id if isinstance(orchestrator, Orchestrator) else None
        self.knowledge_policy_epoch = getattr(orchestrator, '_knowledge_policy_epoch', 0)
        self.conversation_generation = None
        self.cancelled = threading.Event()
        self.result: OrchestrationResult | None = None
        self.failed = False

    def run(self) -> None:
        try:
            if isinstance(self._orchestrator, Orchestrator):
                self.result = self._orchestrator.confirm_session_proposal(
                    self._plan, self._confirmed, self.session_id, self.confirmation_id, self.cancelled)
            else:
                self.result = self._orchestrator.confirm_and_execute(self._plan, confirmed=self._confirmed)
        except Exception:
            self.failed = True


class MainWindow(QMainWindow):
    """Janela principal mínima do Therion."""
    _warm_finished = Signal(int, bool)
    _focus_mail_ready = Signal(object)   # (minutos focados, avisos guardados, e-mails, começo) da thread do fim do foco
    _wake_heard = Signal(object, float, object)   # (áudio depois do nome, pontuação, marca no buffer) da thread do detector
    _wake_problem = Signal(str)
    # Reuso curto evita um segundo preload ao clicar depois da abertura. Não é
    # monitoramento da saúde do Ollama; falhas reais invalidam a prontidão.
    _AI_READY_TTL_SECONDS = 60

    def __init__(
        self,
        app: QApplication,
        config: dict | None = None,
        *,
        voice_service: Optional[VoiceModelService] = None,
        voice_pipeline: Optional[VoicePipeline] = None,
        knowledge_runtime=None,
        config_loader=None,
        config_writer=None,
        log_dir=None,
        autonomy_runtime=None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Therion")
        self.resize(800, 600)
        self._app = app
        self._config = config or {}
        # Nota local da conversa para análise de erros (ui.conversation_log); nunca trava a interface.
        self._conversation_log = ConversationLog(enabled=(self._config.get('ui') or {}).get('conversation_log') is True)
        # Aviso antes do compromisso (ui.event_reminders); usa só a agenda do panorama pedido pelo usuário.
        from therion.interface.reminders import EventReminders
        self._reminders = EventReminders() if (self._config.get('ui') or {}).get('event_reminders') is True else None
        self._reminder_timer = QTimer(self)
        self._reminder_timer.setInterval(30000)
        self._reminder_timer.timeout.connect(self._poll_reminders)
        # Modo jogo (ui.game_mode): em tela cheia, tira o modelo da placa de vídeo.
        self._game_mode = (self._config.get('ui') or {}).get('game_mode') is True
        self._game_polls = 0
        self._game_unloaded = False
        self._game_forced = False
        self._game_thread = None
        # Vigia do PC (ui.pc_watch, ligado por padrão): avisa uma vez quando disco C, memória ou placa de vídeo apertam.
        from therion.interface.pc_watch import PcWatch
        self._pc_watch = PcWatch() if (self._config.get('ui') or {}).get('pc_watch') is True else None
        self._pc_watch_ticks = 0
        self._pc_watch_thread = None
        self._pc_watch_said = []
        # Mini orbe flutuante (ui.mini_orb, ligada por padrão): espelha o estado do orbe e do vigia.
        self._orbe_state = 'idle'
        self._mini_orb = None
        if (self._config.get('ui') or {}).get('mini_orb') is True:
            self._mini_orb = MiniOrb(path=os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Therion', 'mini_orb.json'),
                                     on_open_main=self._show_window)
            self._mini_orb.show()
        # Lembretes por voz e foco não têm chave de config: o tique de 30 s roda sempre (reserva do disparo na hora).
        self._reminder_timer.start()
        self._reminder_shot = QTimer(self)   # disparo na hora: armado até o próximo lembrete
        self._reminder_shot.setSingleShot(True)
        self._reminder_shot.setTimerType(Qt.PreciseTimer)
        self._reminder_shot.timeout.connect(self._fire_reminders)
        self._reminders_mtime = None
        self._focus_shot = QTimer(self)   # fim do foco ou da pausa, na hora
        self._focus_shot.setSingleShot(True)
        self._focus_shot.setTimerType(Qt.PreciseTimer)
        self._focus_shot.timeout.connect(self._focus_due)
        self._focus_view = None   # payload do foco/pausa ligado (as orbes desenham o tempo daqui); None = desligado
        self._timer_tick = QTimer(self)   # minutos e arco nas duas orbes: 1 vez por segundo, só com foco/pausa
        self._timer_tick.setInterval(1000)
        self._timer_tick.timeout.connect(self._show_timer)
        self._focus_mail_thread = None
        self._focus_mail_token = None
        self._focus_held_unsaid = None   # avisos do foco cuja fala ainda não saiu
        self._focus_mail_ready.connect(self._focus_summary)
        self._spoken_queue = []   # falas que nasceram sozinhas, esperando o Therion ficar livre
        self._next_user_channel = 'texto'
        self._command_started_at = None
        self._tray_icon: QSystemTrayIcon | None = None
        self._closing = False
        self._changing_window_mode=False
        self._windowed_geometry=None
        self._therion_icon = self._load_icon()
        real_actions_enabled = self._config.get("runtime", {}).get("real_actions_enabled", False)
        calendar_adapter = self._build_calendar_adapter()
        ai_core = self._build_ai_core()
        orch_kwargs: dict = {"simulate": not real_actions_enabled}
        if 'agent' in self._config:
            orch_kwargs['agent_config'] = self._config['agent']
        self._agent_config_writer = config_writer or save_config
        self._agent_config_loader = config_loader or load_config
        self._agent_panel = None
        if autonomy_runtime is not None:
            orch_kwargs['autonomy_runtime'] = autonomy_runtime
        if log_dir is not None:
            orch_kwargs['log_dir'] = log_dir
        if knowledge_runtime is None and 'knowledge_access' in self._config:
            state_root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData'/'Local')))/'Therion'/'memory'
            knowledge_runtime = KnowledgeRuntime(SecondBrainReader.DEFAULT_VAULT_ROOT, state_root,
                config_loader or (lambda: self._config), config_writer=config_writer)
        if knowledge_runtime is not None:
            orch_kwargs['knowledge_runtime'] = knowledge_runtime
            orch_kwargs['vault_root'] = knowledge_runtime.vault_root
        calendar_time_zone = self._config.get('calendar', {}).get('time_zone')
        if calendar_time_zone is not None:
            orch_kwargs['calendar_time_zone'] = calendar_time_zone
        if calendar_adapter is not None:
            orch_kwargs["calendar_adapter"] = calendar_adapter
        if ai_core is not None:
            orch_kwargs["ai_core"] = ai_core
        conversation_config = self._config.get('conversation', {})
        if isinstance(conversation_config, dict):
            profile_path = conversation_config.get('user_profile_path')
            if isinstance(profile_path, str) and profile_path.strip():
                orch_kwargs['user_profile_path'] = profile_path
        if isinstance(self._config.get('assistant_identity'), dict):
            orch_kwargs['assistant_identity'] = self._config['assistant_identity']
        self._orchestrator = Orchestrator(**orch_kwargs)
        self._orchestrator._agent_ui_confirmations=True
        self._orchestrator.desktop_timers = True   # lembretes e foco só existem com a janela
        self._v4_worker = None
        self._autonomy_panel = None
        self._autonomy_runtime = autonomy_runtime
        if autonomy_runtime is not None:
            from therion.autonomy.routines import RoutineService, RoutineScheduler
            from therion.autonomy.procedures import ProcedureMemory
            from therion.autonomy.windows import session_unlocked
            self._routine_service = RoutineService(self._orchestrator, autonomy_runtime)
            self._routine_scheduler = RoutineScheduler(self._routine_service, session_unlocked)
            self._procedure_memory = ProcedureMemory(self._orchestrator, autonomy_runtime)
        self._v4_timer = QTimer(self)
        self._v4_timer.setInterval(30000)
        self._v4_timer.timeout.connect(self._poll_autonomy)
        self._confirmation_handler = ConfirmationHandler()
        self._pending_plan: Optional[Plan] = None
        self._processing = False
        self._workflow_clear_pending = False
        self._command_worker: _CommandWorker | None = None
        self._confirmation_worker: _ConfirmationWorker | None = None
        self._quit_requested = False
        self._speech_output = None
        self._speech_text = ''
        self._conversation_mode = False
        self._conversation_generation = 0
        self._conversation_capture_generation = None
        self._conversation_confirmation_plan = None
        self._conversation_confirmation_token = None
        self._conversation_primed = False
        self._conversation_listen_after = 0.0
        self._last_conversation_spoken = ''
        self._conversation_capture_started_at = 0.0
        self._wake = None
        self._wake_turn = None      # áudio depois do nome, à espera da primeira captura
        self._wake_mark = None      # ponto do disparo no buffer do detector
        self._wake_score = None     # disparo ainda sem desfecho no registro
        self._wake_opened = False   # conversa aberta pelo nome: continuação de 8 s e volta a dormir no silêncio
        self._wake_sound = None
        self._wake_end_after_reply = False   # "para de me ouvir" dentro da conversa: encerra depois de responder
        self._ai_warm_ready = False
        self._ai_preparing = False
        self._ai_warm_token = 0
        self._ai_warm_generation = None
        self._ai_preparation_epoch = 0
        self._ai_warm_epoch = 0
        self._ai_warm_core = None
        self._ai_resource_core = None
        self._ai_resource_ready_at = None
        self._ai_warm_clock = time.monotonic
        self._preparation = VoicePreparation()
        self._conversation_timer = QTimer(self)
        self._conversation_timer.setInterval(50)
        self._conversation_timer.timeout.connect(self._poll_conversation)
        self._memory_timer = QTimer(self)
        self._memory_timer.setInterval(1000)
        self._memory_timer.timeout.connect(self._poll_memory_previews)
        self._memory_timer.start()
        self._warm_finished.connect(self._on_ai_warmed)

        model_path = self._config.get("voice", {}).get("model_path")
        if voice_service is not None:
            self._voice_service = voice_service
        else:
            voice_options = self._config.get('voice', {})
            self._voice_service = VoiceModelService(model_path,
                provider=voice_options.get('provider', 'whisper'),
                endpoint=voice_options.get('endpoint'))
        self._voice_service.loaded.connect(self._on_voice_model_loaded)
        self._voice_service.load_failed.connect(self._on_voice_model_failed)
        self._voice_service.state_changed.connect(self._on_voice_model_state_changed)
        self._voice_pipeline: Optional[VoicePipeline] = voice_pipeline

        if not self._therion_icon.isNull():
            self.setWindowIcon(self._therion_icon)
        self._setup_ui()
        self._fullscreen_shortcut=QShortcut(QKeySequence('F11'),self)
        self._fullscreen_shortcut.activated.connect(self._toggle_full_screen)
        self._native_accessibility_state = prepare_native_accessibility(self)
        if self._config.get('tts', {}).get('enabled') is True:
            from therion.voice.speech_output import SpeechOutput
            self._speech_output = SpeechOutput(self._config['tts'], self)
            self._speech_output.failed.connect(self._on_speech_failed)
            self._speech_output.changed.connect(self._on_speech_state)
            self._speech_output.warmed.connect(self._on_speech_warmed)
            self._speech_output.completed.connect(self._conversation_playback_finished)
            QApplication.instance().aboutToQuit.connect(self._speech_output.shutdown)
        self._start_wake()
        self._setup_tray()
        if autonomy_runtime is not None:
            self._v4_timer.start()
        if self._config.get('tts', {}).get('warm_on_start') is True:
            QTimer.singleShot(200, self._prepare_voice_background)
        self._dashboard = None
        self._classic_ui = self.centralWidget()
        self._interface_stack = None
        if self._config.get('ui', {}).get('interface') == 'constellation':
            self._select_interface('constellation', persist=False)
        QTimer.singleShot(0, self, self._fire_reminders)   # atrasados de quando o Therion estava fechado
        QTimer.singleShot(0, self, self._resume_focus)

    def _select_interface(self, interface, *, persist=True):
        """Troca somente a apresentação; os donos da sessão e do áudio permanecem."""
        was_fullscreen=self.isFullScreen()
        from PySide6.QtWidgets import QStackedWidget, QScrollArea
        from copy import deepcopy
        if interface not in {'classic', 'constellation'}:
            return
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and (dashboard.action_worker is not None or dashboard.surfaces.busy):
            return
        if persist:
            config = deepcopy(self._agent_config_loader())
            config.setdefault('ui', {})['interface'] = interface
            try:
                self._agent_config_writer(config)
            except Exception:
                self._append('Therion', 'Não consegui salvar a preferência de interface. A sessão foi preservada.')
                return
            self._config['ui'] = deepcopy(config['ui'])
        if interface == 'constellation':
            if self._interface_stack is None:
                self._classic_ui = self.takeCentralWidget()
                self._interface_stack = QStackedWidget()
                self._interface_stack.addWidget(self._classic_ui)
                self.setCentralWidget(self._interface_stack)
            if self._dashboard is None:
                from therion.interface.dashboard import Dashboard
                self._dashboard = Dashboard(self, self._classic_ui)
                self._dashboard.setMinimumSize(960,640)
                self._dashboard_scroll = QScrollArea()
                self._dashboard_scroll.setWidgetResizable(True)
                self._dashboard_scroll.setFrameShape(QFrame.NoFrame)
                self._dashboard_scroll.setWidget(self._dashboard)
                self._interface_stack.addWidget(self._dashboard_scroll)
            self._dashboard.attach_controls()
            self._dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._dashboard_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._classic_ui.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._interface_stack.setCurrentWidget(self._dashboard_scroll)
            if getattr(self, '_last_ui_response', ''):
                self._dashboard.response('Therion', self._last_ui_response)
            self._dashboard.presentation.speech = getattr(self._speech_output, 'state', 'idle')
            self._dashboard.presentation.capture = getattr(self._voice_pipeline, 'state', 'idle')
            if self._processing:
                self._dashboard.interaction('thinking')
            screen = self.screen().availableGeometry()
            # Em escala alta a área útil pode ser menor que o canvas mínimo.
            # A rolagem externa mantém inclusive os controles inferiores acessíveis.
            self.setMinimumSize(min(960,screen.width()), min(640,screen.height()))
            if not was_fullscreen:self.resize(min(1440, screen.width()), min(900, screen.height()))
            self._dashboard.activate(True)
        elif self._dashboard is not None:
            self._dashboard.activate(False)
            self._dashboard.detach_controls()
            self._dashboard.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._dashboard_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self._classic_ui.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._interface_stack.setCurrentWidget(self._classic_ui)
            self.setMinimumSize(0, 0)
            if not was_fullscreen:self.resize(800, 600)
        speech = getattr(self, '_speech_output', None)
        if speech is not None:
            speech.set_meter_enabled(interface == 'constellation')
        if was_fullscreen:
            self._changing_window_mode=True
            try:self.showFullScreen()
            finally:QTimer.singleShot(0,self._finish_window_mode_change)
        self._sync_full_screen_controls()

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
        provider_options = {}
        if "endpoint" in ai_config:
            provider_options["endpoint"] = ai_config["endpoint"]
        if "think" in ai_config:
            provider_options["think"] = ai_config["think"]
        agent_config = self._config.get('agent', {})
        if agent_config.get('enabled') is True:
            provider_options['context_tokens'] = agent_config.get('context_tokens', 8192)
        # Groq na nuvem com o Ollama local de reserva, só quando escolhido na configuração.
        if ai_config.get('online') == 'groq':
            from therion.core.ai_provider_groq import GroqProvider as provider_class
        else:
            provider_class = OllamaProvider
        provider = provider_class(model=model, timeout=timeout_seconds, **provider_options)
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
        self._autonomy_button = QPushButton('Autonomia')
        self._autonomy_button.setEnabled(self._autonomy_runtime is not None)
        self._autonomy_button.clicked.connect(self._show_autonomy)
        top_layout.addWidget(self._autonomy_button)
        self._agent_button = QPushButton('Capacidades')
        self._agent_button.clicked.connect(self._show_agent_panel)
        top_layout.addWidget(self._agent_button)
        interface_button = QPushButton('Constelação')
        interface_button.setToolTip('Abrir o painel Constelação sem encerrar a sessão')
        interface_button.clicked.connect(lambda:self._select_interface('constellation', persist=False))
        top_layout.addWidget(interface_button)
        self._clear_button.setObjectName("btnClear")
        self._clear_button.setCursor(Qt.PointingHandCursor)
        self._clear_button.clicked.connect(self._clear_conversation)
        top_layout.addWidget(self._clear_button)

        self._fullscreen_button=QPushButton('⛶')
        self._fullscreen_button.setFixedWidth(32);self._fullscreen_button.setCheckable(True)
        self._fullscreen_button.clicked.connect(self._toggle_full_screen)
        top_layout.addWidget(self._fullscreen_button)
        self._sync_full_screen_controls()

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
        conversation_layout = QHBoxLayout()
        self._conversation_button = QPushButton('Conversar por voz')
        self._conversation_button.setToolTip('Enquanto ativo, as respostas são faladas, inclusive para mensagens digitadas.')
        self._conversation_button.clicked.connect(self._toggle_conversation)
        self._conversation_button.setEnabled(self._config.get('tts', {}).get('enabled') is True)
        conversation_layout.addWidget(self._conversation_button)
        self._conversation_label = QLabel('')
        conversation_layout.addWidget(self._conversation_label)
        conversation_layout.addStretch()
        self._workflow_label = QLabel('')
        self._workflow_label.setTextFormat(Qt.PlainText)
        conversation_layout.addWidget(self._workflow_label)
        self._workflow_cancel_button = QPushButton('Parar')
        self._workflow_cancel_button.setToolTip('Interromper a tarefa e a inferência em andamento')
        self._workflow_cancel_button.clicked.connect(self._on_workflow_cancel)
        self._workflow_cancel_button.hide()
        conversation_layout.addWidget(self._workflow_cancel_button)
        self._preparation_label = QLabel('')
        self._preparation_label.setTextFormat(Qt.PlainText)
        self._preparation_label.setWordWrap(True)
        layout.addWidget(self._preparation_label)
        layout.addLayout(conversation_layout)
        self._voice_provider_notice=QLabel('Voz online: o texto falado será enviado ao serviço Microsoft Edge TTS.')
        if self._config.get('tts',{}).get('provider')=='voicestudio':
            self._voice_provider_notice.setText('Voz via VoiceStudio local. Mantenha o aplicativo aberto para ouvir as respostas.')
        self._voice_provider_notice.setWordWrap(True)
        self._voice_provider_notice.setVisible(self._config.get('tts',{}).get('enabled') is True
            and self._config.get('tts',{}).get('provider') in ('edge','voicestudio'))
        layout.addWidget(self._voice_provider_notice)
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

        self._voice_button = QPushButton("Falar")
        self._voice_button.setObjectName("btnVoice")
        self._voice_button.clicked.connect(self._on_voice_clicked)
        self._voice_button.pressed.connect(self._on_voice_pressed)
        self._voice_button.released.connect(self._on_voice_released)
        input_layout.addWidget(self._voice_button)
        self._listen_button = QPushButton('Ouvir')
        self._listen_button.setEnabled(False)
        self._listen_button.clicked.connect(self._listen_response)
        input_layout.addWidget(self._listen_button)
        self._stop_speech_button = QPushButton('Parar fala')
        self._stop_speech_button.setToolTip('Interromper somente a reprodução da voz')
        self._stop_speech_button.setEnabled(False)
        self._stop_speech_button.clicked.connect(self._stop_speech)
        input_layout.addWidget(self._stop_speech_button)

        layout.addLayout(input_layout)
        self._agent_details_button=QPushButton('Detalhes da tarefa')
        self._agent_details_view=QPlainTextEdit()
        self._agent_details_view.setReadOnly(True)
        self._agent_details_view.setMaximumHeight(140)
        self._agent_details_view.hide()
        self._agent_details_button.clicked.connect(lambda:self._agent_details_view.setVisible(not self._agent_details_view.isVisible()))
        layout.addWidget(self._agent_details_button)
        layout.addWidget(self._agent_details_view)

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
        if self._autonomy_runtime is not None:
            action_autonomy = QAction('Autonomia', self)
            action_autonomy.triggered.connect(self._show_autonomy)
            tray_menu.addAction(action_autonomy)
            action_pause = QAction('Pausar toda autonomia', self)
            action_pause.triggered.connect(self._pause_autonomy)
            tray_menu.addAction(action_pause)
        action_quit.triggered.connect(self._quit_application)
        tray_menu.addAction(action_quit)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.setToolTip("Therion")
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _show_window(self) -> None:
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and self._interface_stack.currentWidget() is self._dashboard_scroll:
            dashboard.activate(True)
        """Mostra e traz a janela para frente."""
        if self.isMinimized():
            self._changing_window_mode=True
            try:self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
            finally:QTimer.singleShot(0,self._finish_window_mode_change)
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_agent_panel(self,*,index=0):
        from therion.interface.agent_panel import AgentPanel
        runtime=getattr(self._orchestrator,'_agent_runtime',None)
        if not self._processing or getattr(runtime,'waiting_confirmation',False):
            dashboard=getattr(self,'_dashboard',None)
            if dashboard is not None and dashboard.active:
                try:return dashboard.open_agent(index)
                except (OSError,ValueError):
                    self._append('Therion','Não consegui abrir capacidades ou histórico. Os dados foram preservados.');return
            try:self._agent_panel=AgentPanel(self._orchestrator, self._config, self._agent_config_writer, self)
            except (OSError,ValueError):
                QMessageBox.information(self,'Capacidades','Não consegui abrir o histórico ou os recibos. Os dados foram preservados; não reiniciei o banco automaticamente.')
                return
            try:self._agent_panel.exec()
            finally:self._agent_panel.deleteLater();self._agent_panel=None

    def _show_autonomy(self):
        if self._autonomy_runtime is None:
            return
        dashboard=getattr(self,'_dashboard',None)
        if dashboard is not None and dashboard.active:
            return dashboard.open_autonomy()
        self._end_conversation()
        if self._autonomy_panel is None or getattr(self._autonomy_panel,'_surface_dashboard',None) is not None:
            from therion.interface.autonomy_panel import AutonomyPanel
            self._autonomy_panel = AutonomyPanel(self, self._autonomy_runtime,
                self._routine_service, self._procedure_memory)
        self._autonomy_panel.refresh()
        self._autonomy_panel.show()
        self._autonomy_panel.raise_()

    def _pause_autonomy(self):
        try:
            self._autonomy_runtime.pause()
            self._append('Therion', 'Toda autonomia foi pausada. Políticas e histórico foram preservados.')
        except Exception:
            self._v4_timer.stop()
            self._append('Therion', 'Não confirmei a pausa persistente. Suspendi as rotinas nesta sessão; confira o painel.')

    def _poll_autonomy(self):
        if (self._autonomy_runtime is None or self._v4_worker is not None or self._processing
                or self._pending_plan is not None or self._conversation_mode or self._closing
                or self._quit_requested or (self._autonomy_panel and self._autonomy_panel.isVisible())):
            return
        from therion.interface.autonomy_panel import V4Job
        def task():
            try:
                return poll()
            except Exception as error:
                log_autonomy_error(error)
                # Só o tipo: a mensagem do erro pode ter caminho ou dado pessoal.
                raise RuntimeError(type(error).__name__) from error
        def poll():
            messages = []
            due = self._routine_scheduler.next_due()
            if due is not None:
                result = self._routine_scheduler.run(*due)
                if result.status != 'busy':
                    messages.append(result.message)
            if self._routine_scheduler.unlocked():
                try:
                    messages.extend(self._procedure_memory.poll())
                except ValueError:
                    pass  # Sem destino/acesso vigente: nenhuma gravação automática.
            return messages
        worker = V4Job(task, self)
        self._v4_worker = worker
        payloads = []
        worker.completed.connect(payloads.append)
        def finished():
            self._v4_worker = None
            worker.deleteLater()
            ok, value = payloads[0] if payloads else (False, '')
            if not ok:
                self._v4_timer.stop()
                kind = f' ({value})' if value else ''
                self._append('Therion', f'Suspendi as rotinas por falha de estado{kind}. Confira o painel Autonomia.')
                return
            for message in value:
                self._append('Therion', message)
            if value and self._tray_icon is not None:
                self._tray_icon.showMessage('Therion', 'Há um resultado de autonomia disponível no aplicativo.')
        worker.finished.connect(finished)
        worker.start()

    def _minimize_window(self) -> None:
        """Minimiza a janela normalmente."""
        self.showMinimized()

    def _toggle_full_screen(self):
        """Altera somente o modo da janela, sem tocar na sessão ou no áudio."""
        if self._closing or self._quit_requested or self._changing_window_mode:return
        self._changing_window_mode=True
        try:
            if self.isFullScreen():
                self.showNormal()
                if self._windowed_geometry is not None:self.restoreGeometry(self._windowed_geometry)
            else:
                self._windowed_geometry=self.saveGeometry()
                self.showFullScreen()
            self._sync_full_screen_controls()
        finally:
            QTimer.singleShot(0,self._finish_window_mode_change)

    def _finish_window_mode_change(self):
        if not isValid(self):return
        self._changing_window_mode=False;self._sync_full_screen_controls()

    def _sync_full_screen_controls(self):
        full=self.isFullScreen()
        title='Sair da tela cheia' if full else 'Tela cheia'
        classic=getattr(self,'_fullscreen_button',None)
        if classic is not None and isValid(classic):
            classic.setChecked(full);classic.setText('❐' if full else '⛶')
            classic.setToolTip(title+' (F11)');classic.setAccessibleName(title)
        dashboard=getattr(self,'_dashboard',None)
        if dashboard is not None and isValid(dashboard):dashboard.sync_full_screen(full)

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QEvent.WindowStateChange:self._sync_full_screen_controls()

    def _on_tray_activated(self, reason: int) -> None:
        """Trata ativações do ícone da bandeja."""
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _send_command(self) -> None:
        """Envia o comando digitado para o Orchestrator."""
        if self._processing:
            return
        command = self._input.toPlainText().strip()
        if not command:
            return
        if self._conversation_mode:
            # A origem digitada não muda o canal de resposta escolhido.
            # Invalida a captura anterior sem encerrar a sessão de voz.
            self._cancel_voice_if_active()
            self._conversation_capture_generation = None
            self._conversation_confirmation_plan = None
            self._conversation_confirmation_token = None

        if self._pending_plan is not None:
            self._handle_confirmation(command)
            return

        self._append("Você", command)
        self._input.clear()

        self._update_orbe("thinking")

        self._set_processing(True)
        try:
            self._start_command_worker(command)
        except Exception:
            self._command_worker = None
            self._update_orbe("error")
            self._speech_text = "Ocorreu um erro inesperado ao processar o comando."
            self._append("Therion", self._speech_text)
            self._set_processing(False)
            if self._conversation_mode:
                self._conversation_reply()

    def _start_command_worker(self, command: str) -> None:
        if self._closing or self._quit_requested:return
        if hasattr(self,'_agent_details_view'):self._agent_details_view.clear()
        self._briefing_intro=None
        self._command_started_at = time.monotonic()
        worker = _CommandWorker(self._orchestrator, command)
        worker.conversation_generation = self._conversation_generation if self._conversation_mode else None
        self._command_worker = worker
        self._begin_progress_narration(worker)
        worker.finished.connect(self._finish_command)
        worker.presentation_requested.connect(lambda action,payload:self._present_worker(worker,action,payload))
        worker.start()

    def _poll_game_mode(self, full_screen):
        # Dois ciclos seguidos (~1 min) em tela cheia: é jogo ou vídeo, não uma troca rápida de janela.
        self._game_polls = self._game_polls + 1 if full_screen else 0
        if not full_screen:
            self._game_unloaded = False
        provider = getattr(getattr(self._orchestrator, 'ai_core', None), '_provider', None)
        if self._game_polls < 2 or self._game_unloaded or self._processing or not hasattr(provider, 'unload'):
            return
        self._unload_model()
        # 19/11: entrar e sair da tela cheia repetia o aviso a cada partida; uma vez por hora basta.
        shown, now = getattr(self, '_game_notice_at', None), time.monotonic()
        if shown is not None and now - shown < 3600:
            return
        self._game_notice_at = now
        message = 'Modo jogo: liberei a placa de vídeo. Meu primeiro pedido depois disso demora um pouco mais.'
        if not self._focus_hold(message):
            self._append('Therion', message)

    def _unload_model(self):
        provider = getattr(getattr(self._orchestrator, 'ai_core', None), '_provider', None)
        if not hasattr(provider, 'unload'):
            return
        self._game_unloaded = True
        def unload():
            try:
                provider.unload()
            except Exception:
                pass  # sem o Ollama no ar não há o que liberar
        self._game_thread = threading.Thread(target=unload, name='therion-game-mode', daemon=True)
        self._game_thread.start()

    def _set_game_mode(self, on):
        """Pedido falado ou digitado ("modo de jogo" / "sair do modo de jogo"); vale até o usuário desligar."""
        self._game_forced = on
        self._game_unloaded = False
        if self._mini_orb is not None:
            from therion.interface import reminders
            self._mini_orb.set_quiet(on or reminders.do_not_disturb())   # sem esperar o tick de 30 s
            self._mini_orb.set_game(on)
        constellation = getattr(self._dashboard, 'constellation', None)
        if constellation is not None:
            constellation.set_game(on)   # arcos e núcleo vermelhos também no painel
        if on:
            self._unload_model()
            if not self._reminder_timer.isActive():
                self._reminder_timer.start()   # os avisos guardados saem quando o modo for desligado
        # A janela vai para o modo compacto com o jogo e volta só se foi o modo jogo que a encolheu.
        dashboard = self._dashboard if self._dashboard is not None and self._dashboard.active else None
        if dashboard is not None and on and not dashboard.compact:
            dashboard.set_compact(True)
            self._game_compacted = dashboard.compact
        elif dashboard is not None and not on and getattr(self, '_game_compacted', False):
            dashboard.set_compact(False)
            self._game_compacted = False

    def _poll_reminders(self):
        if self._closing or self._quit_requested:
            return
        from therion.interface import reminders
        full_screen = reminders.do_not_disturb()
        if self._mini_orb is not None:
            self._mini_orb.set_quiet(full_screen or self._game_forced)
            rect = reminders.fullscreen_screen()
            self._mini_orb.hide_for_game(rect is not None and rect.intersects(self._mini_orb.frameGeometry()))
            # a cada tick: o problema pode passar sem aviso nenhum, e o âmbar tem de sumir
            self._sync_mini_orb()
        if self._game_mode:
            self._poll_game_mode(full_screen)
        if self._pc_watch is not None:
            self._poll_pc_watch(full_screen)
        from therion.core import voice_reminders
        store = voice_reminders.store()
        mtime = store.mtime()
        if mtime != self._reminders_mtime:   # reserva: alguém gravou o arquivo por fora
            self._reminders_mtime = mtime
            store.reload()
        self._fire_reminders()
        view = self._focus_view
        if view is not None and datetime.now() >= self._focus_end(view):
            self._focus_due()   # reserva: o disparo na hora pode atrasar com o PC dormindo
        if self._reminders is not None:
            busy = self._processing or self._pending_plan is not None or full_screen or self._game_forced
            for message in self._reminders.due(datetime.now(), busy):
                if self._focus_hold(message):
                    continue
                self._append('Therion', message)
                self._speak_when_free(message, write=False)
        self._drain_speech()

    def _fire_reminders(self, now=None):
        """Lembretes vencidos (na hora ou atrasados) entram na porta de fala; fura tela cheia, jogo e foco."""
        if self._closing or self._quit_requested:
            return
        from therion.core import voice_reminders
        store = voice_reminders.store()
        on_time, late, old = store.take_due(now or datetime.now())
        notice, store.broken_notice = store.broken_notice, None
        if notice:
            self._speak_when_free(notice, may_speak_quiet=True)
        if late_text := voice_reminders.late_message(late, old):
            self._speak_when_free(late_text, may_speak_quiet=True)
        if on_time:
            self._speak_when_free(voice_reminders.due_message(on_time), may_speak_quiet=True)
            voice_reminders.snooze_window(self._orchestrator, '; '.join(item.text for item in on_time))
        self._arm_reminder_timer()

    def _arm_reminder_timer(self):
        from therion.core import voice_reminders
        due = voice_reminders.store().next_time()
        if due is None:
            self._reminder_shot.stop()
            return
        milliseconds = (due - datetime.now()).total_seconds() * 1000
        self._reminder_shot.start(int(min(max(milliseconds, 0), 2**31 - 1)))   # se acordar cedo, rearma

    def _speak_when_free(self, text, *, write=True, may_speak_quiet=False, on_spoken=None):
        """Única porta das falas que nascem sozinhas: escreve já, fala só quando livre (speak corta o que toca).
        may_speak_quiet: lembrete e fim do foco falam mesmo em tela cheia/jogo; os outros avisos lá ficam só escritos.
        on_spoken: roda quando a fala sai de fato (ou já, sem voz) — é aí que uma oferta começa a valer."""
        if write:
            self._append('Therion', text)
        if self._speech_output is None:
            if on_spoken is not None:
                on_spoken()
            return
        self._spoken_queue.append((text, may_speak_quiet, on_spoken))
        self._drain_speech()

    def _therion_free(self):
        return (not self._processing and self._pending_plan is None and not self._voice_busy()
                and self._orbe_state not in ('listening', 'transcribing', 'awaiting_confirmation', 'clarification'))

    def _voice_busy(self):
        """Fala tocando/gerando, microfone gravando/transcrevendo ou modelo de voz carregando.
        Não usa o is_quiescent da fala: o processo de voz aquecido fica vivo sem falar nada."""
        speech = self._speech_output
        if getattr(speech, 'state', 'idle') in ('warming', 'synthesizing', 'playing'):
            return True
        # Resposta esperando a voz aquecer (o estado continua "idle") ou áudio guardado/na fila: speak() jogaria fora.
        held = getattr(speech, '__dict__', {})
        if (held.get('_pending') is not None or held.get('_busy') or held.get('_audio_queue')
                or held.get('_active_audio') is not None or held.get('_hold_audio') or held.get('_held_prefix') is not None
                or held.get('_playing')):
            return True
        return any(not getattr(service, 'is_quiescent', True)
                   for service in (self._voice_pipeline, self._voice_service) if service is not None)

    def _drain_speech(self):
        queue = getattr(self, '_spoken_queue', None)
        if not queue or self._speech_output is None or not self._therion_free():
            return
        from therion.interface import reminders
        quiet = self._game_forced or reminders.do_not_disturb()   # vale a regra da hora em que sai, não a da fila
        texts = [text for text, may_speak_quiet, _ in queue if may_speak_quiet or not quiet]
        callbacks = [on_spoken for _, _, on_spoken in queue if on_spoken is not None]
        queue.clear()   # os que ficaram de fora já estão escritos
        if texts:
            self._speech_output.speak(' '.join(texts))   # uma fala só: duas chamadas seguidas cortariam a primeira
        for on_spoken in callbacks:
            on_spoken()   # livre agora: nenhum pedido rodando nem plano esperando o "sim"

    def _drain_speech_later(self):
        # depois do evento atual: o stop() de dentro de outro speak também avisa "idle"
        if getattr(self, '_spoken_queue', None):
            QTimer.singleShot(0, self, self._drain_speech)

    def _poll_pc_watch(self, full_screen):
        quiet = full_screen or self._game_forced   # no jogo ou em tela cheia só escreve, sem voz
        if quiet != self._pc_watch.in_game:
            summary = self._pc_watch.game(quiet)   # ao sair, uma frase com o pior momento da partida
            if summary:
                self._pc_watch_said.append((summary, False))
        if not (self._processing or self._pending_plan is not None):
            while self._pc_watch_said:
                message, cleanup = self._pc_watch_said.pop(0)
                if self._focus_hold(message):
                    continue   # a oferta de limpeza não é rearmada no fim: o "sim" de lá é da pausa
                self._append('Therion', message)
                if cleanup:   # o "sim" da próxima frase limpa os temporários seguros (core/pc_cleanup)
                    from therion.core.pc_cleanup import offer
                    offer(self._orchestrator)   # um dono só para o "sim": a oferta derruba as outras pendências
                if not quiet:
                    self._speak_when_free(message, write=False)
                self._update_orbe(self._orbe_state)   # o âmbar da mini orbe acompanha o problema recém-avisado
        self._pc_watch_ticks += 1
        busy = self._pc_watch_thread is not None and self._pc_watch_thread.is_alive()
        if self._pc_watch_ticks % 4 == 1 and not busy:   # 30 s depois de abrir e depois a cada 2 min
            watch, said = self._pc_watch, self._pc_watch_said
            self._pc_watch_thread = threading.Thread(target=lambda: said.extend(watch.poll()),
                                                     name='therion-pc-watch', daemon=True)
            self._pc_watch_thread.start()

    # --- modo foco -------------------------------------------------------------------------------------
    @staticmethod
    def _focus_end(view):
        return datetime.fromisoformat(view['start']) + timedelta(minutes=view['minutes'])

    def _apply_focus(self, payload):
        """O foco/pausa mudou (pedido respondido ou retomado ao abrir): rearma o fim; foco encerrado → resumo."""
        self._focus_shot.stop()
        self._focus_view = None
        if payload.get('phase') in ('focus', 'pause') and payload.get('start'):
            self._focus_view = dict(payload)
            milliseconds = (self._focus_end(payload) - datetime.now()).total_seconds() * 1000
            self._focus_shot.start(int(min(max(milliseconds, 0), 2**31 - 1)))   # se acordar cedo, rearma
        elif payload.get('ended'):
            self._focus_finished(payload.get('minutes') or 0, datetime.fromisoformat(payload['start']),
                                 payload.get('held') or [])
        self._show_timer()

    def _timer_look(self):
        view = self._focus_view
        if view is None:
            return None
        from therion.core import focus
        state = focus.FocusState(view['phase'], datetime.fromisoformat(view['start']), view['minutes'], [])
        return focus.timer_look(state, datetime.now())

    def _show_timer(self):
        """As duas orbes mostram o tempo do foco/pausa; o tique de 1 s só roda enquanto há tempo a mostrar."""
        look = self._timer_look()
        dashboard = getattr(self, '_dashboard', None)
        for orb in (getattr(self, '_mini_orb', None), getattr(dashboard, 'constellation', None)):
            if orb is not None:
                orb.set_timer(look)
        if look is None:
            self._timer_tick.stop()
        elif not self._timer_tick.isActive():
            self._timer_tick.start()

    def _focus_hold(self, message):
        """Com foco ligado guarda o aviso (vigia, agenda, resumo pós-jogo, modo jogo automático) para o fim,
        sem duplicar. Lembrete nunca passa por aqui. False → o aviso sai agora, como sempre."""
        if self._focus_view is None or self._focus_view.get('phase') != 'focus':
            return False
        from therion.core import focus
        now = datetime.now()
        def keep(state):
            if state.phase != 'focus' or focus.remaining(state, now) <= 0 or message in state.held:
                return state
            return replace(state, held=[*state.held, message])
        try:
            before, _ = focus.store().update(keep)
        except OSError:
            return False   # sem gravar, melhor avisar já do que perder
        return before.phase == 'focus' and focus.remaining(before, now) > 0

    def _focus_due(self, now=None):
        """Disparo na hora (ou o tique de reserva): encerra o foco/pausa que acabou, mesmo com a fala esperando."""
        if self._closing or self._quit_requested:
            return
        from therion.core import focus
        now = now or datetime.now()
        try:
            ended = focus.settle(now)
            state = focus.store().state() if ended is None else None
        except OSError:
            return
        if ended is None:
            if state.phase in ('focus', 'pause') and focus.remaining(state, now) > 0:
                self._apply_focus(focus._payload(state))   # acordou cedo ou o foco foi esticado: rearma
            else:
                self._focus_shot.stop()
                self._focus_view = None
                self._show_timer()
            return
        self._focus_shot.stop()
        self._focus_view = None
        self._show_timer()
        if ended.phase == 'focus':
            self._focus_finished(ended.minutes, ended.start, ended.held)
        else:
            self._speak_when_free(focus.pause_ended_text(focus.next_focus_minutes()), may_speak_quiet=True,
                                  on_spoken=lambda: focus.offer(self._orchestrator, 'again'))

    def _focus_finished(self, minutes_done, start, held):
        """Conta os e-mails numa thread; o resumo sai na thread do Qt (_focus_summary)."""
        if not minutes_done:   # encerrado logo no começo: nada a resumir, só o que foi guardado
            self._write_held(held)
            return
        from therion.agent.contracts import CancellationToken
        from therion.core import focus
        if self._focus_mail_token is not None:
            self._focus_mail_token.cancel()   # dois focos seguidos: a contagem do anterior não fala depois da deste
            if self._focus_held_unsaid is not None:
                self._write_held(self._focus_held_unsaid)   # mas os avisos que ele guardou não se perdem
        self._focus_held_unsaid = list(held)
        token = self._focus_mail_token = CancellationToken()
        host, ready = self._orchestrator, self._focus_mail_ready
        def count():
            try:
                mail = focus.focus_mail(host, start, token)
            except Exception:
                mail = {'error': True}   # caixa sem conta configurada ou estado inesperado: o resto da fala sai
            if token.cancelled:
                return
            try:
                ready.emit((minutes_done, list(held), mail, start))
            except RuntimeError:
                pass   # a janela já foi fechada
        self._focus_mail_thread = threading.Thread(target=count, name='therion-focus-mail', daemon=True)
        self._focus_mail_thread.start()

    @Slot(object)
    def _focus_summary(self, row):
        if self._closing or self._quit_requested:
            return
        from therion.core import focus
        minutes_done, held, mail, start = row
        self._focus_held_unsaid = None
        try:
            today = focus.store().today(start.date()) if start.date() == datetime.now().date() else None   # conta no dia em que começou
        except OSError:
            today = minutes_done
        # Fala em tela cheia e no modo jogo, igual ao lembrete; a oferta de pausa é a dona do próximo "sim".
        # A oferta só começa a valer quando a fala sai: antes disso o "sim" ainda é de outro.
        self._speak_when_free(focus.ended_text(minutes_done, today, mail, held, focus.pause_minutes()), may_speak_quiet=True,
                              on_spoken=lambda: focus.offer(self._orchestrator, 'pause'))
        self._write_held(held)

    def _write_held(self, held):
        if held:
            self._append('Therion', 'Avisos que segurei durante o foco:\n' + '\n'.join('• ' + item for item in held))

    def _resume_focus(self):
        """Ao abrir: retoma o foco/pausa em andamento; o que acabou com o Therion fechado só é contado e dito."""
        if self._closing or self._quit_requested:
            return
        from therion.core import focus
        now = datetime.now()
        try:
            state = focus.store().state()
            if state.phase in ('focus', 'pause') and focus.remaining(state, now) > 0:
                self._apply_focus(focus._payload(state))
                return
            ended = focus.settle(now)
            if ended is None or ended.phase != 'focus':
                return
            end = focus.end_at(ended)
            today = focus.store().today(now.date()) if ended.start.date() == now.date() else None
        except OSError:
            return
        self._speak_when_free(focus.closed_text(end, today), may_speak_quiet=True)   # sem e-mails nem oferta
        self._write_held(ended.held)   # só escritos: são de antes de fechar

    def _present_worker(self,worker,action,payload):
        if worker is not self._command_worker or not self._worker_is_current(worker) or worker.cancelled.is_set() or self._quit_requested or getattr(self,'_workflow_clear_pending',False):return
        if payload and (payload.get('session')!=self._orchestrator.session_id or payload.get('account')!=self._orchestrator._mailbox.identity()):return
        if self._dashboard is None or not self._dashboard.active:self._select_interface('constellation',persist=False)
        if payload and payload.get('calendar_account')!=self._dashboard.source.identity()[1]:return
        if action=='open_briefing':
            if (self._conversation_mode and self._speech_output is not None
                    and payload.get('greeting') and getattr(self,'_briefing_intro',None) is None):
                narration=getattr(self,'_progress_narration',None)
                if narration is not None:narration.cancel()
                self._briefing_intro=dict(worker=worker,greeting=payload['greeting'],active=True,tail=None,stopped=False)
                # Disparar a síntese antes da montagem dos painéis; consultas seguem no worker.
                self._speech_output.speak(payload['greeting']+' Estou preparando seu panorama.')
            self._dashboard.open_briefing()
        elif action=='briefing_part':
            self._dashboard.briefing_part(payload)
            row=payload.get('result') if payload.get('kind')=='calendar' else None
            if self._reminders is not None and isinstance(row,dict) and row.get('state')=='ready':
                self._reminders.arm(row.get('items'),datetime.now())

    def _worker_is_current(self, worker):
        if not isinstance(worker, (_CommandWorker, _ConfirmationWorker)):
            return True
        if worker.session_id is not None and worker.session_id != self._orchestrator.session_id:
            return False
        return (not self._closing and (worker.conversation_generation is None or
                (self._conversation_mode and worker.conversation_generation == self._conversation_generation)))

    def _finish_policy_change(self, worker):
        if (not isinstance(worker, (_CommandWorker, _ConfirmationWorker))
                or self._closing or not isinstance(self._orchestrator, Orchestrator)
                or worker.knowledge_policy_epoch == self._orchestrator._knowledge_policy_epoch):
            return
        self._end_conversation()
        self._stop_speech()
        self._speech_text = ''
        self._pending_plan = None
        self._history.clear()
        self._append('Therion', 'A política de conhecimento mudou. Encerrei o contexto e as propostas anteriores. Faça o pedido novamente no escopo atual.')
        self._update_confirm_panel()
        self._update_orbe('idle')

    @Slot()
    def _finish_command(self, completed_worker=None) -> None:
        """Recebe o resultado após a thread terminar; widgets ficam na thread da UI."""
        if completed_worker is None and isinstance(self.sender(), _CommandWorker):
            completed_worker = self.sender()
        worker = self._command_worker
        if completed_worker is not None and completed_worker is not worker:
            return
        current = self._worker_is_current(worker) and not getattr(self, '_workflow_clear_pending', False) and not self._quit_requested
        try:
            if not current:
                self._finish_policy_change(worker)
                result=getattr(worker,'result',None)
                if (getattr(worker,'session_id',None)==self._orchestrator.session_id and not self._closing and not self._quit_requested
                        and not getattr(self,'_workflow_clear_pending',False) and getattr(result,'status',None)=='uncertain'):
                    self._append('Therion','Não confirmei o resultado da operação interrompida. Confira os recibos antes de repetir; parar não desfaz efeitos já ocorridos.')
                return
            if worker is None or worker.failed or worker.result is None:
                self._update_orbe("error")
                self._speech_text = "Ocorreu um erro inesperado ao processar o comando."
                self._append("Therion", self._speech_text)
            else:
                self._apply_command_result(worker.result)
        finally:
            self._command_worker = None
            if self._dashboard is not None:self._dashboard.briefing_open=False
            self._set_processing(False)
            if not current and not self._closing and not self._quit_requested:
                self._update_orbe('awaiting_confirmation' if self._pending_plan is not None else 'idle')
            if getattr(self, '_workflow_clear_pending', False):
                self._workflow_clear_pending = False
                self._clear_conversation()
            if current and getattr(self, '_conversation_mode', False):
                self._conversation_reply()
            if self._quit_requested:
                self._quit_application()
            else:
                self._drain_speech()   # depois da resposta falada: se ela começou a tocar, o lembrete espera

    def _poll_memory_previews(self):
        poll_workflow = getattr(self, '_poll_workflow_progress', None)
        if callable(poll_workflow):
            poll_workflow()
        if getattr(self, '_processing', False) or getattr(self, '_closing', False):
            return
        text = self._orchestrator.memory_notifications()
        if isinstance(text, str) and text:
            self._append('Therion', text)

    def _begin_progress_narration(self,worker):
        from therion.voice.progress_narration import ProgressNarration
        self._briefing_intro=None
        self._progress_narration=ProgressNarration()
        self._progress_worker=worker
        self._progress_identity=(self._orchestrator.session_id,self._conversation_generation)

    def _poll_progress_narration(self,events):
        speech=getattr(self,'_speech_output',None)
        narration=getattr(self,'_progress_narration',None)
        worker=getattr(self,'_progress_worker',None)
        if (narration is None or speech is None or not self._conversation_mode or not self._processing
                or worker not in (self._command_worker,self._confirmation_worker)
                or not self._worker_is_current(worker) or worker.cancelled.is_set()
                or self._quit_requested or self._closing
                or self._progress_identity!=(self._orchestrator.session_id,self._conversation_generation)):
            return
        for event in events:narration.observe(event)
        intro=getattr(self,'_briefing_intro',None)
        if (intro is not None and (intro['active'] or intro['stopped'] or intro['tail'] is not None)):
            return
        # Áudio final em pré-síntese tem prioridade sobre avisos de andamento.
        if isinstance(getattr(speech,'_held_prefix',None),str) or speech.state!='idle':return
        phrase=narration.next_phrase()
        if phrase:
            self._briefing_intro=dict(worker=worker,greeting='',active=True,tail=None,stopped=False)
            speech.speak(phrase)

    def _poll_workflow_progress(self):
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and dashboard.action_worker is not None:
            self._workflow_cancel_button.show()
            self._workflow_cancel_button.setEnabled(not dashboard.action_worker.token.cancelled)
            self._workflow_label.setText('Processando operação do painel…')
            return
        events = self._orchestrator.agent_events() if hasattr(self._orchestrator, 'agent_events') else []
        runtime = getattr(self._orchestrator, '_agent_runtime', None)
        from therion.agent.runtime import AgentRuntime
        if isinstance(events,list):
            events=[event for event in events if event.session_id==self._orchestrator.session_id and
                (not isinstance(runtime,AgentRuntime) or event.turn_id==runtime.turn_id)]
        if isinstance(events,list) and hasattr(self,'_agent_details_view'):
            from therion.agent.presentation import event_detail
            for event in events:
                detail=event_detail(event)
                if detail:self._agent_details_view.appendPlainText(detail)
        if isinstance(events,list) and getattr(self,'_conversation_mode',False):
            speech=getattr(self,'_speech_output',None)
            for event in events:
                if (event.type=='response_prefix' and speech is not None
                        and isinstance(runtime,AgentRuntime) and runtime.accepting_output
                        and getattr(self,'_processing',False) and getattr(self,'_briefing_intro',None) is None):
                    speech.prepare_prefix(event.payload.get('text'))
                elif event.type in {'thinking','decision_rejected','provider_failed','tool_started'} and speech is not None:
                    if isinstance(getattr(speech,'_held_prefix',None),str):speech.stop()
        self._poll_progress_narration(events if isinstance(events,list) else [])
        if isinstance(runtime, AgentRuntime) and runtime.active and getattr(self, '_processing', False):
            if events and events[-1].session_id == self._orchestrator.session_id:
                latest=events[-1]
                labels={'thinking':'Preparando resposta…','provider_activity':'Processando…','tool_started':'Verificando etapa…','tool_running':'Executando etapa autorizada…','tool_finished':'Etapa concluída','awaiting_confirmation':'Aguardando confirmação em Capacidades…'}
                self._workflow_label.setText(labels.get(latest.type,'Processando…'))
            self._workflow_cancel_button.setVisible(True)
            self._workflow_cancel_button.setEnabled(True)
            return
        if events and getattr(self, '_processing', False):
            latest = events[-1]
            if latest.session_id == self._orchestrator.session_id:
                labels = {'thinking':'Preparando resposta…','provider_activity':'Processando…',
                    'tool_started':'Verificando etapa…','tool_running':'Executando etapa autorizada…','tool_finished':'Etapa concluída'}
                if latest.type in labels:
                    self._workflow_label.setText(labels[latest.type])
                self._workflow_cancel_button.setVisible(True)
                self._workflow_cancel_button.setEnabled(True)
                return
        from therion.core.workflow_runtime import WorkflowSnapshot
        snapshot = self._orchestrator.workflow_progress() if hasattr(self._orchestrator, 'workflow_progress') else None
        active = isinstance(snapshot, WorkflowSnapshot) and snapshot.state in {'running', 'awaiting_confirmation'}
        if hasattr(self, '_workflow_cancel_button'):
            self._workflow_cancel_button.setVisible(active)
            self._workflow_cancel_button.setEnabled(active and not getattr(self, '_workflow_clear_pending', False))
        if hasattr(self, '_workflow_label'):
            running = next((row.index+1 for row in snapshot.receipts if row.state == 'running'), None) if active else None
            self._workflow_label.setText(f'Etapa {running}/{len(snapshot.receipts)}' if running else
                'Evento aguardando confirmação' if active else '')
        if active and hasattr(self, '_clear_button'):
            self._clear_button.setEnabled(not getattr(self, '_workflow_clear_pending', False))

    def _on_workflow_cancel(self):
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and dashboard.action_worker is not None:
            dashboard.action_worker.token.cancel()
            self._end_conversation()
            self._stop_speech()
            self._poll_workflow_progress()
            return
        self._orchestrator.cancel_workflow()
        self._end_conversation()
        self._stop_speech()
        if self._processing:
            self._workflow_label.setText('Cancelando etapas restantes…')
            self._workflow_cancel_button.setEnabled(False)
            return
        self._append('Você', 'Cancele o pedido')
        self._set_processing(True)
        self._start_command_worker('cancele o pedido')

    def _apply_command_result(self, result: OrchestrationResult) -> None:
        """Apresenta o resultado de um comando na interface."""
        if result.ui_action=='open_briefing':
            payload=result.ui_payload or {}
            from therion.integrations.calendar import account_key
            if payload.get('session')!=self._orchestrator.session_id or payload.get('account')!=self._orchestrator._mailbox.identity() or payload.get('calendar_account')!=account_key(self._orchestrator):
                result=OrchestrationResult(status='cancelled',message='A conta ou a sessão mudou. Solicite um novo panorama.')
        if result.ui_action=='game_mode':
            self._set_game_mode((result.ui_payload or {}).get('on') is True)
        if result.ui_action=='wake_off':
            if getattr(self, '_wake', None) is None:
                result=replace(result, message='A escuta pelo nome não está ligada agora.', speech_message=None)
            else:
                self._stop_wake()   # fecha o microfone do detector até reiniciar o Therion
                self._wake_end_after_reply = self._conversation_mode
        if result.ui_action=='reminders':   # o depósito mudou: rearma o disparo na hora
            self._arm_reminder_timer()
        if result.ui_action=='open_mail':
            if self._dashboard is None or not self._dashboard.active:self._select_interface('constellation',persist=False)
            if self._dashboard is not None and self._dashboard.active:self._dashboard.open_mail((result.ui_payload or {}).get('id') or '')
        if result.ui_action=='open_briefing':
            if self._dashboard is None or not self._dashboard.active:self._select_interface('constellation',persist=False)
            if self._dashboard is not None:
                self._dashboard.open_briefing(result.ui_payload)
                try:self._orchestrator.acknowledge_briefing(result.ui_payload['candidate'])
                except (OSError,ValueError):
                    self._dashboard.mailbox.notice.setText('Panorama apresentado, mas o marco não foi salvo. A próxima contagem poderá repetir mensagens.')
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and result.status == 'success' and result.ui_action!='open_briefing':
            dashboard.refresh('calendar')
        self._last_agent_response_status=result.status
        if dashboard is not None:dashboard._skip_response_refresh=result.ui_action=='open_briefing'
        self._append("Therion", result.message)
        if result.ui_action=='focus':   # depois da resposta: o resumo de um foco encerrado vem em seguida
            self._apply_focus(result.ui_payload or {})
        self._speech_text = result.speech_message or result.message
        MainWindow._log_result(self, result)
        self._conversation_awaiting_response = (result.status == 'awaiting_confirmation' or
            (result.confirmation_id is not None and result.status in {'success', 'clarification'}))
        if result.status in {'ai_unavailable', 'ai_timeout', 'ai_invalid_response'}:
            self._invalidate_ai_readiness()
            self._end_conversation()

        if result.registered_plan_id is not None:
            self._orchestrator.ack_registered_plan_displayed(
                result.registered_plan_id
            )

        if result.plan_candidate_id is not None:
            ack = self._orchestrator.ack_plan_displayed(result.plan_candidate_id)
            if ack.status == "displayed_not_registered":
                self._append(
                    "Therion",
                    "Este plano foi exibido, mas não pôde ser registrado nesta sessão. Por isso, ele não poderá ser recuperado depois por referências como “mesmo plano”, “plano anterior” ou “primeiro plano”.",
                )

        if result.confirmation_id is not None and result.status in {'success', 'clarification'}:
            # Prévia de memória mantém o painel da proposta original.
            self._update_orbe('awaiting_confirmation')
        elif result.status == "awaiting_confirmation" and result.plan is not None:
            if self._conversation_mode and self._voice_pipeline is not None:
                self._voice_pipeline.cancel()
                self._conversation_capture_generation = None
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
        if self._processing or self._pending_plan is None:
            return
        if self._conversation_mode:
            if self._voice_pipeline is not None:
                self._voice_pipeline.cancel()
            self._conversation_capture_generation = None
            self._speech_output.stop()
        self._input.clear()
        self._append("Você", response)

        confirmed = self._confirmation_handler.evaluate_response(response)

        if confirmed is None:
            self._speech_text = "Resposta não reconhecida. Responda 'sim' ou 'não'."
            self._append("Therion", self._speech_text)
            if self._conversation_mode:
                self._conversation_reply()
            return

        if confirmed:
            self._update_orbe("executing")

        self._set_processing(True)
        try:
            self._start_confirmation_worker(self._pending_plan, confirmed)
        except Exception:
            self._confirmation_worker = None
            self._show_confirmation_error()
            self._set_processing(False)

    def _start_confirmation_worker(self, plan: Plan, confirmed: bool) -> None:
        worker = _ConfirmationWorker(self._orchestrator, plan, confirmed)
        worker.conversation_generation = self._conversation_generation if self._conversation_mode else None
        self._confirmation_worker = worker
        self._begin_progress_narration(worker)
        worker.finished.connect(self._finish_confirmation)
        worker.start()

    @Slot()
    def _finish_confirmation(self, completed_worker=None) -> None:
        """Apresenta a confirmação após a thread terminar, sempre na thread da UI."""
        if completed_worker is None and isinstance(self.sender(), _ConfirmationWorker):
            completed_worker = self.sender()
        worker = self._confirmation_worker
        if completed_worker is not None and completed_worker is not worker:
            return
        current = self._worker_is_current(worker)
        try:
            if not current:
                self._finish_policy_change(worker)
                return
            if worker is None or worker.failed or worker.result is None:
                self._show_confirmation_error()
            else:
                self._apply_confirmation_result(worker.result)
        finally:
            self._confirmation_worker = None
            self._set_processing(False)
            if not current and not self._closing and not self._quit_requested:
                self._update_orbe('awaiting_confirmation' if self._pending_plan is not None else 'idle')
            if current and self._conversation_mode:
                self._conversation_reply()
            if self._quit_requested:
                self._quit_application()

    def _show_confirmation_error(self) -> None:
        self._end_conversation()
        self._pending_plan = None
        self._update_orbe("error")
        self._append("Therion", "Ocorreu um erro inesperado ao processar a confirmação.")
        self._update_clear_button_state()
        self._update_confirm_panel()

    def _apply_confirmation_result(self, result: OrchestrationResult) -> None:
        """Apresenta o resultado de uma confirmação na interface."""
        self._pending_plan = None
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and result.status == 'success':
            dashboard.refresh('calendar')
        self._conversation_awaiting_response = False
        self._append("Therion", result.message)
        self._speech_text = result.speech_message or result.message
        MainWindow._log_result(self, result)
        orbe_state = _ORBE_STATUS_MAP.get(result.status, "idle")
        self._update_orbe(orbe_state)
        self._update_clear_button_state()
        self._update_confirm_panel()

    def _log_result(self, result) -> None:
        """Completa a nota: o que foi falado, como o pedido foi interpretado e quanto levou."""
        log = getattr(self, '_conversation_log', None)
        if not isinstance(log, ConversationLog):
            return
        intent = getattr(result, 'intent', None)
        route = getattr(intent, 'action', intent) if intent else None
        command = getattr(getattr(self, '_command_worker', None), '_command', None)
        if route is None and isinstance(command, str):
            # Modo jogo, foco, lembretes e afins não trazem intenção; antes todos apareciam como "IA/conversa".
            from therion.core.routes import fixed_route
            try:
                route = fixed_route(command)
            except Exception:
                route = None
        started = getattr(self, '_command_started_at', None)
        seconds = time.monotonic() - started if started is not None else None
        self._command_started_at = None
        log.result(spoken=getattr(self, '_speech_text', None), status=result.status, route=route, seconds=seconds)

    def _append(self, sender: str, text: str) -> None:
        """Adiciona mensagem ao histórico com formatação visual diferenciada.

        Segurança: todo conteúdo de texto é escapado via html.escape()
        antes de envolver em tags HTML estruturais.
        """
        safe_text = html.escape(text).replace("\n", "<br>")
        log = getattr(self, '_conversation_log', None)
        if isinstance(log, ConversationLog):
            if sender == 'Você':
                log.user(text, channel=getattr(self, '_next_user_channel', 'texto'))
                self._next_user_channel = 'texto'
            else:
                log.therion(text)
        if sender != 'Você':
            self._last_ui_response = text

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

        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and dashboard.active:
            from .design_system import history_html
            block=history_html(block)
        scrollbar=self._history.verticalScrollBar()
        old_scroll=scrollbar.value()
        follow=sender=='Você' or scrollbar.maximum()-old_scroll<=24
        self._history.append(block)
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None:
            dashboard.response(sender, text)
        if dashboard is None or not dashboard.active or follow:
            scrollbar.setValue(scrollbar.maximum())
        else:scrollbar.setValue(old_scroll)

    def _cancel_voice_if_active(self) -> None:
        """Cancela o pipeline de voz se estiver ativo (recording ou transcribing).

        Helper resiliente: nunca propaga exceção ao chamador.
        """
        try:
            if self._voice_pipeline is not None:
                self._voice_pipeline.cancel()
        except Exception:  # noqa: BLE001
            pass

    def _clear_conversation(self) -> None:
        """Limpa o histórico visual da conversa e encerra o estado interno da sessão."""
        if self._processing:
            snapshot = self._orchestrator.workflow_progress() if hasattr(self._orchestrator, 'workflow_progress') else None
            if getattr(snapshot, 'state', None) == 'running':
                self._workflow_clear_pending = True
                self._orchestrator.cancel_workflow()
                if self._command_worker is not None:
                    self._command_worker.cancelled.set()
                self._invalidate_ai_readiness()
                self._end_conversation()
                self._stop_speech()
                self._history.clear()
                self._poll_workflow_progress()
            return
        self._invalidate_ai_readiness()
        self._end_conversation()
        self._cancel_voice_if_active()
        self._stop_speech()
        self._speech_text = ''
        if hasattr(self, '_listen_button'):
            self._listen_button.setEnabled(False)
        self._history.clear()
        self._last_ui_response = ''
        self._orchestrator.clear_session()
        if isinstance(getattr(self, '_conversation_log', None), ConversationLog):
            self._conversation_log.rotate()
        self._pending_plan = None
        self._conversation_awaiting_response = False
        self._conversation_confirmation_plan = None
        self._conversation_confirmation_token = None
        self._update_confirm_panel()
        self._update_orbe('idle')
        if hasattr(self, '_clear_button'):
            self._update_clear_button_state()

    def _set_processing(self, processing: bool) -> None:
        """Impede ações concorrentes sem bloquear a edição do campo de texto."""
        if processing:
            self._cancel_voice_if_active()
        self._processing = processing
        if not processing:
            narration=getattr(self,'_progress_narration',None)
            if narration is not None:narration.cancel()
        # Durante inferência, consumir deltas sem esperar o tick de memória.
        if hasattr(self,'_memory_timer'):self._memory_timer.setInterval(100 if processing else 1000)
        cycle = getattr(getattr(self, '_voice_pipeline', None), 'cycle', None)
        if isinstance(cycle, VoiceCycle):
            cycle.runtime(processing)
        if processing:
            self._last_agent_response_status=None
            self._stop_speech()
        if hasattr(self, '_listen_button'):
            self._listen_button.setEnabled(bool(getattr(self, '_speech_output', None) and getattr(self, '_speech_text', '') and not processing and self._pending_plan is None))
        for name in ("_send_button", "_btn_confirm", "_btn_cancel", "_voice_button"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(not processing)
        self._update_clear_button_state()

    def _on_voice_clicked(self) -> None:
        """Primeiro clique dispara carregamento on-demand do modelo.

        Após ``STATE_ERROR``, o caminho é relido da configuração atual
        antes da nova tentativa; se a atualização for rejeitada, o erro
        visível permanece e nenhum carregamento é iniciado.
        """
        if self._processing:
            return

        state = self._voice_service.state
        if state in (VoiceModelService.STATE_UNLOADED, VoiceModelService.STATE_ERROR):
            if state == VoiceModelService.STATE_ERROR:
                fresh_path = load_config().get("voice", {}).get("model_path")
                if not self._voice_service.set_model_path(fresh_path):
                    return
            if hasattr(self, "_voice_button"):
                self._voice_button.setText("Carregando modelo…")
                self._voice_button.setEnabled(False)
            self._voice_service.load()
            return

        if state == VoiceModelService.STATE_READY:
            # Modelo pronto: pressed/released tratam a gravação
            return

    @Slot(object)
    def _on_voice_model_loaded(self, model: object) -> None:
        """Modelo carregado: cria o pipeline e atualiza o botão."""
        if self._closing or self._quit_requested:return
        if self._voice_pipeline is None:
            capture = AudioCaptureService()
            transcription = VoiceTranscriptionService(model, vocabulary_provider=self._voice_vocabulary)
            self._voice_pipeline = VoicePipeline(capture, transcription)
            self._voice_pipeline.transcribed.connect(self._on_voice_transcribed)
            self._voice_pipeline.transcription_failed.connect(self._on_voice_transcription_failed)
            self._voice_pipeline.state_changed.connect(self._on_voice_pipeline_state_changed)
        if hasattr(self, "_voice_button"):
            self._voice_button.setText("Segure para falar")
            self._voice_button.setEnabled(not self._processing)
        self._preparation.finish('transcription')
        self._render_preparation()
        self._try_conversation_listen()

    @Slot(str)
    def _on_voice_model_failed(self, error: str) -> None:
        """Falha no carregamento: visível e permite nova tentativa."""
        self._preparation.finish('transcription', 'failed')
        self._end_conversation()
        if hasattr(self, "_voice_button"):
            self._voice_button.setText("Tentar carregar voz")
            self._voice_button.setEnabled(not self._processing)
        self._append("Therion", f"Não foi possível carregar o modelo de voz: {error}")

    def _voice_vocabulary(self):
        catalog = self._orchestrator.application_catalog
        if catalog is None:
            return []
        return [name for app in catalog.entries() for name in (app.name, *app.aliases)]

    def _on_voice_pressed(self) -> None:
        """Botão pressionado: inicia captura se o pipeline estiver pronto.

        Gates: não inicia se `_processing` ou `_pending_plan` ativo.
        """
        self._end_conversation()
        self._stop_speech()
        if self._voice_pipeline is None:
            return
        if self._processing or self._pending_plan is not None:
            return
        self._voice_pipeline.start()

    def _on_voice_released(self) -> None:
        """Botão solto: para a captura e dispara transcrição."""
        if self._voice_pipeline is None:
            return
        self._voice_pipeline.stop()

    @Slot(int, str)
    def _on_voice_transcribed(self, generation: int, text: str) -> None:
        """Resultado da transcrição inserido no campo de entrada (sem autoenvio).

        Fora da conversa automática, voz não confirma ações. Dentro dela,
        aceita resposta somente da captura atual e para o plano apresentado.
        """
        if self._processing or (self._pending_plan is not None and not self._conversation_mode):
            return
        if self._voice_pipeline is not None and not self._voice_pipeline.is_current_generation(generation):
            return
        if getattr(self, '_conversation_mode', False):
            if generation != self._conversation_capture_generation:
                return
            self._conversation_capture_generation = None
            if self._conversation_confirmation_token != self._orchestrator.confirmation_id:
                self._try_conversation_listen()
                return
            if not text.strip():
                self._wake_outcome('sem fala')
                self._try_conversation_listen()
                return
            if text.strip().casefold().rstrip('.!?') in {'encerrar conversa', 'parar conversa', 'sair do modo voz'}:
                self._wake_outcome('virou pedido')
                self._end_conversation()
                return
            if self._pending_plan is not None:
                if self._pending_plan is not getattr(self, '_conversation_confirmation_plan', None):
                    self._try_conversation_listen()
                    return
                self._wake_outcome('virou pedido')
                self._next_user_channel = 'voz'
                self._handle_confirmation(text.strip().rstrip('.!?').strip())
                return
            if time.monotonic() - self._conversation_capture_started_at <= 15:
                text = strip_spoken_echo_prefix(text, self._last_conversation_spoken)
            if getattr(self, '_conversation_awaiting_response', False):
                normalized_answer = text.strip().rstrip('.!?').strip()
                if self._confirmation_handler.evaluate_response(normalized_answer) is not None:
                    text = normalized_answer
            confidence = getattr(self._voice_pipeline, 'last_confidence', None)
            if self._background_speech(text):
                self._wake_outcome('sem fala')
                self._try_conversation_listen()
                return
            self._wake_outcome('virou pedido')
            self._next_user_channel = 'voz' if not isinstance(confidence, float) else f'voz · confiança {confidence:.2f}'
            self._append('Você', text)
            self._speech_text = ''
            self._conversation_label.setText('Pensando…')
            self._update_orbe('thinking')
            self._set_processing(True)
            try:
                self._start_command_worker(text)
            except Exception:
                self._end_conversation()
                self._set_processing(False)
                self._append('Therion', 'Não foi possível processar a fala.')
            return
        self._insert_transcribed_text(text)

    def _background_speech(self, text):
        """Conversa de fundo: confiança baixa, sem o nome, sem regra fixa e sem pergunta aberta. Ignora em silêncio.

        Nas conversas de 16-20/11 a fala de fundo ficou entre -0,48 e -0,72; comandos reais chegaram a -0,57
        ("Libere espaço") e respostas a -0,51 ("Cinco horas"), por isso esses dois casos nunca são ignorados.
        """
        import re
        pipeline = getattr(self, '_voice_pipeline', None)
        confidence = getattr(pipeline, 'last_confidence', None)
        # 22/11, escolha A: na conversa aberta, fala que começou mais de 8 s depois da última resposta
        # (ou da abertura) e sem o nome é de fundo, mesmo clara. Fora da conversa (tecla) vale só a confiança.
        started, heard = getattr(pipeline, 'speech_started_after', None), getattr(self, '_conversation_heard_at', None)
        late = (getattr(self, '_conversation_mode', False) and isinstance(started, (int, float)) and isinstance(heard, float)
                and getattr(self, '_conversation_capture_started_at', 0.0) + started - heard > CONVERSATION_WINDOW_SECONDS)
        if not late and (not isinstance(confidence, float) or confidence >= -0.5):
            return False
        if getattr(self, '_wake_score', None) is not None:   # chamou pelo nome (o áudio inicial corta o nome do texto)
            return False
        pendings = getattr(self._orchestrator, '_pendings', None)
        now = time.monotonic()   # cada oferta é um prazo ou uma tupla que começa pelo prazo; a vencida não conta
        if callable(pendings) and any(value is not None and (value if isinstance(value, float) else value[0]) > now
                                      for value in pendings()):   # resposta a uma oferta viva
            return False
        if re.search(r'\b(?:therion|terion|eterion)\b', text, re.I):
            return False
        orchestrator = self._orchestrator
        if (getattr(self, '_conversation_awaiting_response', False) or getattr(orchestrator, 'confirmation_id', None)
                or getattr(getattr(orchestrator, '_conversation_frame', None), 'question', None)
                or '?' in (getattr(self, '_last_conversation_spoken', '') or '')):
            return False
        if late:
            return True   # fora da janela, nem regra fixa passa sem o nome
        from therion.core.routes import fixed_route
        return fixed_route(text) is None

    @Slot(int, str)
    def _on_voice_transcription_failed(self, generation: int, error: str) -> None:
        """Falha na transcrição: exibe mensagem discreta no histórico sem autoenvio."""
        if self._voice_pipeline is not None and not self._voice_pipeline.is_current_generation(generation):
            return
        if getattr(self, '_conversation_mode', False) and generation != self._conversation_capture_generation:
            return
        if error == 'voice_unclear_audio':
            self._append('Therion', 'Não entendi o áudio com segurança. Repita a frase ou digite o pedido.')
            if getattr(self, '_conversation_mode', False):
                self._conversation_capture_generation = None
                self._try_conversation_listen()
            return
        self._end_conversation()
        if error == 'voice_memory_exhausted':
            self._append("Therion", 'A transcrição falhou ao alocar memória. '
                         'Encerrei a conversa por voz; o histórico e a confirmação pendente foram preservados. '
                         'Você pode continuar digitando. Libere memória e confira o espaço do disco antes de tentar novamente.')
        else:
            self._append("Therion", f"Transcrição de voz falhou: {error}")

    @Slot(str)
    def _on_voice_pipeline_state_changed(self, state: str) -> None:
        cycle = getattr(getattr(self, '_voice_pipeline', None), 'cycle', None)
        if isinstance(cycle, VoiceCycle) and self._voice_pipeline.state != state:
            return
        """Atualiza texto do botão de acordo com o estado do pipeline."""
        wake = getattr(self, '_wake', None)
        if wake is not None:   # gravando, o nome não importa: o detector descansa
            (wake.pause if state == VoicePipeline.STATE_RECORDING else wake.resume)()
        if not hasattr(self, "_voice_button"):
            return
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None:
            dashboard.presentation.capture = state
            self._sync_mini_orb()
        if state == VoicePipeline.STATE_RECORDING:
            self._voice_button.setText("Gravando…")
            if getattr(self, '_conversation_mode', False):
                self._update_orbe('listening')
        elif state == VoicePipeline.STATE_TRANSCRIBING:
            self._voice_button.setText("Transcrevendo…")
        elif state == VoicePipeline.STATE_IDLE:
            if self._voice_service.state == VoiceModelService.STATE_READY:
                self._voice_button.setText("Segure para falar")

    def _insert_transcribed_text(self, text: str) -> None:
        """Insere texto transcrito no campo self._input preservando rascunho.

        Regras:
        - texto vazio: não altera nada;
        - campo vazio: insere diretamente;
        - campo com conteúdo: adiciona um espaço se o último caractere não for espaço.
        """
        if not text:
            return
        current = self._input.toPlainText()
        if not current:
            new_text = text
        elif current[-1].isspace():
            new_text = current + text
        else:
            new_text = current + " " + text
        self._input.setPlainText(new_text)
        cursor = self._input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._input.setFocus()

    @Slot(str)
    def _on_voice_model_state_changed(self, state: str) -> None:
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and not self._processing:
            if state == VoiceModelService.STATE_LOADING:
                dashboard.interaction('preparing')
            elif state == VoiceModelService.STATE_READY and dashboard.presentation.interaction == 'preparing':
                dashboard.interaction('idle')
        if state == VoiceModelService.STATE_LOADING and hasattr(self, "_voice_button"):
            self._voice_button.setText("Carregando modelo…")
            self._voice_button.setEnabled(False)

    def _update_clear_button_state(self) -> None:
        """Limpar descarta inclusive propostas, mas aguarda a operação corrente."""
        self._clear_button.setEnabled(not self._processing)

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
        self._orbe_state = state
        if hasattr(self, "_orbe"):
            self._orbe.setStyleSheet(
                f"background-color: {color}; border-radius: 28px;"
            )
        if hasattr(self, "_orbe_label"):
            self._orbe_label.setText(text)
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None:
            dashboard.interaction(state)
        self._sync_mini_orb()
        self._drain_speech_later()

    def _sync_mini_orb(self) -> None:
        """A mini orbe mostra o mesmo estado da orbe grande (Presentation: fala e captura incluídas)."""
        mini = getattr(self, '_mini_orb', None)
        if mini is None:
            return
        dashboard = getattr(self, '_dashboard', None)
        state = dashboard.presentation.state if dashboard is not None else self._orbe_state
        watch = getattr(self, '_pc_watch', None)
        mini.set_state(state, watch is not None and watch.tight())

    def _shutdown_voice(self):
        for service in (getattr(self,'_voice_pipeline',None),getattr(self,'_voice_service',None),getattr(self,'_speech_output',None)):
            shutdown=getattr(service,'shutdown',None)
            if callable(shutdown):shutdown()

    def _voice_jobs_pending(self):
        return any(not getattr(service,'is_quiescent',True)
            for service in (getattr(self,'_voice_pipeline',None),getattr(self,'_voice_service',None),getattr(self,'_speech_output',None)) if service is not None)

    def _quit_application(self) -> None:
        """Revoga trabalho novo e aguarda os donos de recursos antes de sair."""
        if self._closing:return
        was_requested=self._quit_requested
        self._quit_requested=True
        self._stop_wake()
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None:
            dashboard.cancel()
        if self._processing:
            for method in ('cancel_agent','cancel_workflow'):
                cancel=getattr(self._orchestrator,method,None)
                if callable(cancel):cancel()
            for worker in (self._command_worker,self._confirmation_worker):
                token=getattr(worker,'cancelled',None)
                if token is not None:token.set()
        self._end_conversation()
        self._stop_speech()
        self._shutdown_voice()
        if dashboard is not None and dashboard.busy:
            QTimer.singleShot(100, self._quit_application)
            return
        if self._closing:return
        self._v4_timer.stop()
        panel=getattr(self,'_agent_panel',None)
        if panel is not None and panel.busy:
            panel.cancel_operations()
            QTimer.singleShot(250,self._quit_application)
            return
        if self._v4_worker is not None:
            QTimer.singleShot(200, self._quit_application)
            return
        if self._voice_jobs_pending():
            if not was_requested:self._append('Therion','Encerrando a voz; aguardando o trabalho de áudio terminar com segurança.')
            QTimer.singleShot(200,self._quit_application)
            return
        if self._processing:
            if not was_requested:
                self._append("Therion", "O aplicativo será encerrado após concluir a tarefa atual.")
            return
        self._closing = True
        if self._focus_mail_token is not None:
            self._focus_mail_token.cancel()   # a contagem de e-mails do fim do foco não segura o encerramento
        if hasattr(self._orchestrator, 'close'):
            self._orchestrator.close()
        if self._tray_icon:
            self._tray_icon.hide()
        self._shut_mini_orb()
        self._app.quit()

    def _start_wake(self):
        """Palavra de ativação (ui.wake_word): só com o modelo baixado; sem ele o Therion segue como antes."""
        path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Therion', 'wake', 'therion.onnx')
        if (self._config.get('ui') or {}).get('wake_word') is not True or not os.path.isfile(path):
            return
        self._wake_heard.connect(self._on_wake)
        self._wake_problem.connect(self._on_wake_problem)
        threshold = (self._config.get('wake') or {}).get('threshold', 0.5)
        listener = WakeListener(path, self._emit_wake, threshold=threshold, on_problem=self._emit_wake_problem)
        if not listener.start():
            return
        self._wake = listener
        self._app.aboutToQuit.connect(self._stop_wake)
        from PySide6.QtMultimedia import QSoundEffect
        from PySide6.QtCore import QUrl
        self._wake_sound = QSoundEffect(self)   # carregado já: o som sai na hora do nome
        self._wake_sound.setSource(QUrl.fromLocalFile(str(_WAKE_SOUND_PATH)))
        self._wake_sound.setVolume(0.35)

    def _emit_wake(self, audio, score):
        # Roda na entrega do disparo (thread do detector): a marca lida aqui é a deste disparo.
        mark = getattr(self._wake, 'wake_mark', None)
        try:
            self._wake_heard.emit(audio, float(score), mark)
        except RuntimeError:   # janela já destruída
            pass

    def _emit_wake_problem(self, kind):
        try:
            self._wake_problem.emit(kind)
        except RuntimeError:
            pass

    def _stop_wake(self):
        # Antes de sair do Qt: a thread do detector não pode emitir para uma janela destruída.
        wake, self._wake = getattr(self, '_wake', None), None
        if wake is not None:
            wake.stop()

    @Slot(str)
    def _on_wake_problem(self, kind):
        self._append('Therion', 'Não consegui abrir o microfone para ouvir meu nome; tento de novo sozinho.'
                     if kind == 'microfone' else 'O detector do meu nome falhou; tento de novo sozinho.')

    def _play_wake_sound(self):
        if self._wake_sound is not None:
            self._wake_sound.play()

    def _wake_log(self, score, outcome):
        log = getattr(self, '_conversation_log', None)
        if isinstance(log, ConversationLog):
            log.event(f'acordou pelo nome · pontuação {score:.2f} · {outcome}')

    def _wake_outcome(self, outcome):
        score, self._wake_score = getattr(self, '_wake_score', None), None
        if score is not None:
            self._wake_log(score, outcome)

    def _wake_ignored(self):
        if self._closing or self._quit_requested:
            return 'encerrando'
        if self._wake is None:   # disparo que já estava na fila quando o detector desligou
            return 'escuta pelo nome desligada'
        if self._processing:
            return 'pedido em andamento'
        pipeline = self._voice_pipeline
        if self._wake_turn is not None or (pipeline is not None and pipeline.state != VoicePipeline.STATE_IDLE):
            return 'turno de voz aberto'
        speech = self._speech_output
        spoken = getattr(speech, 'spoken_text', None)
        spoken = spoken if isinstance(spoken, str) else self._speech_text
        if (speech is not None and speech.state not in {'idle', 'warming'}
                and 'therion' in (spoken or '').casefold()):
            return 'a fala tem o nome'   # o detector ouviu a própria voz do Therion
        return None

    def _wake_preroll(self, audio):
        """O áudio depois do nome, lido do detector só quando o microfone da captura já abriu."""
        mark, since = self._wake_mark, getattr(self._wake, 'since', None)
        if mark is None or not callable(since):
            return audio

        def late():
            fresh = since(mark)
            return fresh if len(fresh) >= len(audio) else audio   # saiu do buffer: fica a foto do disparo
        return late

    @Slot(object, float, object)
    def _on_wake(self, audio, score, mark=None):
        """O detector ouviu o nome: abre um turno de voz que começa pelo áudio dito logo depois dele."""
        reason = self._wake_ignored()
        if reason is None and not self._conversation_mode and (self._pending_plan is not None or self._speech_output is None):
            reason = 'conversa por voz indisponível'
        if reason is not None:
            self._wake_log(score, 'ignorado: ' + reason)
            return
        self._wake_turn = audio   # antes de parar a fala: o reaquecimento da voz não pode travar a captura
        self._wake_mark = mark
        speech = self._speech_output
        speaking = speech is not None and speech.state not in {'idle', 'warming'}
        if speaking:
            self._stop_speech()
        # Fala parada pelo nome, ou voz reaquecendo de uma parada anterior: nada disso é eco, grava já.
        if speaking or (speech is not None and speech.state == 'warming'):
            cycle = getattr(self._voice_pipeline, 'cycle', None)
            if isinstance(cycle, VoiceCycle):
                cycle.barge_in()
        if not self._conversation_mode:
            # Grava antes de abrir a conversa: o aquecimento da voz trava novas capturas, e a fala logo
            # depois do nome ("Therion, abre o Discord") se perderia esperando por ele.
            pipeline = self._voice_pipeline
            early = pipeline is not None and pipeline.start(
                automatic=True, preroll=self._wake_preroll(audio), no_speech_seconds=5.0)
            self._toggle_conversation()
            if not self._conversation_mode:
                if early:
                    pipeline.cancel()
                self._wake_turn = None
                self._wake_log(score, 'ignorado: conversa por voz indisponível')
                return
            self._wake_opened = True
            if early:
                self._wake_turn = None
                self._own_conversation_capture(pipeline)
        self._wake_score = score   # o desfecho (virou pedido, sem fala) chega com o fim do turno
        self._update_orbe('listening')
        self._play_wake_sound()
        self._try_conversation_listen()

    def _shut_mini_orb(self):
        if self._mini_orb is not None:
            self._mini_orb.shut()   # idempotente: fecha o painel, a leitura e o renderizador

    def hideEvent(self, event) -> None:
        if not self.isMinimized() and not self._changing_window_mode:
            self._end_conversation()
            if hasattr(self, '_voice_pipeline'):
                self._cancel_voice_if_active()
            self._stop_speech()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        """Oculta na bandeja ou adia o fechamento até a operação terminar."""
        self._end_conversation()
        self._stop_speech()
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None and dashboard.busy:
            event.ignore()
            self._quit_application()
            return
        if dashboard is not None:
            dashboard.activate(False)
        if self._closing:
            if self._tray_icon:
                self._tray_icon.hide()
            self._stop_wake()
            self._shut_mini_orb()
            super().closeEvent(event)
            return

        if (self._processing or self._v4_worker is not None or self._voice_jobs_pending()) and not (self._tray_icon and self._tray_icon.isVisible()):
            event.ignore()
            self._quit_application()
            return

        if self._tray_icon and self._tray_icon.isVisible():
            event.ignore()
            self._cancel_voice_if_active()
            self.hide()
        else:
            self._shutdown_voice()
            self._cancel_voice_if_active()
            if self._tray_icon:
                self._tray_icon.hide()
            if hasattr(self._orchestrator, 'close'):
                self._orchestrator.close()
            self._closing = True
            self._stop_wake()
            self._shut_mini_orb()
            super().closeEvent(event)


    def _listen_response(self) -> None:
        if self._speech_output and self._speech_text and not self._processing and self._pending_plan is None:
            if self._voice_pipeline is not None and self._voice_pipeline.state != 'idle':
                return
            self._speech_output.speak(self._speech_text)

    def _stop_speech(self) -> None:
        narration=getattr(self,'_progress_narration',None)
        if narration is not None:narration.cancel()
        intro=getattr(self,'_briefing_intro',None)
        if intro is not None:intro.update(stopped=True,active=False,tail=None)
        if getattr(self, '_speech_output', None) is not None:
            self._speech_output.stop()
        if getattr(self, '_conversation_mode', False) and not self._processing:
            if not self._speech_output.is_ready:
                self._speech_output.warmup()
            QTimer.singleShot(200, self._try_conversation_listen)

    def _on_speech_state(self, state: str) -> None:
        dashboard = getattr(self, '_dashboard', None)
        if dashboard is not None:
            dashboard.presentation.speech = state
            self._sync_mini_orb()
        cycle = getattr(getattr(self, '_voice_pipeline', None), 'cycle', None)
        if isinstance(cycle, VoiceCycle):
            # Com o turno do nome pendente, reaquecer a voz (parada pelo nome) não trava a captura.
            cycle.playback(state in {'synthesizing','playing'}
                           or (state == 'warming' and getattr(self, '_wake_turn', None) is None))
        self._stop_speech_button.setEnabled(state != 'idle')
        self._listen_button.setText('Gerando voz…' if state in {'synthesizing', 'warming'} else 'Ouvir')
        self._listen_button.setEnabled(state == 'idle' and bool(self._speech_text) and not self._processing and self._pending_plan is None and not self._conversation_mode)
        if getattr(self, '_conversation_mode', False):
            if state in {'warming', 'synthesizing'}:
                self._conversation_label.setText('Preparando a fala…')
            elif state == 'playing':
                self._conversation_label.setText('Falando…')
            elif state == 'idle' and not self._processing:
                self._conversation_label.setText('Preparando escuta…')
        elif state == 'warming':
            self._conversation_label.setText('Preparando voz…')
        elif state == 'idle':
            self._conversation_label.setText('')
        if state == 'idle':
            self._drain_speech_later()

    def _on_speech_failed(self, message):
        self._preparation.finish('speech', 'failed')
        self._end_conversation()
        self._append('Therion', message)
        self._update_orbe('error')

    def _on_speech_warmed(self):
        self._preparation.finish('speech')
        self._render_preparation()
        self._try_conversation_listen()

    def _render_preparation(self):
        names = {'ai': 'IA', 'transcription': 'Transcrição', 'speech': 'Voz'}
        labels = {'preparing': 'preparando', 'ready': 'pronta', 'failed': 'falhou',
                  'timeout': 'tempo excedido', 'stopped': 'interrompida'}
        items = self._preparation.snapshot()
        self._preparation_label.setText(' · '.join(
            f"{names[name]}: {labels[item['state']]} ({item['seconds']:.1f}s)"
            for name, item in items.items()))

    def _begin_preparation(self):
        ai_timeout = self._config.get('ai', {}).get('timeout_seconds', 90)
        if not isinstance(ai_timeout, (int, float)) or ai_timeout <= 0:
            ai_timeout = 90
        self._ai_warm_ready = self._ai_resource_recent()
        if not self._ai_preparing:
            self._ai_warm_epoch = self._ai_preparation_epoch
            self._ai_warm_core = self._orchestrator.ai_core
        self._preparation.begin(
            {'ai': 'ready' if self._ai_warm_ready else 'preparing',
             'transcription': 'ready' if self._voice_service.state == VoiceModelService.STATE_READY else 'preparing',
             'speech': 'ready' if self._speech_output.is_ready else 'preparing'},
            {'ai': ai_timeout, 'transcription': 120, 'speech': 120},
        )
        self._render_preparation()

    def _toggle_conversation(self):
        if self._conversation_mode:
            self._end_conversation()
            return
        if self._processing or self._pending_plan is not None or not self._speech_output:
            return
        self._conversation_mode = True
        self._conversation_heard_at = time.monotonic()   # abrir a conversa conta como falar com ele
        self._conversation_generation += 1
        self._begin_preparation()
        self._conversation_primed = False
        self._orchestrator.voice_conversation = True
        self._conversation_button.setText('Encerrar conversa')
        self._voice_button.hide()
        self._conversation_label.setText('Preparando voz e IA…')
        self._speech_output.keep_warm = True
        self._speech_output.stop()
        if not self._speech_output.warmup():
            self._end_conversation()
            return
        self._on_voice_clicked()
        if not self._conversation_mode:
            return
        if self._voice_pipeline is not None:
            self._voice_pipeline.set_fast_mode(False)
        self._conversation_timer.start()
        self._prepare_ai_background()

    def _prepare_voice_background(self):
        if self._closing or self._conversation_mode or not self._speech_output:
            return
        self._speech_output.warmup()
        self._on_voice_clicked()
        self._prepare_ai_background()

    def _prepare_ai_background(self):
        if self._closing:
            return
        if self._ai_resource_recent():
            if self._conversation_mode:
                self._ai_warm_ready = True
                self._preparation.finish('ai')
                self._render_preparation()
                self._try_conversation_listen()
            return
        if self._ai_preparing:
            # Uma abertura explícita pode aproveitar o preload do startup. Uma
            # sessão encerrada/limpa muda a época e não pode adotar esse trabalho.
            if (self._ai_warm_epoch == self._ai_preparation_epoch
                    and self._ai_warm_core is self._orchestrator.ai_core):
                self._ai_warm_generation = self._conversation_generation
            return
        self._ai_preparing = True
        self._ai_warm_token += 1
        token = self._ai_warm_token
        self._ai_warm_generation = self._conversation_generation
        core = self._orchestrator.ai_core
        self._ai_warm_epoch = self._ai_preparation_epoch
        self._ai_warm_core = core
        def warm():
            success = core is not None
            try:
                if core is not None:
                    core.warmup()
            except Exception:
                success = False
            try:
                self._warm_finished.emit(token, success)
            except RuntimeError:
                pass
        threading.Thread(target=warm, name='therion-ai-warmup', daemon=True).start()

    def _ai_resource_recent(self):
        core = self._orchestrator.ai_core
        if (self._closing or core is None or core is not self._ai_resource_core
                or self._ai_resource_ready_at is None):
            return False
        age = self._ai_warm_clock() - self._ai_resource_ready_at
        return 0 <= age < self._AI_READY_TTL_SECONDS

    def _invalidate_ai_readiness(self):
        self._ai_resource_ready_at = None
        self._ai_resource_core = None
        self._ai_warm_ready = False
        self._ai_preparation_epoch += 1

    def _on_ai_warmed(self, token, success):
        if token != self._ai_warm_token:
            return
        self._ai_preparing = False
        if self._closing:
            return
        if (self._ai_warm_generation != self._conversation_generation
                or self._ai_warm_epoch != self._ai_preparation_epoch
                or (self._ai_warm_core is not None
                    and self._ai_warm_core is not self._orchestrator.ai_core)):
            if self._conversation_mode:
                self._prepare_ai_background()
            return
        if success:
            self._ai_resource_ready_at = self._ai_warm_clock()
            self._ai_resource_core = self._orchestrator.ai_core
        else:
            self._invalidate_ai_readiness()
        self._ai_warm_ready = success
        self._preparation.finish('ai', 'ready' if success else 'failed')
        self._render_preparation()
        if not self._conversation_mode:
            return
        if not success:
            self._end_conversation()
            self._append('Therion', 'Não foi possível preparar a IA local para conversar.')
            return
        self._try_conversation_listen()

    def _try_conversation_listen(self):
        if not getattr(self, '_conversation_mode', False):
            return
        delay = self._conversation_listen_after - time.monotonic()
        if delay > 0:
            QTimer.singleShot(max(1, int(delay * 1000) + 1), self._try_conversation_listen)
            return
        cycle = getattr(getattr(self, '_voice_pipeline', None), 'cycle', None)
        if isinstance(cycle, VoiceCycle) and not self._voice_pipeline.ready_to_capture:
            # O timer Qt pode acordar antes da barreira antieco do ciclo.
            # Reagendar somente essa espera, nunca durante processamento/fala.
            if cycle.state(self._voice_pipeline.state) == 'rearming':
                QTimer.singleShot(50, self._try_conversation_listen)
            return
        wake_turn = getattr(self, '_wake_turn', None)
        # Turno aberto pelo nome grava logo, sem esperar IA e voz aquecerem: a fala depois do nome não pode se perder.
        if self._processing or not (self._ai_warm_ready or wake_turn is not None):
            return
        if wake_turn is None and not self._conversation_primed and not self._preparation.ready:
            return
        if wake_turn is None and not self._speech_output.is_ready and not self._conversation_primed:
            return
        if self._speech_output.state not in {'idle', 'warming'}:
            return
        pipeline = self._voice_pipeline
        if pipeline is None or pipeline.state != VoicePipeline.STATE_IDLE:
            return
        pipeline.set_fast_mode(False)
        if wake_turn is None:   # turno novo sem o nome: um disparo ainda sem desfecho não vale mais para ele
            self._wake_outcome('ignorado: turno descartado')
        listen = ({'preroll': self._wake_preroll(wake_turn), 'no_speech_seconds': 5.0} if wake_turn is not None
                  else {'no_speech_seconds': 8.0} if getattr(self, '_wake_opened', False) else {})
        if not pipeline.start(automatic=True, **listen):
            self._end_conversation()
            self._append('Therion', 'Não foi possível abrir o microfone. Verifique o dispositivo.')
            return
        self._wake_turn = None
        self._own_conversation_capture(pipeline)

    def _own_conversation_capture(self, pipeline):
        """A captura que acabou de abrir é o turno atual da conversa."""
        self._conversation_capture_started_at = time.monotonic()
        self._conversation_capture_generation = pipeline.generation
        self._conversation_confirmation_plan = self._pending_plan
        self._conversation_confirmation_token = self._orchestrator.confirmation_id
        self._conversation_primed = True
        self._conversation_label.setText('Ouvindo sua confirmação…' if self._pending_plan is not None else 'Ouvindo…')
        self._listen_button.setEnabled(False)

    def _poll_conversation(self):
        if not self._conversation_mode:
            return
        self._render_preparation()
        expired = self._preparation.expired()
        if expired is not None:
            self._invalidate_ai_readiness()
            name = {'ai': 'IA local', 'transcription': 'transcrição', 'speech': 'voz'}[expired]
            self._end_conversation()
            self._append('Therion', f'A preparação de {name} excedeu o tempo limite. '
                         'Você pode continuar digitando ou tentar conversar por voz novamente.')
            return
        if self._voice_pipeline is None:
            return
        pipeline = self._voice_pipeline
        # O aquecimento da fala pode terminar antes da pausa antieco.
        # Nesse caso nenhum outro sinal e obrigado a chegar: reavaliar na
        # conversa ainda ativa permite retomar sem reabrir uma sessao encerrada.
        if pipeline.state == VoicePipeline.STATE_IDLE and not self._conversation_primed:
            self._try_conversation_listen()
            return
        if pipeline.state == VoicePipeline.STATE_RECORDING and pipeline.input_stalled:
            self._end_conversation()
            self._append('Therion', 'O microfone parou de enviar áudio. Verifique a conexão e abra a conversa novamente.')
            return
        if pipeline.state == VoicePipeline.STATE_RECORDING and pipeline.utterance_complete:
            if getattr(pipeline, 'endpoint_reason', None) == 'detector_error':
                self._end_conversation()
                self._append('Therion', 'A detecção de fim de fala falhou. Encerrei a escuta; '
                             'você pode continuar digitando ou iniciar a conversa novamente.')
                return
            if getattr(pipeline, 'endpoint_reason', None) == 'no_speech' and getattr(self, '_wake_opened', False):
                self._wake_outcome('sem fala')
                self._end_conversation()   # ninguém falou depois do nome (ou na continuação): volta a dormir
                return
            if not pipeline.has_speech:
                self._wake_outcome('sem fala')
                pipeline.cancel()
                self._try_conversation_listen()
                return
            self._conversation_label.setText('Transcrevendo…')
            if not pipeline.stop():
                self._try_conversation_listen()

    def _conversation_reply(self):
        if not self._conversation_mode:
            return
        if not self._speech_text:
            self._end_conversation()
            return
        self._last_conversation_spoken = self._speech_text
        intro=getattr(self,'_briefing_intro',None)
        if intro is not None:
            if not self._worker_is_current(intro['worker']):
                self._briefing_intro=None
                return
            if intro['stopped']:
                self._briefing_intro=None
                self._conversation_playback_finished()
                return
            tail=self._speech_text
            if tail.startswith(intro['greeting']):tail=tail[len(intro['greeting']):].lstrip()
            intro['tail']=tail
            if intro['active']:return
            self._briefing_intro=None
            if tail:self._speech_output.speak(tail)
            else:self._conversation_playback_finished()
            return
        self._poll_workflow_progress()
        # O worker já terminou e o resultado público foi aplicado antes daqui.
        if getattr(self,'_last_agent_response_status',None)=='success' and self._speech_output.commit_prefix(self._speech_text) is True:
            return
        self._speech_output.speak(self._speech_text)

    def _conversation_playback_finished(self):
        intro=getattr(self,'_briefing_intro',None)
        if intro is not None:
            intro['active']=False
            tail=intro['tail']
            if tail is not None:
                self._briefing_intro=None
                if (not intro['stopped'] and self._conversation_mode
                        and self._worker_is_current(intro['worker']) and tail):
                    self._speech_output.speak(tail)
                    return
            elif self._processing:return
        if self._conversation_mode and self._wake_end_after_reply:
            self._end_conversation()
            return
        if self._conversation_mode:
            self._conversation_heard_at = time.monotonic()   # a janela de 8 s da resposta começa aqui
            self._conversation_listen_after = time.monotonic() + 0.6
            QTimer.singleShot(600, self._try_conversation_listen)

    def _end_conversation(self):
        narration=getattr(self,'_progress_narration',None)
        if narration is not None:narration.cancel()
        self._briefing_intro=None
        if not getattr(self, '_conversation_mode', False):
            return
        for worker in (self._command_worker, self._confirmation_worker):
            if isinstance(worker, (_CommandWorker, _ConfirmationWorker)) and worker.conversation_generation is not None:
                worker.cancelled.set()
        self._wake_outcome('ignorado: conversa encerrada')
        self._wake_turn = None
        self._wake_opened = False
        self._wake_end_after_reply = False
        self._conversation_mode = False
        self._last_conversation_spoken = ''
        self._conversation_listen_after = 0.0
        self._conversation_generation += 1
        self._ai_preparation_epoch += 1
        self._ai_warm_ready = False
        self._preparation.stop()
        self._render_preparation()
        self._conversation_capture_generation = None
        self._conversation_confirmation_plan = None
        self._conversation_confirmation_token = None
        self._conversation_timer.stop()
        self._orchestrator.voice_conversation = False
        if self._voice_pipeline is not None:
            self._voice_pipeline.cancel()
            self._voice_pipeline.set_fast_mode(False)
        self._speech_output.release()
        self._conversation_button.setText('Conversar por voz')
        self._voice_button.show()
        self._conversation_label.setText('')
        if not self._processing and self._pending_plan is None:
            self._update_orbe('idle')


def main() -> int:
    """Ponto de entrada da aplicação desktop."""
    from therion.interface.graphics import prepare_graphics
    prepare_graphics()
    try:  # Barra de tarefas: agrupa como "Therion" com o ícone próprio, não como Python.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Therion.Desktop')
    except Exception:
        pass
    app = QApplication(sys.argv)
    from therion.autonomy.windows import SingleInstance, build_runtime
    instance = SingleInstance()
    if not instance.acquired:
        instance.close()
        print('Therion já está aberto nesta sessão.')
        return 0
    config = load_config()
    try:
        runtime = build_runtime(load_config, save_config)
        window = MainWindow(app, config, config_loader=load_config, config_writer=save_config,
            autonomy_runtime=runtime)
        # O atalho (therion.interface.launcher) pede por aqui para mostrar a janela já aberta.
        from PySide6.QtNetwork import QLocalServer
        activation = QLocalServer(app)
        QLocalServer.removeServer('TherionV4-activate')
        if activation.listen('TherionV4-activate'):
            def _activate() -> None:
                while activation.hasPendingConnections():
                    activation.nextPendingConnection().close()
                window._show_window()
            activation.newConnection.connect(_activate)
        if '--start-minimized' not in sys.argv and not config.get("ui", {}).get("start_minimized", False):
            window.show()
        elif window._tray_icon is None:
            window.show()  # Sem bandeja, a janela precisa continuar acessível.
        return app.exec()
    finally:
        instance.close()


if __name__ == "__main__":
    sys.exit(main())
