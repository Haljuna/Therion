"""Tela de carregamento do Therion.

Substitui a janela do PowerShell: roda scripts/Start-Therion.ps1 escondido e
mostra o carregamento com a própria orbe do Therion (Constellation), cercada
por órbitas, anel de progresso e etapas. Fecha quando a janela principal
aparece; erros ficam visíveis na própria tela.

Uso: .venv\\Scripts\\pythonw.exe -m therion.interface.launcher
"""
from __future__ import annotations

import ctypes
import json
import math
import random
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

APP_ID = 'Therion.Desktop'
REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / 'therion' / 'assets'
START_SCRIPT = REPO / 'scripts' / 'Start-Therion.ps1'
PROGRESS_URL = 'http://127.0.0.1:3901/startup/progress'

# Paleta do Therion (design_system.COLORS e o shader da orbe).
BACKGROUND = '#09090F'
TEXT = '#F1F0F7'
MUTED = '#B5B1C5'
ACCENT = '#A78BFA'
LAVENDER = '#DDD6FE'
DEEP = '#5C38B5'
DANGER = '#FCA5A5'

# Etapas: (rótulo, início e fim no anel de progresso, constante de tempo em s, estado da orbe).
STEPS = (
    ('Serviços', 0.00, 0.08, 4.0, 'preparing'),
    ('Voz', 0.08, 0.62, 80.0, 'thinking'),
    ('IA', 0.62, 0.92, 18.0, 'executing'),
    ('Interface', 0.92, 1.00, 3.0, 'speaking'),
)
# Linhas do script -> (etapa, frase).
_LINES = (
    ('Preparando', 0, 'Despertando os serviços…'),
    ('Backend', 1, 'Carregando a voz do Jarvis…'),
    ('Parakeet', 1, 'Carregando a transcrição…'),
    ('Therion pronto', 3, 'Abrindo o Therion…'),
)


def set_app_id() -> None:
    """Agrupa as janelas do Therion na barra de tarefas com o ícone próprio."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def fix_mojibake(text: str) -> str:
    """Scripts UTF-8 lidos como ANSI geram 'mÃ­nimo'; desfaz quando possível."""
    try:
        return text.encode('cp1252').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def activate_running() -> bool:
    """Se o Therion já está aberto (mesmo só na bandeja), pede para mostrar a janela."""
    from PySide6.QtNetwork import QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer('TherionV4-activate')
    ok = socket.waitForConnected(800)
    socket.disconnectFromServer()
    return ok


def therion_window_open() -> bool:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, 'Therion')
    return bool(hwnd) and bool(user32.IsWindowVisible(hwnd))


def native_drag(widget: QWidget) -> None:
    """Arrasta a janela sem bordas como se fosse pela barra de título."""
    try:
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.SendMessageW(int(widget.window().winId()), 0x00A1, 2, 0)
    except Exception:
        pass


def rounded_corners(widget: QWidget) -> None:
    """Cantos arredondados nativos do Windows 11 (DWMWA_WINDOW_CORNER_PREFERENCE)."""
    try:
        value = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(widget.winId()), 33, ctypes.byref(value), 4)
    except Exception:
        pass


def ease(t: float) -> float:
    t = max(0., min(1., t))
    return 1 - (1 - t) ** 3


class Loader(QObject):
    """Executa o script de inicialização e repassa a saída linha a linha."""

    line = Signal(str)
    finished = Signal(int, str)

    def run(self) -> None:
        command = [
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
            '[Console]::OutputEncoding=[Text.Encoding]::UTF8; '
            f"& '{START_SCRIPT}' -Quiet; exit $LASTEXITCODE",
        ]
        try:
            process = subprocess.Popen(
                command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                encoding='utf-8', errors='replace')
        except OSError as error:
            self.finished.emit(1, f'Não foi possível iniciar o PowerShell: {error}')
            return
        output: list[str] = []
        assert process.stdout is not None
        for raw in process.stdout:
            text = fix_mojibake(raw.rstrip())
            if text:
                output.append(text)
                self.line.emit(text)
        code = process.wait()
        self.finished.emit(code, '\n'.join(output[-12:]))


class OrbitOverlay(QWidget):
    """Camada vetorial sobre a orbe: estrelas, órbitas com satélites e anel de progresso."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.clock = 0.
        self.progress = 0.      # valor exibido (suavizado)
        self.target = 0.
        self.state = 'loading'  # loading | done | error
        self.intro = 0.
        rng = random.Random(419)
        self.stars = [(rng.random(), rng.random(), rng.uniform(.4, 1.6), rng.uniform(0, math.tau),
                       rng.uniform(.2, 1.)) for _ in range(90)]
        self.orbits = (  # inclinação, achatamento, raio relativo, velocidade, satélites
            (-.42, .30, 1.42, .55, 2),
            (.36, .22, 1.62, -.38, 1),
            (1.25, .18, 1.30, .72, 1),
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            native_drag(self)

    def advance(self, dt: float) -> None:
        self.clock += dt
        self.intro = min(1., self.intro + dt / 1.4)
        self.progress += (self.target - self.progress) * (1 - math.exp(-dt / .45))
        self.update()

    def orb_rect(self) -> QRectF:
        side = min(self.width(), self.height()) * .50
        return QRectF(self.width() / 2 - side / 2, self.height() / 2 - side / 2 - 6, side, side)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = self.orb_rect().center()
        r = self.orb_rect().width() / 2
        t = self.clock
        fade = ease(self.intro)

        # Estrelas ao fundo, deriva lenta e cintilação.
        p.setPen(Qt.NoPen)
        for sx, sy, size, phase, depth in self.stars:
            x = (sx * w + t * 4 * depth) % w
            y = (sy * h + math.sin(t * .2 + phase) * 3 * depth) % h
            alpha = int(fade * 140 * depth * (.55 + .45 * math.sin(t * (1.2 + depth) + phase)))
            if math.hypot(x - c.x(), y - c.y()) < r * 1.05:
                continue
            col = QColor(LAVENDER)
            col.setAlpha(max(0, alpha))
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), size * .6, size * .6)

        error = self.state == 'error'
        tint = QColor(DANGER) if error else QColor(ACCENT)

        # Órbitas inclinadas com satélites e rastros.
        for i, (tilt, flat, scale, speed, sats) in enumerate(self.orbits):
            radius = r * scale * (.85 + .15 * fade)
            p.save()
            p.translate(c)
            p.rotate(math.degrees(tilt + math.sin(t * .11 + i) * .06))
            line = QColor(tint)
            line.setAlpha(int(fade * (34 if not error else 28)))
            p.setPen(QPen(line, 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), radius, radius * flat)
            spd = speed * (0.35 if error else 1.0) * (1.8 if self.state == 'done' else 1.0)
            for s in range(sats):
                base = t * spd + s * math.tau / sats + i
                for k in range(14):  # rastro
                    a = base - k * .045 * math.copysign(1, spd)
                    x, y = math.cos(a) * radius, math.sin(a) * radius * flat
                    front = math.sin(a) > 0  # metade da frente fica mais clara
                    col = QColor(LAVENDER if k == 0 else ACCENT)
                    col.setAlpha(int(fade * (230 if k == 0 else 120 * (1 - k / 14)) * (1 if front else .45)))
                    p.setPen(Qt.NoPen)
                    p.setBrush(col)
                    size = (2.6 if k == 0 else 1.7 * (1 - k / 16)) * (1.15 if front else .85)
                    p.drawEllipse(QPointF(x, y), size, size)
                if True:  # brilho do satélite
                    x, y = math.cos(base) * radius, math.sin(base) * radius * flat
                    g = QRadialGradient(QPointF(x, y), 10)
                    g.setColorAt(0, QColor(167, 139, 250, int(fade * 90)))
                    g.setColorAt(1, QColor(167, 139, 250, 0))
                    p.setBrush(g)
                    p.drawEllipse(QPointF(x, y), 10, 10)
            p.restore()

        # Anel de progresso.
        ring = QRectF(c.x() - r * 1.16, c.y() - r * 1.16, r * 2.32, r * 2.32)
        track = QColor(tint)
        track.setAlpha(int(fade * 26))
        p.setPen(QPen(track, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(ring)
        span = max(.004, self.progress) * 360
        grad = QLinearGradient(ring.topLeft(), ring.bottomRight())
        grad.setColorAt(0, QColor(DANGER if error else DEEP))
        grad.setColorAt(1, QColor(DANGER if error else LAVENDER))
        p.setPen(QPen(grad, 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(ring, 90 * 16, int(-span * 16))
        # Cabeça luminosa do anel, respirando.
        a = math.radians(90 - span)
        head = QPointF(c.x() + math.cos(a) * ring.width() / 2, c.y() - math.sin(a) * ring.height() / 2)
        breath = .75 + .25 * math.sin(t * 3.2)
        g = QRadialGradient(head, 16)
        g.setColorAt(0, QColor(252, 165, 165, 200) if error else QColor(221, 214, 254, int(220 * breath)))
        g.setColorAt(1, QColor(167, 139, 250, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(head, 16, 16)
        p.setBrush(QColor(TEXT))
        p.drawEllipse(head, 2.4, 2.4)

        # Marcas das etapas no anel.
        for _label, start, _end, _tau, _state in STEPS[1:]:
            a = math.radians(90 - start * 360)
            pt = QPointF(c.x() + math.cos(a) * ring.width() / 2, c.y() - math.sin(a) * ring.height() / 2)
            col = QColor(LAVENDER if self.progress >= start else MUTED)
            col.setAlpha(int(fade * (230 if self.progress >= start else 90)))
            p.setBrush(col)
            p.drawEllipse(pt, 2.0, 2.0)

        # Onda de conclusão: anel que se expande quando fica pronto.
        if self.state == 'done':
            k = (t * .9) % 1.
            col = QColor(LAVENDER)
            col.setAlpha(int(160 * (1 - k)))
            p.setPen(QPen(col, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r * (1.16 + k * .9), r * (1.16 + k * .9))


class StepBar(QWidget):
    """Quatro etapas ligadas por uma linha; a atual pulsa."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(46)
        self.current = 0
        self.error = False
        self.clock = 0.
        self.fill = 0.

    def advance(self, dt: float) -> None:
        self.clock += dt
        self.fill += (self.current - self.fill) * (1 - math.exp(-dt / .35))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(STEPS)
        margin = 46
        span = (self.width() - 2 * margin) / (n - 1)
        y = 12
        xs = [margin + i * span for i in range(n)]
        dim = QColor(MUTED)
        dim.setAlpha(50)
        p.setPen(QPen(dim, 1.2))
        p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
        lit = QColor(DANGER if self.error else ACCENT)
        p.setPen(QPen(lit, 1.6))
        p.drawLine(QPointF(xs[0], y), QPointF(xs[0] + self.fill * span, y))
        font = QFont('Segoe UI Variable Text', 8)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(font)
        for i, x in enumerate(xs):
            done = i < self.current
            active = i == self.current
            p.setPen(Qt.NoPen)
            if active:
                pulse = (self.clock * .8) % 1.
                halo = QColor(DANGER if self.error else ACCENT)
                halo.setAlpha(int(120 * (1 - pulse)))
                p.setBrush(halo)
                p.drawEllipse(QPointF(x, y), 4 + pulse * 9, 4 + pulse * 9)
                p.setBrush(QColor(DANGER if self.error else LAVENDER))
                p.drawEllipse(QPointF(x, y), 4.2, 4.2)
            elif done:
                p.setBrush(QColor(ACCENT))
                p.drawEllipse(QPointF(x, y), 3.6, 3.6)
            else:
                p.setPen(QPen(dim, 1.2))
                p.setBrush(QColor(BACKGROUND))
                p.drawEllipse(QPointF(x, y), 3.4, 3.4)
            text = QColor(TEXT if active else (MUTED if done else '#6E6A80'))
            p.setPen(text)
            label = STEPS[i][0].upper()
            p.drawText(QRectF(x - 50, y + 10, 100, 18), Qt.AlignCenter, label)


class Splash(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint)
        self.setWindowTitle('Therion — carregando')
        self.setWindowIcon(QIcon(str(ASSETS / 'therion-orb.ico')))
        self.setFixedSize(560, 620)
        self.setStyleSheet(f'background:{BACKGROUND};')
        self._step = 0
        self._step_started = time.monotonic()
        self._started = time.monotonic()
        self._status_text = ''
        self._done = False
        self._closing = 0.
        self._title_spacing = 22.

        # A orbe do Therion, a mesma da janela principal.
        from therion.interface.constellation import Constellation
        self._orb = Constellation(self)
        self._orb.setGeometry(0, 0, 560, 620)  # Janela inteira: fundo contínuo sob o texto.
        self._overlay = OrbitOverlay(self)
        self._overlay.setGeometry(0, 0, 560, 430)
        orb = self._overlay.orb_rect()
        self._orb.set_focus_rect(orb.adjusted(-orb.width() * .06, -orb.height() * .06,
                                              orb.width() * .06, orb.height() * .06))
        self._orb.set_visual('preparing')

        self._title = QLabel('THERION', self)
        self._title.setAlignment(Qt.AlignCenter)
        self._status = QLabel('', self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(f'color:{LAVENDER}; font-size:14px; background:transparent;')
        self._steps = StepBar(self)
        self._detail = QLabel('', self)
        self._detail.setAlignment(Qt.AlignCenter)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f'color:{MUTED}; font-size:11px; background:transparent;')

        self._close = QPushButton('Fechar')
        self._retry = QPushButton('Tentar de novo')
        for button in (self._close, self._retry):
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f'QPushButton {{ color:#E5E1F0; background:#211D30; border:1px solid #443B58;'
                ' border-radius:12px; padding:7px 18px; font-size:12px; }'
                f'QPushButton:hover {{ color:{TEXT}; background:#30283F; border-color:{ACCENT}; }}')
            button.hide()
        self._close.clicked.connect(QApplication.quit)
        self._retry.clicked.connect(self._restart)

        bottom = QWidget(self)
        bottom.setGeometry(0, 380, 560, 240)
        bottom.setStyleSheet('background:transparent;')
        layout = QVBoxLayout(bottom)
        layout.setContentsMargins(24, 0, 24, 20)
        layout.setSpacing(6)
        self._title.setParent(bottom)
        self._status.setParent(bottom)
        self._steps.setParent(bottom)
        self._detail.setParent(bottom)
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addSpacing(8)
        layout.addWidget(self._steps)
        layout.addWidget(self._detail)
        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._retry)
        buttons.addWidget(self._close)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._set_status('Despertando os serviços…')
        self._last = time.monotonic()
        self._frame = QTimer(self)
        self._frame.setTimerType(Qt.PreciseTimer)
        self._frame.timeout.connect(self._tick)
        self._frame.start(16)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._poll)
        self._clock.start(1000)
        self.setWindowOpacity(0.)
        self._start_loader()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        rounded_corners(self)
        self._orb.set_active(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            native_drag(self)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BACKGROUND))
        border = QColor(ACCENT)
        border.setAlpha(40)
        p.setPen(QPen(border, 1))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
        p.drawPath(path)

    # --- animação -----------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(.1, now - self._last)
        self._last = now
        # Entrada e saída em fade.
        if self._closing > 0:
            self._closing += dt
            self.setWindowOpacity(max(0., 1 - self._closing / .6))
            if self._closing > .6:
                QApplication.quit()
                return
        elif self.windowOpacity() < 1:
            self.setWindowOpacity(min(1., self.windowOpacity() + dt / .45))
        # Título: letras se aproximam na entrada.
        self._title_spacing += (9. - self._title_spacing) * (1 - math.exp(-dt / .5))
        font = QFont('Segoe UI Variable Display', 22, QFont.DemiBold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, self._title_spacing)
        self._title.setFont(font)
        alpha = int(255 * ease(self._overlay.intro))
        self._title.setStyleSheet(f'color:rgba(241,240,247,{alpha}); background:transparent;')
        # Progresso: dentro da etapa avança assintoticamente, sem nunca passar a próxima.
        if not self._done or self._overlay.state == 'done':
            _l, start, end, tau, _s = STEPS[self._step]
            frac = 1 - math.exp(-(now - self._step_started) / tau)
            self._overlay.target = start + (end - start) * frac * .96 if self._overlay.state != 'done' else 1.
        self._overlay.advance(dt)
        self._steps.advance(dt)

    def _go_step(self, index: int) -> None:
        if index <= self._step and self._step != 0:
            return
        if index != self._step:
            self._step = index
            self._step_started = time.monotonic()
        self._steps.current = index
        self._orb.set_visual(STEPS[index][4], .4)

    def _set_status(self, text: str) -> None:
        self._status_text = text
        self._status.setText(text)

    # --- carregamento -------------------------------------------------
    def _start_loader(self) -> None:
        if '--demo' in sys.argv:  # Simulação visual, sem iniciar nada.
            fail = '--demo-error' in sys.argv
            for delay, text in ((600, 'Preparando faster-whisper, Jarvis e a IA local.'), (2500, 'Backend minimo iniciado')):
                QTimer.singleShot(delay, lambda t=text: self._on_line(t))
            QTimer.singleShot(9000, lambda: (self._go_step(2), self._set_status('Aquecendo a IA local…')))
            if fail:
                QTimer.singleShot(13000, lambda: self._on_finished(1, 'Jarvis nao ficou pronto.'))
            else:
                QTimer.singleShot(14000, lambda: self._on_line('Therion pronto.'))
                QTimer.singleShot(15500, lambda: (self._ready_wave(), self._set_status('Pronto.'),
                                                  QTimer.singleShot(1600, self._finish)))
            return
        self._thread = QThread(self)
        self._loader = Loader()
        self._loader.moveToThread(self._thread)
        self._thread.started.connect(self._loader.run)
        self._loader.line.connect(self._on_line)
        self._loader.finished.connect(self._on_finished)
        self._loader.finished.connect(self._thread.quit)
        self._thread.start()

    def _restart(self) -> None:
        self._done = False
        self._started = self._step_started = time.monotonic()
        self._step = 0
        self._overlay.state = 'loading'
        self._overlay.target = self._overlay.progress = 0.
        self._steps.error = False
        self._steps.current = 0
        self._retry.hide()
        self._close.hide()
        self._detail.setStyleSheet(f'color:{MUTED}; font-size:11px; background:transparent;')
        self._status.setStyleSheet(f'color:{LAVENDER}; font-size:14px; background:transparent;')
        self._orb.set_visual('preparing')
        self._set_status('Despertando os serviços…')
        self._start_loader()

    def _on_line(self, text: str) -> None:
        for marker, step, status in _LINES:
            if text.startswith(marker):
                self._go_step(step)
                self._set_status(status)
                return
        if 'ja esta aberto' in text or 'já está aberto' in text:
            self._set_status('O Therion já está aberto.')
        elif 'ja esta sendo preparado' in text:
            self._set_status('O Therion já está sendo preparado.')

    def _poll(self) -> None:
        if self._done and self._overlay.state != 'loading':
            return
        elapsed = int(time.monotonic() - self._started)
        self._detail.setText(f'{elapsed // 60}:{elapsed % 60:02d}  ·  a primeira carga pode levar alguns minutos')
        if self._step == 1:
            try:
                with urllib.request.urlopen(PROGRESS_URL, timeout=0.5) as response:
                    state = json.loads(response.read().decode('utf-8'))
                if state.get('status') == 'ready':
                    self._go_step(2)
                    self._set_status('Aquecendo a IA local…')
                elif state.get('phase') == 'warming':
                    self._set_status('Aquecendo a voz do Jarvis…')
            except Exception:
                pass

    def _on_finished(self, code: int, output: str) -> None:
        self._done = True
        if code == 0:
            if 'já está aberto' in self._status_text:  # Talvez só na bandeja.
                if activate_running():
                    self._finish()
                    return
                self._ready_wave()
                QTimer.singleShot(2500, self._finish)
                return
            if 'sendo preparado' in self._status_text:
                # Outra abertura (ex.: inicialização do Windows) já está carregando: acompanhar até a janela surgir.
                self._done = False
                self._go_step(1)
                self._set_status('Carregando a voz do Jarvis…')
                self._wait_window(time.monotonic(), limit=900)
                return
            self._go_step(3)
            self._set_status('Abrindo o Therion…')
            self._wait_window(time.monotonic())
            return
        self._overlay.state = 'error'
        self._steps.error = True
        self._orb.set_visual('error')
        self._set_status('Não foi possível abrir o Therion')
        self._status.setStyleSheet(f'color:{DANGER}; font-size:14px; background:transparent;')
        message = output.strip().splitlines()[-3:] if output.strip() else ['Sem detalhes.']
        self._detail.setText('\n'.join(message) + '\nLog: %LOCALAPPDATA%\\Therion\\voice\\startup.log')
        self._detail.setStyleSheet(f'color:{DANGER}; font-size:11px; background:transparent;')
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._retry.show()
        self._close.show()

    def _ready_wave(self) -> None:
        self._overlay.state = 'done'
        self._steps.current = len(STEPS)
        self._orb.set_visual('speaking', .7)
        self._detail.setText('')

    def _wait_window(self, since: float, limit: float = 45) -> None:
        # A janela principal leva alguns segundos para surgir; fecha quando aparecer.
        if therion_window_open() or time.monotonic() - since > limit:
            self._ready_wave()
            self._set_status('Pronto.')
            QTimer.singleShot(900, self._finish)
        else:
            QTimer.singleShot(300, lambda: self._wait_window(since, limit))

    def _finish(self) -> None:
        if self._closing == 0:
            self._closing = 1e-6


def main() -> int:
    set_app_id()
    from therion.interface.graphics import prepare_graphics
    prepare_graphics()
    app = QApplication(sys.argv)
    if '--demo' not in sys.argv and activate_running():
        return 0  # Já aberto: só trouxe a janela para frente.
    app.setApplicationName('Therion')
    app.setWindowIcon(QIcon(str(ASSETS / 'therion-orb.ico')))
    splash = Splash()
    splash.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
