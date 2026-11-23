"""Painel Constelação: apresentação desacoplada dos fluxos de comando existentes."""
from copy import deepcopy
from datetime import date, timedelta, datetime
import json
import os
import re
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QProcess, QRect, QPoint, QEvent, QVariantAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QShortcut, QKeySequence, QCursor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QStackedWidget, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QTabWidget, QComboBox, QCheckBox, QScrollArea, QSizePolicy, QInputDialog,
    QFormLayout, QSpinBox, QMessageBox, QFileDialog, QToolButton, QGroupBox, QGridLayout)
from therion.agent.contracts import CancellationToken, ToolResult
from .constellation import Constellation
from .dashboard_data import DashboardSource
from .presentation import Presentation, QualityController, normalized_level, WorkspacePresentation
from .design_system import COMPONENT_STYLE, history_html, COLORS
from .voice_meter import VoiceMeter
from .workspace import SceneWorkspace
from .singularity_chrome import OrbShortcut, GlyphSkin, AgendaDelegate, TaskDelegate
from .surface_dialogs import SurfaceHost, InputDialog as QInputDialog, MessageBox as QMessageBox, FileDialog as QFileDialog
from .mailbox_panel import MailboxPanel, MailPreview
from shiboken6 import isValid

SECTION_KEYS=('', 'conversations','calendar','tasks','knowledge','tools','settings')
SECTION_TITLES=('Início','Conversas','Agenda','Tarefas','Conhecimento','Ferramentas','Configurações')


STYLE = """
QFrame#card { background:transparent; border:0; }
QLabel#heading { font-size:22px; font-weight:600; }
QToolButton#activityLauncher { padding:6px; }
QFrame#statusPill { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; }
QLabel#healthDot { color:#B5B1C5; font-size:12px; border:1px solid transparent; border-radius:8px; padding:0 3px; }
QLabel#healthDot[clickable="true"]:hover { color:#F1F0F7; }
QLabel#healthDot[clickable="true"]:focus { border-color:#C4B5FD; }
QLabel#navBadge { background:#282036; color:#C4B5FD; border-radius:9px; font-size:11px; font-weight:600; }
QLabel#greetingKicker { color:#C4B5FD; font-size:11px; letter-spacing:3px; }
QLabel#greetingTitle { color:#F1F0F7; font-size:22px; font-weight:600; }
QPushButton#quickAction { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; color:#E5E1F0; font-size:13px; padding:8px 16px; }
QPushButton#quickAction:hover { border-color:#A78BFA; background:rgba(98,80,128,60); }
QPushButton#quickAction:disabled { color:#8E8A9C; }
QPushButton#composerAction { background:#211D30; border:1px solid #443B58; border-radius:10px; color:#DDD6FE; font-size:12px; padding:0 12px; min-height:32px; }
QPushButton#composerAction:hover { border-color:#A78BFA; }
QPushButton#composerStop { background:#3A1F2A; border:1px solid #7F3B4F; border-radius:10px; color:#FECDD3; font-size:12px; padding:0 12px; min-height:32px; }
"""

def greeting_for(moment):
    """Período pelo relógio local verificado; madrugada conta como noite."""
    hour=moment.hour
    if 5<=hour<12:return 'BOM DIA'
    if 12<=hour<18:return 'BOA TARDE'
    return 'BOA NOITE'


def read_stt_health(url='http://127.0.0.1:3902/stt/health'):
    """Somente leitura do estado do Parakeet local; nunca inicia, reinicia nem envia áudio."""
    opener=build_opener(ProxyHandler({}))
    try:
        with opener.open(url,timeout=2) as response:raw=response.read(65536)
    except HTTPError as error:
        raw=error.read(65536) if error.code==503 else b''
        if not raw:return dict(status='error',failure_type='HTTP '+str(error.code))
    except Exception:
        return dict(status='offline')
    try:
        state=json.loads(raw)
        return state if isinstance(state,dict) else dict(status='unknown')
    except ValueError:
        return dict(status='unknown')


PATHS = [
    'M3 11 12 3l9 8M5 10v11h5v-6h4v6h5V10',
    'M4 4h16v13H9l-5 4zM8 8h8M8 12h6',
    'M4 6h16v15H4zM8 3v6M16 3v6M4 11h16',
    'M4 12l5 5L20 5M3 4h7M3 21h18',
    'M3 5l9-3 9 3v15l-9-3-9 3zM12 2v15',
    'M14 3a5 5 0 0 0-6 6L2 15l7 7 6-6a5 5 0 0 0 6-6l-4 4-5-5z',
    'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37c1 .608 2.296.07 2.572-1.065zM9 12a3 3 0 1 0 6 0a3 3 0 0 0-6 0',   # engrenagem (Configurações)
    'M3 5h18v14H3zM3 6l9 7 9-7',
    'M21 21l-6-6M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
    'M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5',
    'M3 8h5V3M16 3v5h5M21 16h-5v5M8 21v-5H3',
]


def icon(index, active=False):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           '<path d="'+PATHS[index]+'" fill="none" stroke="'+('#A387E8' if active else '#B5B1C5')+'" stroke-width="1.6" '
           'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    pixmap = QPixmap(48,48); pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap); QSvgRenderer(svg.encode()).render(painter); painter.end()
    return QIcon(pixmap)


def label(text, name=''):
    widget = QLabel(text); widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback):
    widget = QPushButton(text); widget.clicked.connect(callback)
    widget.setAccessibleName(text)
    return widget


def scroll_page():
    scroll = QScrollArea(); scroll.setWidgetResizable(True)
    body = QWidget(); layout = QVBoxLayout(body); layout.setContentsMargins(16,16,16,16)
    layout.setSpacing(16); scroll.setWidget(body)
    return scroll, layout


_RUNNING_READS = set()


class ReadWorker(QThread):
    def __init__(self, function, parent=None):
        # Sem pai Qt: destruir o painel com a leitura em andamento destruía a thread
        # ainda rodando, e o Qt derruba o processo. A thread se segura até terminar.
        super().__init__()
        self.function = function
        self.token = CancellationToken()
        self.result = None

    def start(self, *args):
        # Solta as que já terminaram aqui, e não no sinal finished: soltar durante o
        # próprio sinal destruiria a thread antes de os outros ouvintes serem avisados.
        _RUNNING_READS.difference_update([worker for worker in _RUNNING_READS if not isValid(worker) or worker.isFinished()])
        _RUNNING_READS.add(self)
        super().start(*args)

    def run(self):
        try:
            self.result = self.function(self.token)
        except Exception:
            self.result = {'state':'error','message':'Consulta indisponível. Atualize para tentar novamente.', 'items':[]}


class GlanceCard(QPushButton):
    """Resumo de leitura na tela inicial; o clique só abre a janela correspondente."""
    def __init__(self,title,icon_index,callback,parent=None):
        super().__init__(parent)
        self.setObjectName('glanceCard');self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(64);self.setAccessibleName('Abrir '+title)
        # Linha do painel único: ícone em quadro tingido, rótulo e detalhe, número grande à direita.
        row=QHBoxLayout(self);row.setContentsMargins(10,10,12,10);row.setSpacing(12)
        glyph=QLabel();glyph.setObjectName('glanceIcon');glyph.setPixmap(icon(icon_index,True).pixmap(20,20))
        glyph.setFixedSize(34,34);glyph.setAlignment(Qt.AlignCenter);row.addWidget(glyph,0,Qt.AlignVCenter)
        texts=QVBoxLayout();texts.setSpacing(2);row.addLayout(texts,1)
        self.title=QLabel(title);self.title.setObjectName('glanceTitle')
        self.detail=_ElidedLabel('');self.detail.setObjectName('glanceDetail');self.detail.setWordWrap(False)
        self.detail.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.value=QLabel('');self.value.setObjectName('glanceValue');self.value.setWordWrap(False)
        texts.addWidget(self.title);texts.addWidget(self.detail);row.addWidget(self.value,0,Qt.AlignVCenter)
        for widget in (glyph,self.title,self.value,self.detail):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents);widget.setTextFormat(Qt.PlainText)
        self.clicked.connect(callback)

    def show_summary(self,text,count=None):
        # Número grande só quando há contagem; o texto integral fica no tooltip.
        self._text=text
        self.value.setText('' if count is None else str(count));self.value.setVisible(count is not None)
        self.detail.full_text=text;self.detail.elide();self.setToolTip(text)


class _ElidedLabel(QLabel):
    """Corta pela largura real com reticências, em vez de um limite fixo de letras."""
    full_text=''
    def elide(self):
        self.setText(self.fontMetrics().elidedText(self.full_text,Qt.ElideRight,max(0,self.width())))
    def resizeEvent(self,event):
        super().resizeEvent(event);self.elide()


class ClickableDot(QLabel):
    """Ponto de saúde que também é botão (Nome): clique, Enter e Espaço."""
    clicked=Signal()

    def __init__(self,text=''):
        super().__init__(text);self.setProperty('clickable',True)
        self.setCursor(Qt.PointingHandCursor);self.setFocusPolicy(Qt.StrongFocus)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton and self.rect().contains(event.position().toPoint()):self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Space):
            if not event.isAutoRepeat():self.clicked.emit()   # tecla segurada não liga e desliga em sequência
        else:super().keyPressEvent(event)


class HomeGlance(QFrame):
    """Agenda, tarefas e e-mails já lidos pelo painel; não dispara consultas novas."""
    STYLE = """
    QFrame#homeGlance { background:transparent; border:0; }
    QFrame#glancePanel { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; }
    QFrame#glanceDivider { background:rgba(255,255,255,20); border:0; }
    QPushButton#glanceCard { background:transparent; border:0; border-radius:10px; padding:0; text-align:left; }
    QPushButton#glanceCard:hover { background:rgba(98,80,128,60); }
    QPushButton#glanceCard:focus { border:2px solid #C4B5FD; }
    QLabel#glanceIcon { background:rgba(196,181,253,38); border-radius:10px; }
    QLabel#glanceTitle { color:rgba(241,240,247,153); font-size:11px; letter-spacing:1px; }
    QLabel#glanceValue { color:#F1F0F7; font-size:18px; font-weight:600; }
    QLabel#glanceDetail { color:#C4B5FD; font-size:12px; }
    """
    def __init__(self,dashboard):
        super().__init__(dashboard)
        self.setObjectName('homeGlance');self.setStyleSheet(self.STYLE)
        column=QVBoxLayout(self);column.setContentsMargins(0,0,0,0);column.setSpacing(0)
        panel=QFrame();panel.setObjectName('glancePanel');column.addWidget(panel);column.addStretch()
        rows=QVBoxLayout(panel);rows.setContentsMargins(6,6,6,6);rows.setSpacing(0)
        self.calendar=GlanceCard('AGENDA DE HOJE',2,lambda:dashboard.navigate(2))
        self.tasks=GlanceCard('TAREFAS',3,lambda:dashboard.navigate(3))
        self.mail=GlanceCard('E-MAILS',7,lambda:dashboard.open_mail())
        for index,card in enumerate((self.calendar,self.tasks,self.mail)):
            if index:
                line=QFrame();line.setObjectName('glanceDivider');line.setFixedHeight(1)
                rows.addSpacing(2);rows.addWidget(line);rows.addSpacing(2)
            rows.addWidget(card)
        self.calendar.show_summary('Consultando…');self.tasks.show_summary('Consultando…');self.mail.show_summary('Preparando caixa…')

    def render_calendar(self,result,now):
        state=result.get('state');items=result.get('items',[])
        if state!='ready':
            self.calendar.show_summary(result.get('message') or ('Consultando…' if state=='loading' else 'Agenda indisponível'));return
        if not items:self.calendar.show_summary('Nenhum compromisso hoje');return
        current=now.strftime('%H:%M')
        upcoming=[row for row in items if str(row.get('time','')) >= current or not re.match(r'^\d{2}:\d{2}$',str(row.get('time','')))]
        if upcoming:
            row=upcoming[0];self.calendar.show_summary('Próximo: '+str(row.get('time',''))+' · '+str(row.get('title','')),len(items))
        else:self.calendar.show_summary('Nada mais para hoje',len(items))

    def render_tasks(self,result,pending):
        if result.get('state')!='ready':
            self.tasks.show_summary(result.get('message') or 'Consultando…');return
        if not pending:self.tasks.show_summary('Nenhuma pendente');return
        self.tasks.show_summary('pendente' if pending==1 else 'pendentes',pending)

    def render_mail(self,result,tz=None):
        # Recebe o mesmo estado já publicado para as prévias da caixa.
        items=result.get('items',[]);state=result.get('state')
        if not items:
            self.mail.show_summary(result.get('message') or ('Carregando e-mails…' if state=='loading' else 'Nenhum e-mail carregado'));return
        unread=sum(bool(row.get('unread')) for row in items)
        suffix={'stale':'cache desatualizado','error':'falha na atualização','loading':'atualizando'}.get(state,'')
        latest=items[0].get('subject','') if items else ''
        text=(suffix+' · ' if suffix else '')+('Recente: '+latest if latest else ('Caixa em dia' if not unread else 'não lidos'))
        self.mail.show_summary(text,unread or None)


class _MailGlanceFeed:
    """Adaptador de prévia da caixa para o resumo inicial."""
    def __init__(self,glance):self.glance=glance
    def render(self,result,tz):
        dashboard=self.glance.parent();dashboard._mail_health=result.get('state');self.glance.render_mail(result,tz)
        dashboard.set_badge('mail',sum(bool(row.get('unread')) for row in result.get('items',[])))


class Dashboard(QWidget):
    """Reutiliza os controles nativos; trocar a aparência não troca a sessão."""
    def __init__(self, window, classic):
        super().__init__()
        self.window, self.classic = window, classic
        self.source = DashboardSource(window._orchestrator)
        self.presentation = Presentation()
        self._mini_state = None
        self.day = window._orchestrator._calendar_now().date()
        self.workers = {}
        self.epochs = {'calendar':0,'tasks':0}
        self.dirty = set()
        self.active = False
        self.action_worker = None
        self.calendar_auth = None
        self.auth_cancelled = False
        self.saved_locations = []
        self.task_rows = {'saved':[], 'temporary':[]}
        self.calendar_lists, self.task_tabs = [], [];self.task_status_labels=[]
        self._proposal = None
        self._response = ''
        self.glyph_skins=[];self._clock_value='';self.nav_expanded=True;self._quick_room=True
        self.compact=False;self._normal_geometry=None
        self.workspace_presentation=WorkspacePresentation();self._orb_target=None
        self.orb_transition=QVariantAnimation(self);self.orb_transition.setDuration(320)
        self.orb_transition.setEasingCurve(QEasingCurve.InOutCubic)
        self.orb_transition.valueChanged.connect(lambda rect:self.constellation.set_focus_rect(rect))
        self._layout_ui()
        self.surfaces=SurfaceHost(self)
        self.setStyleSheet(STYLE+COMPONENT_STYLE)
        self.timer = QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.poll)
        self.refresh_timer = QTimer(self); self.refresh_timer.setInterval(300000)
        self.refresh_timer.timeout.connect(self.refresh_visible)

    def _layout_ui(self):
        w = self.window
        self.constellation=Constellation(self)
        self.constellation.lower()
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        header = QWidget(); header.setFixedHeight(56)
        top = QHBoxLayout(header); top.setContentsMargins(12,4,16,4);top.setSpacing(12)
        self.menu_toggle=QToolButton();self.menu_toggle.setObjectName('headerAction');self.menu_toggle.setIcon(QIcon())
        self.menu_toggle.setText('≡')
        self.menu_toggle.setFixedSize(36,36);self.menu_toggle.setAccessibleName('Expandir navegação')
        self.menu_toggle.setToolTip('Expandir ou recolher navegação');self.menu_toggle.clicked.connect(self.toggle_navigation)
        top.addWidget(self.menu_toggle)
        self.menu_toggle.hide()   # layout gaveta: a barra da direita é sempre só ícones
        self.brand_label=label('THERION','brand');top.addWidget(self.brand_label); top.addStretch()
        self.organize_button=QToolButton();self.organize_button.setObjectName('headerAction')
        self.organize_button.setText('Organizar');self.organize_button.setToolTip('Restaurar a organização dos painéis abertos')
        self.organize_button.clicked.connect(lambda:self.workspace.organize());top.addWidget(self.organize_button)
        self.search = QLineEdit(); self.search.setPlaceholderText('Buscar nas conversas…')
        self.search.setMaximumWidth(280); self.search.setAccessibleName('Buscar nas conversas')
        self.search.returnPressed.connect(self.search_history)
        self.status_pill=QFrame();self.status_pill.setObjectName('statusPill')
        pill=QHBoxLayout(self.status_pill);pill.setContentsMargins(14,5,14,5);pill.setSpacing(10)
        self.state_light=label('●');self.state_light.setStyleSheet('color:#9574E5; font-size:14px;')
        self.state_light.setAccessibleName('Indicador de estado');pill.addWidget(self.state_light)
        self.status = label('Pronto para conversar','state'); self.status.setMaximumWidth(290); self.status.setWordWrap(False); pill.addWidget(self.status)
        divider=QFrame();divider.setFixedSize(1,16);divider.setStyleSheet('background:#373244;');pill.addWidget(divider)
        self.health_dots={}
        for key,title in [('ai','IA'),('voice','Voz'),('stt','Parakeet'),('mail','Gmail'),('wake','Nome')]:
            dot=ClickableDot(title) if key=='wake' else QLabel(title)
            dot.setObjectName('healthDot');dot.setTextFormat(Qt.RichText);dot.setWordWrap(False)
            if key=='wake':dot.clicked.connect(lambda:w._toggle_wake())
            pill.addWidget(dot);self.health_dots[key]=(dot,title)
        top.addWidget(self.status_pill)
        self.clock=label(datetime.now().astimezone().strftime('%d/%m/%Y   ·   %H:%M'),'clock');self.clock.setWordWrap(False);top.addWidget(self.clock)
        self.fullscreen_button=QToolButton();self.fullscreen_button.setObjectName('headerAction')
        self.fullscreen_button.setFixedSize(32,32);self.fullscreen_button.setCheckable(True)
        self.fullscreen_button.clicked.connect(w._toggle_full_screen);top.addWidget(self.fullscreen_button)
        self.sync_full_screen(w.isFullScreen())
        # Modo compacto: janela pequena para o segundo monitor (jogo ou trabalho na tela principal).
        self.compact_button=QToolButton();self.compact_button.setObjectName('headerAction')
        self.compact_button.setFixedSize(32,32);self.compact_button.setCheckable(True)
        self.compact_button.clicked.connect(lambda:self.set_compact(not self.compact));top.addWidget(self.compact_button)
        self.header_controls={}
        for title,path,callback in [('Buscar',8,self.open_search),('Minimizar',None,w._minimize_window),('Sair',None,w._quit_application)]:
            control=QToolButton();control.setObjectName('headerAction');control.setToolTip(title);control.setAccessibleName(title)
            control.setFixedSize(32,32)
            if path is not None:control.setIcon(icon(path))
            else:control.setText('−' if title=='Minimizar' else '×')
            control.clicked.connect(callback);top.addWidget(control);self.header_controls[title]=control
        self.find_shortcut=QShortcut(QKeySequence('Ctrl+F'),self);self.find_shortcut.activated.connect(self.open_search)
        root.addWidget(header)
        middle = QHBoxLayout(); middle.setSpacing(0); root.addLayout(middle,1)
        self.nav = QWidget(); self.nav.setFixedWidth(64)
        nav = QVBoxLayout(self.nav);self.nav_layout=nav; nav.setContentsMargins(6,16,6,16); nav.setSpacing(8)
        self.nav_buttons = []
        for index, title in enumerate(SECTION_TITLES):
            b = button(title,lambda checked=False,i=index:self.navigate(i))
            b.setObjectName('nav'); b.setCheckable(True); b.setIcon(icon(index)); b.setIconSize(QSize(20,20))
            b.setFixedHeight(42)
            b.setToolTip(title); self.nav_buttons.append(b); nav.addWidget(b)
        self.nav_buttons[5].hide()   # Ferramentas agora fica dentro de Configurações
        self.mail_nav=button('E-mails',lambda:self.toggle_mail());self.mail_nav.setObjectName('nav')
        self.mail_nav.setCheckable(True);self.mail_nav.setIcon(icon(7));self.mail_nav.setIconSize(QSize(20,20))
        self.mail_nav.setFixedHeight(42);self.mail_nav.setToolTip('Caixa de e-mails');nav.insertWidget(4,self.mail_nav)
        self.nav_caption=label('INTELIGÊNCIA\nEM MOVIMENTO','muted'); nav.addWidget(self.nav_caption)
        self.nav_badges={}
        for key,owner in [('calendar',self.nav_buttons[2]),('tasks',self.nav_buttons[3]),('mail',self.mail_nav)]:
            badge=QLabel('',owner);badge.setObjectName('navBadge');badge.setAlignment(Qt.AlignCenter)
            badge.setAttribute(Qt.WA_TransparentForMouseEvents);badge.hide();self.nav_badges[key]=badge
        self._badge_counts={}
        nav.insertStretch(nav.indexOf(self.nav_buttons[-1]))
        content = QWidget(); center = QVBoxLayout(content); center.setContentsMargins(24,0,16,16); center.setSpacing(8)
        middle.addWidget(content,1)
        # Layout gaveta: a barra fica na borda direita e as seções abrem coladas nela.
        middle.addWidget(self.nav)
        self.pages = QStackedWidget(); center.addWidget(self.pages,1)
        self.home = QWidget(); home = QHBoxLayout(self.home); home.setContentsMargins(0,0,0,0); home.setSpacing(24)
        stage = QWidget(); stage_layout = QVBoxLayout(stage); stage_layout.setContentsMargins(0,0,0,0)
        stage_layout.setSpacing(4)
        self.hero_container=QWidget();self.hero_container.setMinimumHeight(210)
        stage_layout.addWidget(self.hero_container,1)
        self.hero_space=QWidget(self.hero_container)
        self.hero_space.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hero_space.installEventFilter(self)
        self.intro = QLabel('Como posso ajudar, senhor?',self)
        self.intro.setAlignment(Qt.AlignCenter)
        self.intro.setStyleSheet('background:transparent; color:#B9AADE; font-family:Segoe UI; font-size:12px; letter-spacing:2px;')
        self.intro.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.greeting_kicker=QLabel('',self);self.greeting_kicker.setObjectName('greetingKicker')
        self.greeting_title=QLabel('Como posso ajudar?',self);self.greeting_title.setObjectName('greetingTitle')
        for widget in (self.greeting_kicker,self.greeting_title):
            widget.setAlignment(Qt.AlignCenter);widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.update_greeting()
        self.quick_bar=QWidget(self);quick=QHBoxLayout(self.quick_bar);quick.setContentsMargins(0,0,0,0);quick.setSpacing(8)
        quick.addStretch();self.quick_actions=[]
        for text,callback in [('Mostre meu panorama',lambda:self.quick_command('Mostre meu panorama')),
                              ('Abrir e-mails',lambda:self.quick_command('Abra meus e-mails')),
                              ('Nova tarefa',lambda:self.add_task(0)),
                              ('Abrir o Obsidian',lambda:self.quick_command('Abrir o Obsidian'))]:
            action=QPushButton(text);action.setObjectName('quickAction');action.setCursor(Qt.PointingHandCursor)
            action.setStyleSheet('QPushButton { background:rgba(20,19,30,184); border:1px solid rgba(255,255,255,23); border-radius:14px; color:#E5E1F0; font-size:13px; padding:0 16px; min-height:34px; max-height:34px; }'
                                 'QPushButton:hover { border-color:#A78BFA; background:rgba(98,80,128,60); } QPushButton:disabled { color:#8E8A9C; }')
            action.setToolTip('Mesmo efeito de pedir “'+text+'”: confirmações continuam valendo.' if text!='Nova tarefa' else 'Abre o formulário de nova tarefa')
            action.clicked.connect(callback);quick.addWidget(action);self.quick_actions.append(action)
        quick.addStretch()
        self.response_preview=QFrame(self);self.response_preview.setObjectName('responsePreview')
        response_layout=QVBoxLayout(self.response_preview);response_layout.setContentsMargins(14,9,14,10);response_layout.setSpacing(5)
        self.response_title=label('Última resposta','muted');self.response_title.setWordWrap(False)
        response_heading=QHBoxLayout();response_heading.addWidget(self.response_title);response_heading.addStretch()
        response_layout.addLayout(response_heading)
        self.last_response = QTextEdit(); self.last_response.setReadOnly(True)
        self.last_response.setObjectName('lastResponse'); self.last_response.setFixedHeight(96)
        self.last_response.setAlignment(Qt.AlignLeft)
        option=self.last_response.document().defaultTextOption();option.setAlignment(Qt.AlignLeft)
        self.last_response.document().setDefaultTextOption(option)
        self.last_response.setPlainText('')
        self.last_response.setAccessibleName('Última resposta do Therion')
        response_layout.addWidget(self.last_response)
        self.listen_slot=QHBoxLayout();self.listen_slot.setSpacing(6);response_heading.addLayout(self.listen_slot)
        history_link = button('Ver conversa completa',lambda:self.navigate(1)); history_link.setObjectName('textLink')
        self.history_link=history_link
        response_heading.addWidget(history_link)
        self.response_space=QWidget();self.response_space.setFixedHeight(152);stage_layout.addWidget(self.response_space)
        self.home_copy=(self.response_preview,)
        for widget in self.home_copy:
            policy=widget.sizePolicy(); policy.setRetainSizeWhenHidden(True); widget.setSizePolicy(policy)
        home.addWidget(stage,1)
        self.pages.addWidget(self.home)
        conversation, layout = scroll_page()
        layout.addWidget(self.search)
        self.history_slot = QVBoxLayout(); layout.addLayout(self.history_slot,1)
        history_buttons = QHBoxLayout(); self.clear_slot = QHBoxLayout(); history_buttons.addLayout(self.clear_slot)
        self.sessions_toggle=button('Sessões anteriores',self.toggle_sessions)
        self.sessions_toggle.setCheckable(True)
        history_buttons.addWidget(self.sessions_toggle)
        self.latest_button=button('Ir para o mais recente',self.scroll_to_latest)
        history_buttons.addWidget(self.latest_button)
        layout.addLayout(history_buttons); self.pages.addWidget(conversation)
        agenda, layout = scroll_page()
        # Navegação de dias em uma única linha: ‹ data › · Hoje · atualizar.
        self.date_label = label(''); self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setStyleSheet('font-size:15px; font-weight:600; color:#F1F0F7;')
        self.calendar_dates=QWidget();dates = QHBoxLayout(self.calendar_dates);self.calendar_date_layout=dates
        dates.setContentsMargins(0,0,0,0);dates.setSpacing(8);self.calendar_date_buttons=[]
        for text,delta,name in [('‹',-1,'Dia anterior'),('Hoje',0,'Voltar para hoje'),('›',1,'Próximo dia')]:
            control=button(text,lambda checked=False,d=delta:self.change_day(d))
            control.setToolTip(name);control.setAccessibleName(name);self.calendar_date_buttons.append(control)
        refresh=button('↻',lambda:self.refresh('calendar'));refresh.setToolTip('Atualizar agenda');refresh.setAccessibleName('Atualizar agenda')
        self.calendar_date_buttons.append(refresh)
        previous,today,following,refresh=self.calendar_date_buttons
        for control in (previous,following,refresh):control.setFixedWidth(44)
        dates.addWidget(previous);dates.addWidget(self.date_label,1);dates.addWidget(following)
        dates.addSpacing(8);dates.addWidget(today);dates.addWidget(refresh)
        layout.addWidget(self.calendar_dates)
        self.calendar_page_layout=layout;self.calendar_compact=False
        layout.addWidget(self.calendar_card(),1)
        layout.addSpacing(8);self.mail_preview=MailPreview();layout.addWidget(self.mail_preview)
        self.calendar_connection = label('','muted'); layout.addWidget(self.calendar_connection)
        self.calendar_connect=button('Conectar Google Calendar',self.calendar_help)
        layout.addWidget(self.calendar_connect); self.pages.addWidget(agenda)
        tasks, layout = scroll_page()
        layout.addWidget(self.tasks_card(),1)
        layout.addWidget(button('Atualizar tarefas',lambda:self.refresh('tasks'))); self.pages.addWidget(tasks)
        knowledge, layout = scroll_page()
        layout.addWidget(label('Seu conhecimento','heading'))
        layout.addWidget(label('Consulte as fontes que o senhor autorizou.','muted'))
        self.knowledge_info = label('','muted'); layout.addWidget(self.knowledge_info)
        self.knowledge_paths=label('','muted');self.knowledge_paths.hide()
        details=button('Ver caminhos das fontes',lambda:self.knowledge_paths.setVisible(not self.knowledge_paths.isVisible()))
        details.setObjectName('textLink');layout.addWidget(details);layout.addWidget(self.knowledge_paths)
        self.knowledge_query = QLineEdit(); self.knowledge_query.setPlaceholderText('O que deseja consultar nas fontes autorizadas?')
        self.knowledge_query.returnPressed.connect(self.search_knowledge); layout.addWidget(self.knowledge_query)
        layout.addWidget(button('Consultar fontes',self.search_knowledge))
        layout.addWidget(button('Estado da memória',lambda:self.command('status da memoria')))
        layout.addWidget(button('Revisões disponíveis',lambda:self.command('liste as revisoes de aprendizados')))
        layout.addStretch(); self.pages.addWidget(knowledge)
        tools, layout = scroll_page()
        layout.addWidget(label('As ferramentas agora ficam em Configurações.','muted')); layout.addStretch()
        self.pages.addWidget(tools)
        settings, layout = scroll_page()
        layout.addWidget(label('Configurações','heading'))
        settings_root=layout
        def settings_group(title):
            box=QGroupBox(title);part=QVBoxLayout(box);part.setSpacing(12);settings_root.addWidget(box);return part
        layout=settings_group('Ferramentas')
        layout.addWidget(label('Capacidades, propostas e procedimentos seguem as autorizações do Therion.','muted'))
        self.agent_slot = QVBoxLayout(); layout.addLayout(self.agent_slot)
        layout.addWidget(button('Propostas pendentes',lambda:self.agent_tab(2)))
        layout.addWidget(button('Procedimentos',self.procedures))
        self.details_slot = QVBoxLayout(); layout.addLayout(self.details_slot)
        layout=settings_group('Aparência')
        self.settings_status = label('','muted')
        self.quality = QComboBox()
        choices=[('Automática · adaptar ao computador','auto'),('Alta · mais detalhes','high'),
                 ('Equilibrada','medium'),('Economia de recursos','low')]
        for title,value in choices:
            self.quality.addItem(title,value)
        self.quality.setAccessibleName('Qualidade gráfica'); layout.addWidget(self.quality)
        self.reduced = QCheckBox('Reduzir movimento'); layout.addWidget(self.reduced)
        self.graphics_note = label('','muted'); layout.addWidget(self.graphics_note)
        layout.addWidget(button('Salvar aparência',self.save_appearance))
        layout=settings_group('Voz e modelo');form = QFormLayout();form.setSpacing(12)
        self.model = QLineEdit(); self.model.setMaxLength(100); form.addRow('Modelo local',self.model)
        self.ai_enabled = QCheckBox('IA habilitada'); form.addRow(self.ai_enabled)
        self.voice_enabled = QCheckBox('Respostas faladas habilitadas'); form.addRow(self.voice_enabled)
        self.voice_name = QLineEdit(); self.voice_name.setMaxLength(100); form.addRow('Voz do provedor atual',self.voice_name)
        layout.addLayout(form)
        layout.addWidget(label('Alterações de modelo e voz entram em vigor na próxima abertura.','muted'))
        layout.addWidget(button('Salvar modelo e voz',self.save_runtime))
        layout=settings_group('Integrações e interface')
        layout.addWidget(button('Integrações e permissões',lambda:self.agent_tab(0)))
        layout.addWidget(label('Central de Comando · interface padrão','muted'))
        layout.addWidget(button('Usar esta interface ao iniciar',lambda:w._select_interface('constellation')))
        layout.addWidget(button('Voltar à interface clássica',lambda:w._select_interface('classic')))
        layout=settings_group('Diagnóstico')
        layout.addWidget(self.settings_status)
        layout.addWidget(label('Detalhes de execução, renderização e provedor ficam nesta área.','muted'))
        self.diagnostic_slot=QVBoxLayout();layout.addLayout(self.diagnostic_slot)
        layout=settings_root
        layout.addStretch(); self.pages.addWidget(settings)
        self.confirm_overlay=QWidget(self)
        confirmations=QVBoxLayout(self.confirm_overlay);confirmations.setContentsMargins(0,0,0,0)
        self.confirm_slot=QVBoxLayout();confirmations.addLayout(self.confirm_slot)
        self.proposal_bar = QFrame(); self.proposal_bar.setObjectName('proposal')
        proposal = QVBoxLayout(self.proposal_bar); self.proposal_text = QTextEdit()
        self.proposal_text.setReadOnly(True); self.proposal_text.setMaximumHeight(100)
        proposal.addWidget(self.proposal_text)
        approvals = QHBoxLayout()
        self.approve = button('Confirmar proposta',self.approve_proposal)
        self.discard = button('Cancelar proposta',self.discard_proposal)
        approvals.addWidget(self.approve); approvals.addWidget(self.discard); proposal.addLayout(approvals)
        self.proposal_bar.hide();confirmations.addWidget(self.proposal_bar)
        self.confirm_overlay.hide()
        self.control_bar=QWidget(self);self.control_slot = QHBoxLayout(self.control_bar)
        self.control_bar.installEventFilter(self)
        self.control_slot.setContentsMargins(0,0,0,0);self.control_slot.setSpacing(8);self.control_slot.setAlignment(Qt.AlignHCenter)
        self.preparation_slot = QVBoxLayout(); center.addLayout(self.preparation_slot)
        self.composer=QFrame(self); self.composer.setObjectName('composer')
        self.input_slot = QHBoxLayout(self.composer); self.input_slot.setSpacing(8)
        self.input_slot.setContentsMargins(12,6,8,6)
        self.composer_space=QWidget();self.composer_space.setFixedHeight(116);center.addWidget(self.composer_space)
        self.meter=VoiceMeter();self.meter.setFixedSize(42,30); self.input_slot.addWidget(self.meter)
        self.notice_slot = QVBoxLayout(); center.addLayout(self.notice_slot)
        self.nav_buttons[0].setChecked(True)
        self.nav_buttons[0].setIcon(icon(0,True))
        self.workspace=SceneWorkspace(self,self.workspace_rect,self.panel_opening_rect)
        self.workspace.changed.connect(self._workspace_changed)
        preferred=[QSize(700,520),QSize(480,520),QSize(420,540),QSize(600,440),QSize(620,480),QSize(650,540)]
        contents=[self.pages.widget(i) for i in range(1,7)]
        for index,(page,size) in enumerate(zip(contents,preferred),1):
            self.pages.removeWidget(page)
            self.workspace.register(SECTION_KEYS[index],SECTION_TITLES[index],page,size,
                bounds=self.calendar_bounds if index==2 else None)
        self.mailbox=MailboxPanel(self)
        self.mailbox.attach_preview(self.mail_preview)
        self.glance=HomeGlance(self);self.mailbox.previews.append(_MailGlanceFeed(self.glance));self.glance.hide()
        mail_scroll=QScrollArea();mail_scroll.setWidgetResizable(True);mail_scroll.setFrameShape(QFrame.NoFrame)
        mail_scroll.setWidget(self.mailbox)
        self.workspace.register('mail','E-mails',mail_scroll,QSize(1100,720))
        self.activity_dock=QWidget(self)
        dock=QVBoxLayout(self.activity_dock); dock.setContentsMargins(0,0,0,0); dock.setSpacing(12)
        self.activity_buttons={}
        for key,title,index in [('tasks','Tarefas',3),('calendar','Agenda',2)]:
            launcher=OrbShortcut(); launcher.setObjectName('activityLauncher')
            launcher.setToolButtonStyle(Qt.ToolButtonIconOnly)
            launcher.setIcon(icon(index)); launcher.setIconSize(QSize(24,24))
            launcher.setText(title+' · —'); launcher.setFixedSize(44,44); launcher.setCheckable(True)
            launcher.setAccessibleName('Abrir '+title); launcher.setToolTip('Abrir '+title+' nesta cena')
            launcher.clicked.connect(lambda checked=False,k=key:self.toggle_activity(k))
            dock.addWidget(launcher); self.activity_buttons[key]=launcher
        self.mail_button=OrbShortcut();self.mail_button.setObjectName('activityLauncher');self.mail_button.setFixedSize(44,44)
        self.mail_button.setIcon(icon(7));self.mail_button.setIconSize(QSize(24,24))
        self.mail_button.setToolTip('Abrir janela de e-mails');self.mail_button.setAccessibleName('Abrir caixa de entrada')
        self.mail_button.setCheckable(True);self.mail_button.clicked.connect(lambda:self.open_mail())
        dock.addWidget(self.mail_button)
        self.activity_dock.raise_()
        self.activity_dock.hide()
        # Modo compacto: no lugar da barra, três atalhos com os números do dia.
        self.compact_bar=QWidget(self);row=QHBoxLayout(self.compact_bar);row.setContentsMargins(0,0,0,0);row.setSpacing(8)
        self.compact_shortcuts={}
        for key,title,callback in [('calendar','agenda',lambda:self.navigate(2)),('tasks','tarefas',lambda:self.navigate(3)),
                                   ('mail','e-mails',lambda:self.open_mail())]:
            shortcut=QPushButton(title);shortcut.setObjectName('quickAction');shortcut.setCursor(Qt.PointingHandCursor)
            shortcut.setStyleSheet('QPushButton { background:#14131E; border:1px solid #373244; border-radius:12px; color:#F1F0F7; font-size:12px; padding:0; min-height:44px; max-height:44px; }'
                                   'QPushButton:hover { border-color:#A78BFA; }')
            shortcut.clicked.connect(callback);row.addWidget(shortcut);self.compact_shortcuts[key]=(shortcut,title)
        self.compact_bar.hide()
        self.sync_compact()
        self.composer.raise_();self.intro.raise_();self.control_bar.raise_()

    def set_compact(self,on):
        """Janela de 420×640 no segundo monitor (ou no canto deste) e volta ao tamanho de antes."""
        w=self.window
        if on==self.compact or w.isFullScreen():
            self.sync_compact();return
        self.compact=on
        if on:
            if w.isMaximized():w.showNormal()
            self._normal_geometry=w.geometry()
            self.setMinimumSize(380,520);w.setMinimumSize(380,520)
            from PySide6.QtGui import QGuiApplication
            primary=QGuiApplication.primaryScreen()
            screen=next((s for s in QGuiApplication.screens() if s is not primary),w.screen())
            area=screen.availableGeometry()
            w.resize(420,min(640,area.height()-48));w.move(area.right()-420-24,area.top()+24)
        else:
            area=w.screen().availableGeometry()
            self.setMinimumSize(960,640);w.setMinimumSize(min(960,area.width()),min(640,area.height()))
            if self._normal_geometry is not None:w.setGeometry(self._normal_geometry)
        self.sync_compact();self._arrange_scene()

    def sync_compact(self):
        on=self.compact
        title='Voltar ao tamanho normal' if on else 'Modo compacto'
        self.compact_button.setChecked(on);self.compact_button.setIcon(icon(9 if on else 10))
        self.compact_button.setToolTip(title);self.compact_button.setAccessibleName(title)
        for widget in (self.organize_button,self.search,self.status_pill,self.fullscreen_button,self.header_controls['Buscar'],self.nav):
            widget.setVisible(not on)
        if on:self.clock.setVisible(False)
        self.compact_bar.setVisible(on and self.active and not self.workspace.visible_keys())

    def _rail(self):
        return 0 if self.compact else self.nav.width()

    def toggle_navigation(self):
        self.nav_expanded=not self.nav_expanded;self._update_navigation();QTimer.singleShot(0,self._arrange_scene)

    def sync_full_screen(self,full):
        title='Sair da tela cheia' if full else 'Tela cheia'
        self.fullscreen_button.setChecked(full);self.fullscreen_button.setIcon(icon(10 if full else 9))
        self.fullscreen_button.setToolTip(title+' (F11)');self.fullscreen_button.setAccessibleName(title)

    def _update_navigation(self):
        expanded=False   # layout gaveta: só ícones, com o nome na dica
        self.nav.setFixedWidth(64)
        self.nav_layout.setContentsMargins(6,16,6,16)
        for b,title in zip(self.nav_buttons,SECTION_TITLES):b.setText(title if expanded else '')
        self.mail_nav.setText('E-mails' if expanded else '')
        self.menu_toggle.setAccessibleName('Recolher navegação' if expanded else 'Expandir navegação')

    def _theme_history(self, *, classic=False):
        history=self.window._history
        bar=history.verticalScrollBar();position=bar.value()
        cursor=history.textCursor();anchor,point=cursor.anchor(),cursor.position()
        history.setHtml(history_html(history.toHtml(),classic=classic))
        cursor=history.textCursor();cursor.setPosition(min(anchor,history.document().characterCount()-1))
        cursor.setPosition(min(point,history.document().characterCount()-1),cursor.MoveMode.KeepAnchor)
        history.setTextCursor(cursor);bar.setValue(position)

    def toggle_sessions(self):
        panel=self.workspace.panels.get('sessions')
        if panel is not None and not panel.isHidden():
            panel.dismiss()
        else:
            from .agent_panel import AgentPanel
            def create():
                w=self.window
                view=AgentPanel(w._orchestrator,w._config,w._agent_config_writer,w)
                view.setWindowTitle('Conversas anteriores')
                history_page=view.tabs.widget(1)
                for index in (2,0):
                    hidden_page=view.tabs.widget(index)
                    view.tabs.removeTab(index);hidden_page.setParent(view);hidden_page.hide()
                view.tabs.setCurrentIndex(0)
                view.tabs.tabBar().hide()
                view.list.setAccessibleName('Sessões de conversa autorizadas')
                view.preview.setAccessibleName('Prévia da sessão selecionada')
                if not view.rows:
                    view.preview.setPlainText('Nenhuma conversa salva disponível. O histórico segue as permissões definidas em Capacidades e histórico.')
                history=history_page.layout()
                actions=history.takeAt(history.count()-1).layout()
                grid=QGridLayout();grid.setSpacing(8)
                while actions.count():
                    item=actions.takeAt(0);widget=item.widget()
                    if widget is not None:
                        index=grid.count();grid.addWidget(widget,index//2,index%2)
                history.addLayout(grid)
                view.tabs.updateGeometry();view.layout().invalidate();view.layout().activate()
                view.setMinimumWidth(0)
                view.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
                return view
            try:self.surfaces.open('sessions','Conversas anteriores',create,QSize(420,600))
            except (OSError,ValueError):
                self.sessions_toggle.setChecked(False)
                self.window._append('Therion','Não consegui abrir as conversas anteriores. Os registros foram preservados.')

    def scroll_to_latest(self):
        bar=self.window._history.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _resize_input(self):
        text=self.window._input
        lines=max(1,sum(max(1,text.document().findBlockByNumber(i).layout().lineCount())
                        for i in range(text.document().blockCount())))
        height=min(100,34+(lines-1)*21)
        if text.height()!=height:text.setFixedHeight(height)
        self._arrange_scene()

    def calendar_card(self, compact=False):
        card = QFrame(); card.setObjectName('card'); layout = QVBoxLayout(card); layout.setContentsMargins(16,16,16,16)
        row = QHBoxLayout(); row.addStretch()
        if compact:
            row.insertWidget(0,label('Agenda'))
            link=button('Ver tudo',lambda:self.navigate(2)); link.setObjectName('textLink'); row.addWidget(link)
            layout.addLayout(row)
        day = label('','muted'); layout.addWidget(day)
        day.setVisible(compact)
        listing = QListWidget(); listing.setAccessibleName('Compromissos da agenda'); layout.addWidget(listing,1)
        listing.setItemDelegate(AgendaDelegate(listing))
        if compact: listing.setObjectName('summaryList')
        self.calendar_lists.append((listing,day,compact))
        return card

    def tasks_card(self, compact=False):
        card = QFrame(); card.setObjectName('card'); layout = QVBoxLayout(card); layout.setContentsMargins(16,16,16,16)
        row = QHBoxLayout(); row.addWidget(label('Tarefas' if compact else 'Suas atividades','muted')); row.addStretch()
        if compact:
            link=button('Ver tudo',lambda:self.navigate(3)); link.setObjectName('textLink'); row.addWidget(link)
        row.addWidget(button('Nova tarefa',lambda:self.add_task(tabs.currentIndex())))
        layout.addLayout(row)
        task_status=label('','muted');task_status.hide();layout.addWidget(task_status);self.task_status_labels.append(task_status)
        tabs = QTabWidget(); lists = []
        for key,title in [('saved','Salvas'),('temporary','Da conversa')]:
            page = QWidget(); content = QVBoxLayout(page); content.setContentsMargins(0,4,0,0)
            if key == 'temporary':
                content.addWidget(label('Temporárias · apagadas ao limpar ou encerrar.','muted'))
            listing = QListWidget(); listing.setAccessibleName('Tarefas '+title)
            listing.setItemDelegate(TaskDelegate(listing,lambda item,k=key:self.toggle_task(k,item)))
            if compact: listing.setObjectName('summaryList')
            listing.itemDoubleClicked.connect(lambda item,k=key:self.toggle_task(k,item))
            content.addWidget(listing,1); lists.append(listing); tabs.addTab(page,title)
        layout.addWidget(tabs,1)
        change = button('Concluir / reabrir',lambda:self.toggle_task('saved' if tabs.currentIndex()==0 else 'temporary', lists[tabs.currentIndex()].currentItem()))
        change.setObjectName('textLink')
        layout.addWidget(change)
        self.task_tabs.append((tabs,lists,compact))
        return card

    def _locate(self, layout, widget):
        if not layout:
            return None
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.widget() is widget:
                return layout,index
            found = self._locate(item.layout() or (item.widget().layout() if item.widget() else None),widget)
            if found:
                return found
        return None

    def attach_controls(self):
        if self.saved_locations:
            return
        w = self.window
        groups = [
            (self.history_slot,['_history']), (self.clear_slot,['_clear_button']),
            (self.agent_slot,['_agent_button','_autonomy_button']),
            (self.details_slot,['_agent_details_button','_agent_details_view']),
            (self.confirm_slot,['_confirm_panel']),
            (self.control_slot,['_conversation_label','_workflow_label','_workflow_cancel_button']),
            (self.listen_slot,['_listen_button']),
            (self.diagnostic_slot,['_preparation_label']),
            (self.input_slot,['_input','_conversation_button','_stop_speech_button','_voice_button','_send_button']),
            (self.diagnostic_slot,['_voice_provider_notice']),
        ]
        # Localizar todos antes de remover para preservar os índices originais.
        for target,names in groups:
            for name in names:
                widget = getattr(w,name)
                location = self._locate(self.classic.layout(),widget)
                if location:
                    self.saved_locations.append((*location,widget,widget.isHidden(),target))
        for original,index,widget,hidden,target in self.saved_locations:
            original.removeWidget(widget); target.addWidget(widget)
            widget.setVisible(not hidden)
        self._input_height = w._input.maximumHeight()
        self._input_limits=(w._input.minimumSize(),w._input.maximumSize())
        self._history_name=w._history.objectName()
        self._theme_history()
        self._control_appearance=[(widget,widget.objectName(),widget.accessibleName()) for widget in
            (w._conversation_button,w._listen_button,w._stop_speech_button,w._send_button,w._voice_button)]
        w._history.setObjectName('conversationHistory')
        w._history.setAccessibleName('Histórico da conversa atual')
        w._input.setFixedHeight(34)
        w._input.installEventFilter(self)
        w._input.document().contentsChanged.connect(self._resize_input)
        self.composer.setProperty('focused',w._input.hasFocus())
        # Voz dentro do campo: conversa contínua, parar fala (só enquanto fala) e microfone.
        w._conversation_button.setObjectName('composerAction');w._stop_speech_button.setObjectName('composerStop')
        w._listen_button.setObjectName('textLink')
        w._input.setPlaceholderText('Fale com o Therion…')
        w._workflow_cancel_button.setText('Parar tarefa')
        w._send_button.setAccessibleName('Enviar mensagem');w._voice_button.setAccessibleName('Falar por voz')
        self.glyph_skins=[GlyphSkin(w._voice_button,'M9 4a3 3 0 0 1 6 0v8a3 3 0 0 1-6 0zM6 10v2a6 6 0 0 0 12 0v-2M12 18v4M8 22h8'),
                          GlyphSkin(w._send_button,'M22 2L9 15M22 2l-7 20-4-9-9-4z',send=True)]

    def detach_controls(self):
        # A interface clássica mantém rótulos e botões de voz sempre visíveis.
        for name in ('_conversation_label','_workflow_label','_listen_button','_stop_speech_button'):
            widget=getattr(self.window,name,None)
            if widget is not None:widget.show()
        self.window._input.removeEventFilter(self)
        try:self.window._input.document().contentsChanged.disconnect(self._resize_input)
        except (RuntimeError,TypeError):pass
        for skin in self.glyph_skins:skin.detach()
        self.glyph_skins.clear()
        for original,index,widget,hidden,target in sorted(self.saved_locations,key=lambda row:row[1]):
            current_hidden = widget.isHidden()
            target.removeWidget(widget); original.insertWidget(index,widget)
            widget.setVisible(not current_hidden)
        self.saved_locations.clear()
        self.window._history.setObjectName(self._history_name)
        self._theme_history(classic=True)
        for widget,name,accessible in self._control_appearance:
            widget.setObjectName(name);widget.setAccessibleName(accessible)
        self.window._input.setMinimumSize(self._input_limits[0]);self.window._input.setMaximumSize(self._input_limits[1])
        self.window._input.setMaximumHeight(self._input_height)

    def activate(self, active):
        self.active = active
        self.mailbox.activate(active)
        if active:
            self.window._dashboard_scroll.setStyleSheet('''
                QScrollArea { border:0; background:#09090F; }
                QScrollBar:vertical { background:#09090F; width:6px; }
                QScrollBar:horizontal { background:#09090F; height:6px; }
                QScrollBar::handle:vertical { background:rgba(82,51,159,140); border-radius:3px; min-height:22px; }
                QScrollBar::handle:horizontal { background:rgba(82,51,159,140); border-radius:3px; min-width:22px; }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
                QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
                QAbstractScrollArea::corner { background:#09090F; }
            ''')
            self.timer.start(); self.refresh_timer.start(); self.refresh_settings()
            self.refresh('calendar'); self.refresh('tasks'); self.probe_stt()
        else:
            self.orb_transition.stop()
            self.timer.stop(); self.refresh_timer.stop()
            self.workspace.hide_all()
            for worker in self.workers.values():
                worker.token.cancel()
            for key in self.epochs:
                self.epochs[key] += 1
        self.constellation.set_active(active and not self.window.isMinimized())
        QTimer.singleShot(0,self._arrange_scene)

    def navigate(self, index):
        if not 0<=index<len(SECTION_KEYS): return
        if index==2:self.set_calendar_compact(False)
        first_open=index!=0 and not self.workspace.panels[SECTION_KEYS[index]].positioned
        panel=self.workspace.panels.get(SECTION_KEYS[index])
        if panel is not None and panel.window_state=='open' and not panel.isHidden():
            panel.dismiss();return   # clicar de novo no mesmo botão fecha
        if index==0: self.workspace.hide_all()
        else: self.workspace.open(SECTION_KEYS[index])
        self._select_navigation(index)
        self.constellation.set_active(self.active and not self.window.isMinimized())
        if index==2: self.refresh('calendar')
        if index==3: self.refresh('tasks')
        if index==4:
            roots = getattr(self.window._orchestrator,'_knowledge_read_roots',())
            self.knowledge_info.setText('\n'.join('●  '+Path(root).name+' · acesso autorizado' for root in roots) if roots else 'Nenhuma fonte autorizada nesta sessão.')
            self.knowledge_paths.setText('\n'.join(map(str,roots)))
        if index==6 and first_open: self.refresh_settings()

    def _select_navigation(self,index):
        for i,b in enumerate(self.nav_buttons):
            b.setChecked(i==index)
            b.setIcon(icon(i,i==index))

    def _workspace_changed(self,key):
        self._select_navigation(1 if key=='sessions' else -1 if key=='mail' else SECTION_KEYS.index(key) if key in SECTION_KEYS else (6 if key else 0))
        if hasattr(self,'mail_button'):
            self.mail_button.setChecked(key=='mail');self.mail_button.setIcon(icon(7,'mail' in self.workspace.visible_keys()))
        for kind,launcher in self.activity_buttons.items():
            opened=kind in self.workspace.visible_keys()
            launcher.setChecked(opened)
            launcher.setIcon(icon(2 if kind=='calendar' else 3,opened))
        if hasattr(self,'sessions_toggle'):
            panel=self.workspace.panels.get('sessions')
            self.sessions_toggle.setChecked(bool(panel and not panel.isHidden()))
        self._sync_home_copy()
        for i,b in enumerate(self.nav_buttons):
            panel=self.workspace.panels.get(SECTION_KEYS[i]);opened=bool(panel and panel.window_state=='open' and not panel.isHidden())
            if b.property('windowOpen')!=opened:
                b.setProperty('windowOpen',opened);b.style().unpolish(b);b.style().polish(b)
        mail=self.workspace.panels.get('mail');self.mail_nav.setChecked(key=='mail')
        self.mail_nav.setProperty('windowOpen',bool(mail and mail.window_state=='open' and not mail.isHidden()))
        self.mail_nav.style().unpolish(self.mail_nav);self.mail_nav.style().polish(self.mail_nav)
        self._arrange_scene()
        # Só uma confirmação pendente tem prioridade sobre a janela ativa.
        self._arrange_confirmations()

    def _sync_home_copy(self):
        # O vidro revela a cena, sem misturar textos de duas superfícies.
        # Reter o espaço conserva o enquadramento e o conteúdo da resposta.
        opened=self.workspace.visible_keys()
        visible=not any(key!='calendar' or not self.calendar_compact for key in opened)
        visible=visible and (self.width()>=1280 or not opened)
        # Layout gaveta: a última resposta é a legenda sob a orbe e fica visível com a gaveta aberta se couber.
        caption_room=not opened or self.center_region()[1]>=420
        for widget in self.home_copy: widget.setVisible(caption_room and bool(self._response))
        if hasattr(self,'glance'):
            # O resumo do dia agora são os números na barra da direita.
            self.glance.setVisible(False)
        if hasattr(self,'quick_bar'):
            home=self.active and not opened
            # A saudação ocupa o lugar da legenda enquanto ainda não há resposta.
            for widget in (self.greeting_kicker,self.greeting_title):widget.setVisible(home and not self._response)
            self.quick_bar.setVisible(home and self._quick_room)
            self.compact_bar.setVisible(home and self.compact)
            for action in self.quick_actions:action.setEnabled(not self.window._processing)
        # A saudação sob a orbe substitui a frase antiga sobre o campo.
        self.intro.setVisible(False)

    def toggle_activity(self,key):
        if key=='calendar':self.set_calendar_compact(True)
        self.workspace.toggle(key)
        if key in self.workspace.visible_keys(): self.refresh(key)
        if key=='calendar':self.mailbox.poll(force=True)

    def toggle_mail(self):
        panel=self.workspace.panels['mail']
        if panel.window_state=='open' and not panel.isHidden():panel.dismiss()
        else:self.open_mail()

    def open_mail(self,identifier=''):
        self.mailbox.show();self.workspace.open('mail');self.mailbox.opened(identifier)

    def open_briefing(self,payload=None):
        if payload and (payload.get('session')!=self.window._orchestrator.session_id or payload.get('account')!=self.window._orchestrator._mailbox.identity()):return
        if not getattr(self,'briefing_open',False):
            self.briefing_open=True;self.day=self.window._orchestrator._calendar_now().date();self.set_calendar_compact(False)
            for kind in ('calendar','tasks'):
                self.epochs[kind]+=1
                if kind in self.workers:self.workers[kind].token.cancel()
                self.dirty.discard(kind)
                self.workspace.open(kind)
            self.open_mail();self.workspace.organize(['mail','calendar'])
            self.render_calendar(dict(state='loading',items=[],message='Preparando sua agenda…'),self.day)
            self.render_tasks(dict(state='loading',message='Consultando suas tarefas…'))
        if payload:
            for kind,result in payload['parts'].items():self.briefing_part(dict(kind=kind,result=result))
            self.briefing_open=False

    def briefing_part(self,payload):
        kind,result=payload['kind'],payload['result']
        if kind=='calendar':self.render_calendar(result,self.day)
        elif kind=='tasks':self.render_tasks(result)
        else:
            if result.get('page'):
                self.mailbox._render_page(result['page'],dict(page=None,force=False,query='in:inbox'))
            text=('Acompanhamento iniciado neste panorama.' if result.get('first') else
                  ('Pelo menos ' if not result.get('complete') else '')+str(result.get('count',0))+' recebidos desde o último panorama.') if result.get('state') in {'ready','partial'} else result.get('message','Gmail indisponível.')
            self.mailbox.briefing_note.setText(text)
            self.mailbox.briefing_note.setVisible(not self.mailbox.compact or not self.mailbox.list_page.isHidden())

    def set_calendar_compact(self,compact):
        if compact!=self.calendar_compact:
            self.calendar_compact=compact
            panel=self.workspace.panels['calendar']
            if not panel.manually_placed:panel.positioned=False
        self.calendar_dates.setVisible(not compact);self.date_label.setVisible(not compact)
        compact_height=max(420,min(500,self.height()*.55)) if self.mailbox.account else max(380,min(440,self.height()*.42))
        self.workspace.preferred['calendar']=QSize(round(max(390,min(540,self.width()*.27))),round(compact_height)) if compact else QSize(500,520)
        self.workspace.anchors['calendar']='bottom-right' if compact else 'top'
        today=self.window._orchestrator._calendar_now().date()
        self.workspace.panels['calendar'].title_bar.label.setText(('Agenda de hoje' if self.day==today else 'Agenda · '+self.day.strftime('%d/%m')) if compact else 'Agenda')
        self.calendar_page_layout.setContentsMargins(12,4,12,8) if compact else self.calendar_page_layout.setContentsMargins(24,20,24,20)

    def open_search(self):
        self.navigate(1);self.search.setFocus();self.search.selectAll()

    def wide_home(self):
        return self.width()>=1200

    def side_column(self):
        # Layout gaveta: a faixa da direita, ao lado da barra, é onde a gaveta abre.
        width=340
        return QRect(self.width()-self.nav.width()-12-width,72,width,self.height()-72-24)

    @property
    def tile_reserve(self):
        # Painéis lado a lado param antes de cobrir a orbe e o campo de digitar.
        composer=getattr(self,'composer',None)
        need=composer.minimumSizeHint().width()+72 if composer is not None else 0
        return 0 if self.compact else max(380,need)

    def drawer_width(self,key):
        return self.drawer_rect(key).width()

    def drawer_rect(self,key=None):
        """Gaveta colada na barra da direita; e-mail e painel com detalhe pedem mais largura."""
        workspace=getattr(self,'workspace',None)
        if key is None:key=workspace.order[-1] if workspace is not None and workspace.order else ''
        wide=key=='mail' or bool(workspace is not None and workspace._return_to.get(key))
        if self.compact:
            # Compacto: a seção cobre a orbe e para acima do campo, que continua à mão.
            composer=getattr(self,'composer',None)
            bottom=composer.y()-12 if composer is not None and composer.y()>360 else self.height()-8
            return QRect(8,60,max(300,self.width()-16),max(240,bottom-60))
        right=self.width()-self.nav.width()-12
        # E-mail abaixo de 900 px vira lista ou leitura; 920 mantém as duas lado a lado quando cabe.
        width=max(920 if key=='mail' else 360,min(1100 if wide else 560,round(self.width()*(.62 if wide else .36))))
        width=min(width,max(300,right-24))
        return QRect(right-width,72,width,max(240,self.height()-72-24))

    def center_region(self):
        # Entre a borda esquerda e a barra (ou a gaveta aberta): orbe, legenda e campo ficam centrados aí.
        right=self.width()-self._rail()-24
        workspace=getattr(self,'workspace',None)
        if workspace is not None and workspace.visible_keys() and not self.compact:
            right=min(right,min(self._panel_left(workspace.panels[key]) for key in workspace.visible_keys())-24)
        return 24,max(200,right-24)

    @staticmethod
    def _panel_left(panel):
        # Durante a entrada deslizando, vale a posição final do painel.
        slide=getattr(panel,'_slide',None)
        return slide.endValue().x() if slide is not None and slide.state()==slide.State.Running else panel.x()

    def workspace_rect(self):
        # Área onde as janelas podem ficar: abaixo do cabeçalho e à esquerda da barra.
        nav=getattr(self,'nav',None)
        return self.rect().adjusted(8,56 if self.compact else 64,-((self._rail() if nav is not None else 0)+8),-8)

    def panel_opening_rect(self):
        return self.drawer_rect()

    def calendar_bounds(self):
        rect=self.panel_opening_rect()
        if self.calendar_compact:
            rect.setBottom(round(self.height()*.755))
        return rect

    def _arrange_confirmations(self):
        if not hasattr(self,'confirm_overlay'):return
        visible=not self.window._confirm_panel.isHidden() or not self.proposal_bar.isHidden()
        self.confirm_overlay.setVisible(visible)
        if visible:
            width=min(900,self.width()-32)
            height=max(self.confirm_overlay.minimumSizeHint().height(),self.confirm_overlay.sizeHint().height())
            self.confirm_overlay.setGeometry((self.width()-width)//2,104,width,height)
            self.confirm_overlay.raise_()

    def _arrange_scene(self):
        if not isValid(self) or not hasattr(self,'workspace'): return
        self.workspace.reflow()   # posiciona os painéis antes de a orbe medir o espaço livre
        self.constellation.setGeometry(self.rect())
        self.constellation.lower()
        opened=self.workspace.visible_keys()
        # A orbe fica no centro do espaço livre; com a gaveta aberta ela desliza para a esquerda.
        left,region=self.center_region()
        side=max(160,min(round(self.height()*.46),region-48))
        if self.compact:side=max(140,min(round(self.height()*.33),region-40))
        if opened and region<220:
            brand=self.brand_label.mapTo(self,QPoint(self.brand_label.width(),0)).x()
            target=QRect(max(left,brand+12),4,48,48)   # sem espaço ao lado da gaveta: orbe pequena depois do nome
        else:
            target=QRect(left+(region-side)//2,64 if self.compact else 88,side,side)
        anchor=self.hero_container.mapFrom(self,target.topLeft())
        self.hero_space.setGeometry(QRect(anchor,target.size()))
        attention=.45 if opened else 1.
        self.workspace_presentation=WorkspacePresentation(self.workspace.order[-1] if self.workspace.order else '',tuple(opened),tuple(target.getRect()),attention)
        self.constellation.set_attention(attention)
        if self.reduced.isChecked():
            self.orb_transition.stop();self.constellation.set_focus_rect(target)
        if self._orb_target!=target:
            self._orb_target=QRect(target);self.orb_transition.stop()
            if self.reduced.isChecked() or self.constellation.focus_rect is None:
                self.constellation.set_focus_rect(target)
            else:
                self.orb_transition.setStartValue(QRectF(self.constellation.focus_rect));self.orb_transition.setEndValue(QRectF(target));self.orb_transition.start()
        left,available=self.center_region()
        width=min(880,available)
        x=left+(available-width)//2
        self.composer.setFixedWidth(width)
        input_height=self.window._input.height() if self.saved_locations else 34
        composer_height=input_height+20
        control_height=max(36,self.control_slot.sizeHint().height())
        composer_y=self.height()-24-control_height-8-composer_height
        self.composer.setGeometry(x,composer_y,width,composer_height)
        self.intro.setGeometry(x,composer_y-64,width,40)
        self.control_bar.setGeometry(left,composer_y+composer_height+8,available,control_height)
        # Saudação logo abaixo da orbe da tela inicial; atalhos logo acima do campo.
        self.greeting_kicker.setGeometry(left,target.bottom()+12,available,22)
        self.greeting_title.setGeometry(left,target.bottom()+36,available,36)
        self.quick_bar.setGeometry(left,composer_y-56,available,40)
        # Legenda: a última resposta logo abaixo da orbe, sem passar por cima do campo.
        caption_width=min(640,available)
        caption_height=128 if self.compact else 152
        caption_y=min(target.bottom()+12,composer_y-8-(60 if self.compact else 0)-caption_height)
        self.response_preview.setFixedWidth(caption_width)
        self.response_preview.setGeometry(left+(available-caption_width)//2,caption_y,caption_width,caption_height)
        self.last_response.setFixedHeight(caption_height-56);self.last_response.setStyleSheet('font-size:14px;')
        self.history_link.setText('Ver conversa completa' if caption_width>=560 else 'Ver tudo')
        below=caption_y+caption_height if self._response else target.bottom()+80
        self._quick_room=not self.compact and composer_y-56>=below+8
        self.compact_bar.setGeometry(left,composer_y-60,available,52)
        self._sync_home_copy()
        for widget in (self.glance,self.response_preview,self.greeting_kicker,self.greeting_title,self.quick_bar,self.compact_bar):widget.raise_()
        self._place_badges()
        self.activity_dock.setGeometry(self.width()-62,round(self.height()*.18),44,156)
        self.activity_dock.hide()
        self.workspace.reflow()
        self._arrange_confirmations()
        if hasattr(self,'surfaces'):self.surfaces.reflow()

    def eventFilter(self,watched,event):
        if watched is getattr(self.window,'_input',None) and event.type() in (QEvent.FocusIn,QEvent.FocusOut):
            self.composer.setProperty('focused',event.type()==QEvent.FocusIn)
            self.composer.style().unpolish(self.composer);self.composer.style().polish(self.composer);self.composer.update()
        if watched is getattr(self,'control_bar',None) and event.type()==QEvent.LayoutRequest:
            QTimer.singleShot(0,self._arrange_scene)
        if watched is getattr(self,'hero_space',None) and event.type() in (QEvent.Resize,QEvent.Move):
            QTimer.singleShot(0,self._arrange_scene)
        return super().eventFilter(watched,event)

    def change_day(self, delta):
        self.day = self.window._orchestrator._calendar_now().date() if delta==0 else self.day+timedelta(days=delta)
        self.epochs['calendar'] += 1
        self.render_calendar({'state':'loading','items':[],'message':'Consultando agenda…'},self.day)
        self.refresh('calendar')

    def refresh_visible(self):
        if not self.window.isMinimized() and 'calendar' in self.workspace.visible_keys():
            self.refresh('calendar')

    def refresh(self, kind):
        if not self.active:
            return
        if kind in self.workers:
            self.dirty.add(kind)
            return
        self.epochs[kind] += 1
        epoch, identity, day = self.epochs[kind],self.source.identity(),self.day
        if kind=='calendar':
            self.render_calendar({'state':'loading','items':[],'message':'Consultando agenda…'}, day)
        else:
            for tabs,lists,compact in self.task_tabs:
                for listing in lists:
                    listing.clear(); listing.addItem('Consultando tarefas…')
        fn = (lambda token:self.source.calendar(day,token)) if kind=='calendar' else self.source.tasks
        worker = ReadWorker(fn,self); self.workers[kind] = worker
        worker.finished.connect(lambda:self.read_finished(kind,worker,epoch,identity,day))
        worker.start()

    def read_finished(self, kind, worker, epoch, identity, day):
        if not isValid(self) or self.workers.get(kind) is not worker:
            return
        self.workers.pop(kind)
        # A primeira leitura pode inicializar o store; a identidade da sessão/conta
        # continua sendo a mesma e não se vincula ao endereço do objeto Python.
        current = self.source.identity()
        valid = (self.active and not worker.token.cancelled and epoch==self.epochs[kind]
                 and identity[:2]==current[:2] and identity[3:]==current[3:]
                 and (kind!='calendar' or day==self.day))
        if valid:
            if kind=='calendar': self.render_calendar(worker.result,day)
            else: self.render_tasks(worker.result)
        elif self.active:
            stale={'state':'stale','items':[],'message':'O contexto mudou. Atualize para consultar novamente.'}
            if kind=='calendar': self.render_calendar(stale,self.day)
            else: self.render_tasks(stale)
        worker.deleteLater()
        if kind in self.dirty:
            self.dirty.discard(kind)
            self.refresh(kind)

    def render_calendar(self, result, day):
        if result.get('state') in {'disconnected','disabled','stale'} and hasattr(self,'_calendar_snapshot'):del self._calendar_snapshot
        if result.get('state')=='ready':self._calendar_snapshot=(self.source.identity()[:2],day,deepcopy(result))
        elif hasattr(self,'_calendar_snapshot') and self._calendar_snapshot[:2]==(self.source.identity()[:2],day):
            result=dict(result,items=self._calendar_snapshot[2].get('items',[]))
        state=result.get('state')
        if day==self.window._orchestrator._calendar_now().date():self._calendar_health=state
        self.calendar_connect.setVisible(state=='disconnected')
        self.calendar_connection.setText(result.get('message') or 'Consultando agenda…' if state=='loading' else result.get('message',''))
        self.calendar_connection.setVisible(state!='ready')
        if hasattr(self,'activity_buttons'):
            count=str(len(result.get('items',[]))) if result.get('state')=='ready' else '—'
            self.activity_buttons['calendar'].setText('Agenda · '+count)
            self.activity_buttons['calendar'].setToolTip('Abrir agenda · '+day.strftime('%d/%m/%Y'))
        self.date_label.setText(day.strftime('%d/%m/%Y'))
        if hasattr(self,'glance'):
            now=self.window._orchestrator._calendar_now()
            if day==now.date():
                self.glance.render_calendar(result,now)
                self.set_badge('calendar',len(result.get('items',[])) if result.get('state')=='ready' else 0)
        for listing,day_label,compact in self.calendar_lists:
            # O cartão inicial sempre identifica a data selecionada.
            day_label.setText(day.strftime('%d/%m/%Y'))
            listing.clear()
            for row in result.get('items',[])[:4 if compact else None]:
                item=QListWidgetItem(row['time']+'  '+row['title']);item.setData(Qt.UserRole,row)
                item.setToolTip(row['time']+' · '+row['title']);listing.addItem(item)
            if not result.get('items'):
                listing.addItem(result.get('message') or 'Nenhum compromisso neste dia.')

    def render_tasks(self, result):
        if result.get('state') in {'disconnected','disabled','stale'} and hasattr(self,'_tasks_snapshot'):del self._tasks_snapshot
        if result.get('state')=='ready':self._tasks_snapshot=(self.source.identity()[:2],deepcopy(result))
        elif hasattr(self,'_tasks_snapshot') and self._tasks_snapshot[0]==self.source.identity()[:2]:
            result=dict(result,saved=self._tasks_snapshot[1].get('saved',[]),temporary=self._tasks_snapshot[1].get('temporary',[]))
        self.task_rows = {'saved':result.get('saved',[]),'temporary':result.get('temporary',[])}
        for status in self.task_status_labels:
            status.setText(result.get('message') or 'Consultando tarefas…');status.setVisible(result.get('state')!='ready')
        if hasattr(self,'activity_buttons'):
            pending=sum(row.get('state')!='completed' for row in self.task_rows['saved'])
            pending+=sum(not row['completed'] for row in self.task_rows['temporary'])
            self.activity_buttons['tasks'].setText('Tarefas · '+(str(pending) if result.get('state')=='ready' else '—'))
            if hasattr(self,'glance'):
                self.glance.render_tasks(result,pending)
                self.set_badge('tasks',pending if result.get('state')=='ready' else 0)
        for tabs,lists,compact in self.task_tabs:
            for key,listing in zip(('saved','temporary'),lists):
                listing.clear()
                rows = self.task_rows[key]
                for row in rows[:4 if compact else None]:
                    completed = row.get('state')=='completed' if key=='saved' else row['completed']
                    item = QListWidgetItem(('✓  ' if completed else '○  ')+row['title'])
                    item.setData(Qt.UserRole,row); listing.addItem(item)
                if not rows:
                    listing.addItem(result.get('message') if key=='saved' and result.get('state')!='ready'
                                    else 'Nenhuma tarefa nesta lista.')

    def action(self, operation, arguments):
        w = self.window
        # O turno que espera a aprovação segura _processing; aprovar ou descartar a proposta é o que o destrava.
        waiting = operation in {'approve','discard'} and self._turn_awaits_approval()
        if (w._processing and not waiting) or self.action_worker or w._quit_requested:
            return
        if w._pending_plan is not None:
            return
        if not waiting:
            w._set_processing(True); w._update_orbe('executing')
        worker = ReadWorker(lambda token:self.source.action(operation,arguments,token),self)
        worker.turn_reports = waiting
        self.action_worker = worker
        w._poll_workflow_progress()
        worker.finished.connect(lambda:self.action_finished(worker)); worker.start()

    def _turn_awaits_approval(self):
        runtime = getattr(self.window._orchestrator,'_agent_runtime',None)
        return getattr(runtime,'waiting_confirmation',False) is True

    def action_finished(self, worker):
        self.action_worker = None
        if worker.turn_reports:
            # O turno em espera recebe o recibo, publica a resposta e encerra o estado ocupado.
            worker.deleteLater(); return
        result = worker.result
        self.window._set_processing(False)
        self.window._poll_workflow_progress()
        message = result.message if isinstance(result,ToolResult) else 'Não consegui concluir a operação. Confira as propostas e os recibos antes de tentar novamente.'
        self.window._append('Therion',message or 'Operação concluída.')
        state = result.status if isinstance(result,ToolResult) else 'uncertain'
        self.window._update_orbe('error' if state in {'failed','blocked','unavailable'} else state)
        if not self.window._quit_requested:
            self.refresh('tasks')
            if state=='success': self.refresh('calendar')
        worker.deleteLater()
        if self.window._quit_requested:
            self.window._quit_application()

    def add_task(self, tab):
        if self.window._processing:
            return
        title,accepted = QInputDialog.getText(self,'Adicionar tarefa','Título da tarefa:')
        if not accepted or not title.strip():
            return
        self.action('session_add' if tab else 'prepare_task',
                    {'title':title.strip()} if tab else {'title':title.strip(),'source_id':'user:current','due':''})

    def toggle_task(self, key, item):
        row = item.data(Qt.UserRole) if item else None
        if not row:
            return
        if key=='temporary':
            self.action('session_state',{'id':row['id'],'completed':not row['completed']})
        else:
            self.action('prepare_task_state',{'id':row['id'],'state':'pending' if row['state']=='completed' else 'completed'})

    def approve_proposal(self):
        if self._proposal:
            self.action('approve',{'id':self._proposal.id,'digest':self._proposal.digest})

    def discard_proposal(self):
        if self._proposal:
            self.action('discard',{'id':self._proposal.id})

    def poll(self):
        w = self.window
        self.mailbox.poll()
        now=datetime.now().astimezone()
        clock=now.strftime('%d/%m/%Y   ·   %H:%M')
        if clock!=self._clock_value:
            self.clock.setText(clock);self._clock_value=clock;self.update_greeting()
            # A cada minuto, uma leitura curta do estado do Parakeet (sem efeitos).
            self.probe_stt()
        p = self.presentation
        speech = getattr(w,'_speech_output',None)
        if speech is not None:
            state = speech.state
            p.speech = 'synthesizing' if state=='playing' and not speech._playing else state
        capture = getattr(getattr(w,'_voice_pipeline',None),'_capture',None)
        p.intensity = (normalized_level(getattr(capture,'level',0.)) if p.capture=='recording'
                       else normalized_level(getattr(getattr(w,'_speech_output',None),'level',0.)))
        proposals = getattr(w._orchestrator,'_agent_proposals',None)
        rows = proposals.list() if proposals else []
        self._proposal = rows[0] if rows else None
        p.confirmation = w._pending_plan is not None or self._proposal is not None
        if not p.confirmation and p.interaction=='awaiting_confirmation':
            p.interaction='idle'
        self.proposal_bar.setVisible(self._proposal is not None and w._pending_plan is None)
        if self._proposal and self.proposal_text.toPlainText()!=self._proposal.preview:
            self.proposal_text.setPlainText(self._proposal.preview)
        free = (not w._processing or self._turn_awaits_approval()) and self.action_worker is None
        self.approve.setEnabled(free); self.discard.setEnabled(free)
        health=self.service_health()
        text=p.label
        if p.state=='idle' and not health['ai']:text='Pronto · IA desativada'
        self.status.setText(text);self.status.setToolTip(health['summary']);self.state_light.setToolTip(health['summary'])
        self.state_light.setAccessibleDescription(text+'. '+health['summary'].replace('\n','. '))
        pigment=('#FCA5A5' if p.state in {'error','uncertain'} else '#FCD34D' if p.confirmation
                 else '#B5B1C5' if p.state=='idle' and not health['ai'] else '#A78BFA')
        self._render_health(health)
        self._tidy_session_controls()
        self.state_light.setStyleSheet('color:'+pigment+';font-size:14px;')
        self.meter.set_level(p.state,p.intensity)
        self.constellation.set_visual(p.state,p.intensity)
        if p.state!=self._mini_state:   # confirmação e fala são lidas aqui; a mini orbe acompanha cada mudança
            self._mini_state=p.state
            sync=getattr(w,'_sync_mini_orb',None)
            if callable(sync):sync()
        pointer=self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(pointer) and w.isActiveWindow():
            self.constellation.set_scene_pointer(pointer.x()/max(1,self.width())*2-1,1-pointer.y()/max(1,self.height())*2)
        else:self.constellation.set_scene_pointer(0.,0.)
        self._arrange_confirmations()
        active = self.active and not w.isMinimized()
        renderer = self.constellation.renderer
        if renderer and renderer.timer.isActive()!=bool(active and not renderer.reduced and not renderer.disabled):
            self.constellation.set_active(active)
        if w._history.document().isEmpty() and self._response:
            self._response = ''; p.last_response = ''
            self.last_response.setPlainText('Como posso ajudar você?')
            self._sync_home_copy()

    HEALTH_WORDS={'ready':'conectada','disconnected':'desconectada','disabled':'desativada','error':'com falha',
                  'loading':'consultando…','stale':'desatualizada','partial':'resultado parcial','missing':'ainda não consultada'}

    def service_health(self):
        """Resumo honesto do que está ligado; lê apenas configuração e últimos estados já obtidos."""
        config=getattr(self.window,'_config',{}) or {}
        ai=config.get('ai',{}).get('enabled') is True;tts=config.get('tts',{}).get('enabled') is True
        model=str(config.get('ai',{}).get('model','')).strip()
        calendar=self.HEALTH_WORDS.get(getattr(self,'_calendar_health',''),'ainda não consultada')
        mail=self.HEALTH_WORDS.get(getattr(self,'_mail_health',''),'ainda não consultada').replace('conectada','conectado').replace('desconectada','desconectado').replace('desativada','desativado').replace('desatualizada','desatualizado')
        stt_expected=config.get('voice',{}).get('provider')=='parakeet_http'
        stt=getattr(self,'_stt_health',None) or {}
        stt_status=stt.get('status')
        stt_word=({'ready':'pronto','loading':'carregando','error':'falhou · '+str(stt.get('failure_type') or 'erro'),
                   'offline':'não respondeu'}.get(stt_status,'verificando…' if stt_expected else 'não usado'))
        lines=['Modelo local: '+(('ativado · '+model) if ai and model else 'ativado' if ai else 'desativado'),
               'Respostas faladas: '+('ativadas' if tts else 'desativadas'),
               'Transcrição Parakeet: '+stt_word,
               'Agenda: '+calendar,'Gmail: '+mail]
        mail_state=getattr(self,'_mail_health','')
        levels=dict(ai='ok' if ai else 'off',voice='ok' if tts else 'off',
            stt=('hidden' if not stt_expected else 'ok' if stt_status=='ready' else 'error' if stt_status in {'error','offline'} else 'warn'),
            mail=('ok' if mail_state=='ready' else 'error' if mail_state=='error' else 'warn' if mail_state in {'stale','loading','partial'} else 'off'))
        wake=(getattr(self.window,'_wake_state',None) or (lambda:None))()   # só nesta sessão: não lê nem grava a config
        levels['wake']={'on':'ok','off':'off','problem':'warn'}.get(wake,'hidden')
        words=dict(ai=lines[0],voice=lines[1],stt=lines[2],mail=lines[4],
            wake={'on':'Ouvindo o nome · clique para pausar','off':'Escuta do nome pausada · clique para religar',
                  'problem':'Microfone com problema · clique para tentar de novo'}.get(wake,''))
        return dict(ai=ai,tts=tts,summary='\n'.join(lines),levels=levels,words=words)

    HEALTH_COLORS={'ok':'#86EFAC','warn':'#FCD34D','error':'#FCA5A5','off':'#6E6A80'}

    def _render_health(self,health):
        for key,(dot,title) in self.health_dots.items():
            level=health['levels'][key]
            dot.setVisible(level!='hidden')
            if level=='hidden':continue
            # Em janelas estreitas ficam só os pontos; o nome segue no tooltip.
            markup='<span style="color:'+self.HEALTH_COLORS[level]+';">●</span>'+('&nbsp;'+title if self.width()>=1100 else '')
            if dot.text()!=markup:dot.setText(markup)
            dot.setToolTip(health['words'][key]);dot.setAccessibleName(health['words'][key])

    def probe_stt(self):
        # Leitura periódica apenas quando o perfil Parakeet está configurado.
        config=getattr(self.window,'_config',{}) or {}
        if not self.active or config.get('voice',{}).get('provider')!='parakeet_http':return
        if getattr(self,'_stt_probe',None) and self._stt_probe.is_alive():return
        def run():self._stt_health=read_stt_health()
        self._stt_probe=threading.Thread(target=run,name='therion-stt-health',daemon=True);self._stt_probe.start()

    def update_greeting(self):
        text=greeting_for(datetime.now().astimezone())+', SENHOR'
        if self.greeting_kicker.text()!=text:self.greeting_kicker.setText(text)

    def quick_command(self,text):
        # Igual a digitar o pedido: mesmo caminho do orquestrador e das confirmações.
        if self.window._processing:return
        draft=self.window._input.toPlainText()
        self.window._input.setPlainText(text);self.window._send_command()
        if not self.window._input.toPlainText():self.window._input.setPlainText(draft)

    def set_badge(self,key,count):
        self._badge_counts[key]=count;self._place_badges()
        if key in getattr(self,'compact_shortcuts',{}):
            shortcut,title=self.compact_shortcuts[key]
            shortcut.setText(f'{count}  {title}' if count else title)

    def _place_badges(self):
        if not hasattr(self,'nav_badges'):return
        for key,badge in self.nav_badges.items():
            owner=badge.parentWidget();count=self._badge_counts.get(key) or 0
            badge.setText(str(count) if count<100 else '99+')
            if owner.width()>=120:badge.setGeometry(owner.width()-38,(owner.height()-20)//2,28,20)
            else:badge.setGeometry(owner.width()-20,2,18,16)
            badge.setVisible(bool(self.active and count>0));badge.raise_()

    def _tidy_session_controls(self):
        # Controles de voz contextuais: só aparece o que pode ser usado agora.
        w=self.window
        for action in getattr(self,'quick_actions',()):
            if action.isEnabled()==bool(w._processing):action.setEnabled(not w._processing)
        if not self.saved_locations:return
        for name in ('_conversation_label','_workflow_label'):
            widget=getattr(w,name,None)
            if widget is not None and widget.isHidden()==bool(widget.text()):widget.setVisible(bool(widget.text()))
        for name in ('_listen_button','_stop_speech_button'):
            widget=getattr(w,name,None)
            if widget is not None and widget.isHidden()==widget.isEnabled():widget.setVisible(widget.isEnabled())

    def interaction(self, state):
        self.presentation.interaction = {'responding':'idle','success':'idle','cancelled':'idle'}.get(state,state)

    def response(self, sender, text):
        if sender!='Você':
            self._response = text; self.presentation.last_response = text
            # Identificadores técnicos continuam no histórico completo.
            self.last_response.setPlainText(re.sub(r'\[gmail:[^\]\n]+\]','',text).strip())
            self.last_response.setAlignment(Qt.AlignLeft);self._sync_home_copy()
        # Atualização solicitada depois de comandos, executada sem bloquear o chat.
        if sender!='Você' and self.active:
            if not getattr(self,'_skip_response_refresh',False):self.refresh('tasks')
            self._skip_response_refresh=False

    def command(self, text):
        if self.window._processing:
            return
        self.navigate(1)
        draft=self.window._input.toPlainText()
        self.window._input.setPlainText(text); self.window._send_command()
        if not self.window._input.toPlainText():self.window._input.setPlainText(draft)

    def search_history(self):
        self.navigate(1)
        self.window._history.moveCursor(self.window._history.textCursor().Start)
        found = self.window._history.find(self.search.text())
        self.search.setToolTip('Trecho encontrado.' if found else 'Nenhum trecho na conversa atual. Use Histórico autorizado para registros anteriores.')

    def search_knowledge(self):
        query = self.knowledge_query.text().strip()
        if query:
            self.command('busque nas notas '+query)

    def agent_tab(self, index):
        self.window._show_agent_panel(index=index)

    def open_agent(self,index=0):
        from .agent_panel import AgentPanel
        w=self.window
        panel=self.surfaces.open('capabilities','Capacidades e histórico',
            lambda:AgentPanel(w._orchestrator,w._config,w._agent_config_writer,w),QSize(840,680))
        w._agent_panel=panel
        panel.tabs.setCurrentIndex(index)
        return panel

    def open_autonomy(self):
        from .autonomy_panel import AutonomyPanel
        w=self.window
        panel=self.surfaces.open('autonomy','Autonomia',
            lambda:AutonomyPanel(w,w._autonomy_runtime,w._routine_service,w._procedure_memory),QSize(1080,730))
        w._autonomy_panel=panel
        return panel

    def procedures(self):
        if self.window._processing:return
        from .procedure_panel import ProcedurePanel
        host=self.window._orchestrator
        try:
            store=host._get_agent_store()
            return self.surfaces.open('procedures','Procedimentos técnicos',lambda:ProcedurePanel(store,self.window),QSize(900,700))
        except (OSError,ValueError):
            self.window._append('Therion','Não consegui abrir os procedimentos. Os registros existentes foram preservados.')

    def calendar_help(self):
        if self.calendar_auth is not None or self.window._processing:
            return
        root = Path(os.environ.get('APPDATA',str(Path.home()/'.config')))/'Therion'
        credentials = root/'credentials.json'
        if not credentials.is_file():
            selected,_ = QFileDialog.getOpenFileName(self,'Selecionar credenciais OAuth do Google Calendar','','JSON (*.json)')
            if not selected:
                return
            try:
                raw = Path(selected).read_bytes()
                if len(raw)>1000000 or not isinstance(json.loads(raw).get('installed'),dict):
                    raise ValueError('Credenciais incompatíveis.')
                root.mkdir(parents=True,exist_ok=True)
                # Não substitui um arquivo que tenha surgido durante a seleção.
                with credentials.open('xb') as stream: stream.write(raw)
            except Exception:
                self.calendar_connection.setText('Selecione um arquivo de credenciais OAuth do tipo aplicativo para computador.'); return
        self.auth_cancelled=False
        process=QProcess(self); self.calendar_auth=process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        process.finished.connect(lambda code,status:self.calendar_connected(process,code))
        process.errorOccurred.connect(lambda error:self.calendar_auth_failed(process))
        process.start(sys.executable,[str(Path(__file__).resolve().parents[2]/'scripts'/'connect-calendar.py')])
        self.calendar_connection.setText('Conclua a autorização no navegador. Nenhum compromisso será criado.')
        QTimer.singleShot(180000,lambda:process.kill() if self.calendar_auth is process and process.state()!=QProcess.NotRunning else None)

    def calendar_auth_failed(self, process):
        self.calendar_connection.setText('Não foi possível iniciar a conexão da agenda.')
        if self.calendar_auth is process and process.state()==QProcess.NotRunning:
            self.calendar_auth=None
            process.deleteLater()

    def calendar_connected(self, process, code):
        if self.calendar_auth is not process:
            return
        self.calendar_auth=None
        process.deleteLater()
        if self.auth_cancelled or self.window._quit_requested:
            return
        if code!=0:
            self.calendar_connection.setText('Conexão não concluída. Confira as credenciais e tente novamente.'); return
        try:
            config=deepcopy(self.window._agent_config_loader())
            config.setdefault('calendar',{})['enabled']=True
            self.window._agent_config_writer(config)
            self.window._config['calendar']=deepcopy(config['calendar'])
            self.window._orchestrator.calendar_adapter=self.window._build_calendar_adapter()
        except Exception:
            self.calendar_connection.setText('Conta autorizada, mas não consegui habilitar a agenda. Confira os ajustes.'); return
        self.calendar_connection.setText('Agenda conectada. Nenhum compromisso foi criado.')
        self.epochs['calendar']+=1; self.refresh('calendar')

    def refresh_settings(self):
        config = self.window._config
        ui = config.get('ui',{})
        self.quality.setCurrentIndex(max(0,self.quality.findData(ui.get('graphics_quality','auto'))))
        self.reduced.setChecked(ui.get('reduced_motion') is True)
        renderer = self.constellation.renderer
        if renderer:
            renderer.set_quality(self.quality.currentData()); renderer.reduced = self.reduced.isChecked()
            self.constellation.set_active(self.active and not self.window.isMinimized())
        self.model.setText(str(config.get('ai',{}).get('model','qwen3:4b-instruct')))
        self.ai_enabled.setChecked(config.get('ai',{}).get('enabled') is True)
        self.voice_enabled.setChecked(config.get('tts',{}).get('enabled') is True)
        tts = config.get('tts',{}); provider=tts.get('provider','kokoro')
        self.voice_name.setText(str(tts.get({'edge':'edge_voice','voicestudio':'voicestudio_voice'}.get(provider,'voice'),'')))
        self.settings_status.setText('Provedor de voz: '+provider+' · credenciais e tokens permanecem ocultos.')
        self._arrange_scene()

    def save_appearance(self):
        if self.window._processing:
            self.graphics_note.setText('Conclua ou pare o pedido antes de salvar.'); return
        config = deepcopy(self.window._agent_config_loader())
        config.setdefault('ui',{}).update(graphics_quality=self.quality.currentData(),reduced_motion=self.reduced.isChecked())
        try:
            self.window._agent_config_writer(config)
        except Exception:
            self.graphics_note.setText('Não foi possível salvar a aparência.'); return
        self.window._config['ui'] = deepcopy(config['ui']); self.refresh_settings()
        self.graphics_note.setText('Aparência salva.')

    def save_runtime(self):
        if self.window._processing:
            self.settings_status.setText('Conclua ou pare o pedido antes de salvar.'); return
        config = deepcopy(self.window._agent_config_loader())
        if not self.model.text().strip():
            self.settings_status.setText('Informe o nome do modelo.'); return
        config.setdefault('ai',{}).update(model=self.model.text().strip(),enabled=self.ai_enabled.isChecked())
        tts = config.setdefault('tts',{})
        field={'edge':'edge_voice','voicestudio':'voicestudio_voice'}.get(tts.get('provider'),'voice')
        tts.update(enabled=self.voice_enabled.isChecked()); tts[field]=self.voice_name.text().strip()
        try:
            self.window._agent_config_writer(config)
        except Exception:
            self.settings_status.setText('Não foi possível salvar modelo e voz.'); return
        # A configuração em uso não muda no meio de uma sessão.
        self.settings_status.setText('Modelo e voz salvos. Feche e abra o Therion para aplicar.')

    @property
    def busy(self):
        return (self.mailbox.busy or self.surfaces.busy or self.action_worker is not None or any(worker.isRunning() for worker in self.workers.values())
                or (self.calendar_auth is not None and self.calendar_auth.state()!=QProcess.NotRunning))

    def cancel(self):
        self.active = False
        self.orb_transition.stop()
        self.mailbox.cancel()
        self.surfaces.cancel()
        self.dirty.clear()
        for key in self.epochs: self.epochs[key] += 1
        self.timer.stop(); self.refresh_timer.stop(); self.constellation.set_active(False)
        renderer=self.constellation.renderer
        if renderer:
            renderer.disabled=True;renderer.cleanup()
        for worker in self.workers.values(): worker.token.cancel()
        if self.action_worker: self.action_worker.token.cancel()
        if self.calendar_auth is not None:
            self.auth_cancelled=True
            self.calendar_auth.kill()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.window.width()
        self._update_navigation()
        self.nav_caption.hide()
        titles = SECTION_TITLES
        self.search.setMaximumWidth(280 if width>=1280 else 180)
        self.meter.setVisible(width>=1100)


        self.clock.setVisible(width>=1280)
        self._sync_home_copy()
        self._arrange_scene()
        QTimer.singleShot(0,self._arrange_scene)
