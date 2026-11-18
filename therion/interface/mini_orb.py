"""Posição da mini orbe flutuante: funções puras sobre QRect/QPoint/QSize em coordenadas lógicas.

`screens` são as áreas úteis (sem barra de tarefas).
"""
import ctypes
import json
import os
import threading

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QRadialGradient, QRegion
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QProgressBar, QVBoxLayout, QWidget

from therion.core.local_reports import _gb

from .hud_style import hud_layout
from .orb_renderer import OrbGL
from .pc_health import full_reading, label_text, quick_reading


def default_position(screens: list[QRect], primary: QRect, size: QSize, margin=24) -> QPoint:
    others = [screen for screen in screens if screen != primary]
    target = others[0] if others else primary
    return QPoint(target.x() + target.width() - size.width() - margin,
                  target.y() + target.height() - size.height() - margin)


def clamp(point: QPoint, size: QSize, screens: list[QRect]) -> QPoint:
    screen = _nearest(_center(point, size), screens)
    x = min(max(point.x(), screen.x()), screen.x() + screen.width() - size.width())
    y = min(max(point.y(), screen.y()), screen.y() + screen.height() - size.height())
    return QPoint(x, y)


def restore(path: str, screens: list[QRect], size: QSize) -> QPoint | None:
    try:
        with open(path, encoding='utf-8') as file:
            data = json.load(file)
        x, y = int(data['x']), int(data['y'])
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None
    # QPoint wraps out-of-range ints silently, so reject them before building it
    if not all(-2 ** 31 <= value < 2 ** 31 for value in (x, y)):
        return None
    point = QPoint(x, y)
    center = _center(point, size)
    return point if any(_contains(screen, center) for screen in screens) else None


def save(path: str, point: QPoint) -> None:
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as file:
            json.dump({'x': point.x(), 'y': point.y()}, file)
        os.replace(tmp, path)
    except OSError:
        pass


def beside(anchor: QRect, size: QSize, screen: QRect, gap=8) -> QPoint:
    right = anchor.x() + anchor.width() + gap
    left = anchor.x() - gap - size.width()
    x = right if right + size.width() <= _right(screen) else left
    top = anchor.y()
    bottom = anchor.y() + anchor.height() - size.height()
    y = top if top + size.height() <= _bottom(screen) else bottom
    return clamp(QPoint(x, y), size, [screen])


def _center(point: QPoint, size: QSize) -> QPoint:
    return QPoint(point.x() + size.width() // 2, point.y() + size.height() // 2)


def _right(rect: QRect) -> int:
    return rect.x() + rect.width()


def _bottom(rect: QRect) -> int:
    return rect.y() + rect.height()


def _contains(rect: QRect, point: QPoint) -> bool:
    return rect.x() <= point.x() < _right(rect) and rect.y() <= point.y() < _bottom(rect)


def _distance(rect: QRect, point: QPoint) -> int:
    dx = max(rect.x() - point.x(), 0, point.x() - _right(rect))
    dy = max(rect.y() - point.y(), 0, point.y() - _bottom(rect))
    return dx * dx + dy * dy


def _nearest(point: QPoint, screens: list[QRect]) -> QRect:
    return min(screens, key=lambda screen: _distance(screen, point))


ORB_PX = 96
DRAG_PX = 4
VK_LBUTTON, VK_ESCAPE = 0x01, 0x1B
GLASS = ('background: rgba(20,19,30,184); border: 1px solid rgba(255,255,255,23); border-radius: 14px;'
         ' color: #F1F0F7; font-size: 12px;')
NO_FOCUS = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus


def _floating(widget):
    widget.setWindowFlags(NO_FOCUS)
    widget.setAttribute(Qt.WA_ShowWithoutActivating)
    widget.setAttribute(Qt.WA_TranslucentBackground)


def _key_down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _screens():
    return [screen.availableGeometry() for screen in QGuiApplication.screens()]


def _size_text(used, total, missing='indisponível'):
    return missing if used is None or not total else f'{_gb(used)} de {_gb(total)}'


class _Panel(QFrame):
    def __init__(self):
        super().__init__()
        _floating(self)
        self.setObjectName('panel')
        self.setFixedWidth(320)
        self.setStyleSheet('QFrame#panel {' + GLASS + '} QLabel { border: none; background: transparent; }'
                           ' QProgressBar { border: none; background: rgba(255,255,255,23); border-radius: 3px;'
                           ' max-height: 6px; } QProgressBar::chunk { background: #A78BFA; border-radius: 3px; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        title = QLabel('SAÚDE DO PC')
        title.setStyleSheet('font-size: 11px; color: #8E89A6;')
        layout.addWidget(title)
        self.rows, self.bars = {}, {}
        for key, name in (('ram', 'RAM'), ('vram', 'VRAM'), ('commit', 'Memória virtual'), ('c', 'Disco C')):
            row = QLabel(name)
            layout.addWidget(row)
            self.rows[key] = (row, name)
            self.bars[key] = QProgressBar(maximum=1000, textVisible=False)
            layout.addWidget(self.bars[key])
        self.tops = {}
        for key, name in (('top_ram', 'Quem mais usa RAM'), ('top_vram', 'Quem mais usa VRAM')):
            head = QLabel(name)
            head.setStyleSheet('font-size: 11px; color: #8E89A6; margin-top: 8px;')
            layout.addWidget(head)
            self.tops[key] = QLabel('lendo…')
            layout.addWidget(self.tops[key])

    def show_reading(self, reading, partial=False):
        """`partial`: a leitura completa ainda não chegou, então o que falta é 'lendo…', não 'indisponível'."""
        missing = 'lendo…' if partial else 'indisponível'
        def line(key, text, fraction, amber=False):
            label, name = self.rows[key]
            label.setText(f'{name}  ·  {text}')
            label.setStyleSheet('color: #F2B544;' if amber else '')
            if key in self.bars:
                self.bars[key].setStyleSheet('QProgressBar::chunk { background: #F2B544; border-radius: 3px; }' if amber else '')
            if key in self.bars:
                self.bars[key].setValue(round(1000 * min(max(fraction or 0, 0), 1)))
        line('ram', _size_text(reading.get('ram_used'), reading.get('ram_total'), missing), reading.get('ram'))
        temp = reading.get('gpu_temp')
        vram = _size_text(reading.get('vram_used'), reading.get('vram_total'), missing)
        if temp is not None and reading.get('vram_used') is not None:
            vram += f' · {temp} °C'
        line('vram', vram, reading.get('vram'))
        used, total = reading.get('commit_used'), reading.get('commit_total')
        line('commit', _size_text(used, total, missing), used / total if total and used is not None else 0)
        free = reading.get('c_free')
        c_total = reading.get('c_total')
        line('c', missing if free is None else f'{_gb(free)} livres',
             1 - free / c_total if free is not None and c_total else 0, amber=free is not None and free < 5 * 1024 ** 3)
        for key, label in self.tops.items():
            rows = reading.get(key)
            label.setText('\n'.join(f'{name}  ·  {_gb(size)}' for name, size in rows or ())
                          or ('lendo…' if partial and rows is None else 'indisponível'))
        self.adjustSize()


class MiniOrb(QWidget):
    reading_ready = Signal(dict)

    def __init__(self, *, path, renderer_factory=OrbGL, readers=(quick_reading, full_reading), on_open_main=None,
                 key_state=_key_down, cursor_pos=QCursor.pos):
        super().__init__()
        _floating(self)
        self.setFixedSize(ORB_PX, ORB_PX)
        self._path, self._readers, self._on_open_main = path, readers, on_open_main
        self._key_state, self._cursor_pos, self._last_quick, self._last_full = key_state, cursor_pos, None, None
        self._visual, self._busy, self._pending = 'idle', False, None
        self._thread, self._press, self._dragged = None, None, False
        self._hover = self._quiet = self._game_hidden = self._dismissed = self._shut = False
        self.label = QLabel()
        _floating(self.label)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.label.setStyleSheet(GLASS + ' font-size: 11px; padding: 6px 10px;')
        self.panel = _Panel()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(3000)
        self.refresh_timer.timeout.connect(lambda: self._request('full'))
        self.watch_timer = QTimer(self)   # sem foco não há Esc nem clique fora: olha o teclado e o mouse
        self.watch_timer.setInterval(30)
        self.watch_timer.timeout.connect(self._watch)
        self.reading_ready.connect(self._deliver)
        self._renderer = renderer_factory() if renderer_factory else None
        if isinstance(self._renderer, QWidget):
            self._renderer.setParent(self)
            self._renderer.setMinimumSize(0, 0)
            self._renderer.setGeometry(0, 0, ORB_PX, ORB_PX)
            self._renderer.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.setMask(QRegion(self.rect(), QRegion.Ellipse))   # o GL desenha fundo escuro opaco: recorta em círculo
            if hasattr(self._renderer, 'failed'):
                self._renderer.failed.connect(self._renderer_failed)
        if self._renderer is not None:
            # Esfera no centro do círculo de 96 px: o HUD põe o centro a 44% da altura do retângulo.
            # 85 é o maior que cabe, pois o renderizador recorta o retângulo ao widget e o centro depende dele.
            self._renderer.focus_rect = QRectF(0, ORB_PX / 2 - hud_layout(0, 0, ORB_PX, 85).cy, ORB_PX, 85)
            self._renderer.set_quality('low')
            self._renderer.set_active(True)
            self._show_visual()
        screens = _screens()
        point = restore(path, screens, self.size())
        if point is None and screens:
            point = default_position(screens, QGuiApplication.primaryScreen().availableGeometry(), self.size())
        if point is not None:
            self.move(clamp(point, self.size(), screens))
        QGuiApplication.instance().screenRemoved.connect(self._reclamp)
        QGuiApplication.instance().screenAdded.connect(self._watch_screen)
        for screen in QGuiApplication.screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen):
        screen.availableGeometryChanged.connect(self._reclamp)

    def _reclamp(self, *_):
        """Monitor tirado ou resolução trocada em plena execução: traz a orbe de volta para a tela."""
        screens = _screens()
        if screens and not self._shut:
            self.move(clamp(self.pos(), self.size(), screens))

    # ---- estado visual ----
    def set_state(self, state, tight):
        if self._shut:
            return
        state = {'responding': 'idle', 'success': 'idle', 'cancelled': 'idle'}.get(state, state)   # como dashboard.interaction
        self._visual = 'error' if state == 'idle' and tight else state
        if self._renderer is not None:
            self._show_visual()
        self.update()

    def _show_visual(self):
        # Parada (repouso ou âmbar) ela só respira devagar: 10 quadros/s; ativa, 30. A orbe fica sempre ligada.
        self._renderer.min_interval_ms = 100 if self._visual in ('idle', 'error') else 33
        self._renderer.set_visual(self._visual, .5)

    def set_quiet(self, quiet):
        if self._shut:
            return
        self._quiet = quiet
        if self._renderer is not None:
            self._renderer.reduced = quiet
        self._sync_renderer()

    def hide_for_game(self, hidden):
        if self._shut:
            return
        self._game_hidden = hidden
        if hidden:
            self._close_panel()
            self.label.hide()
            self.hide()
        elif not self._dismissed and not self._shut:
            self.show()
        self._sync_renderer()

    def _sync_renderer(self):
        if self._renderer is not None:
            self._renderer.set_active(not (self._quiet or self._game_hidden or self._dismissed))

    def _renderer_failed(self, _message):
        if self._renderer is not None:
            self._renderer.set_active(False)
            self._renderer.hide()
        self._renderer = None
        self.clearMask()
        self.update()

    def paintEvent(self, _event):
        if self._renderer is not None:
            return
        paint = QPainter(self)
        paint.setRenderHint(QPainter.Antialiasing)
        color = QColor('#F2B544' if self._visual == 'error' else '#A78BFA')
        glow = QRadialGradient(ORB_PX / 2, ORB_PX / 2, ORB_PX / 2)
        glow.setColorAt(0, color.lighter(140))
        glow.setColorAt(1, color.darker(200))
        paint.setBrush(glow)
        paint.setPen(Qt.NoPen)
        paint.drawEllipse(self.rect().adjusted(8, 8, -8, -8))

    # ---- mouse: clique abre o painel, arrastar só move ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press, self._dragged = event.globalPosition().toPoint() - self.pos(), False

    def mouseMoveEvent(self, event):
        if self._press is None:
            return
        target = event.globalPosition().toPoint() - self._press
        if not self._dragged and (target - self.pos()).manhattanLength() <= DRAG_PX:
            return
        if not self._dragged:
            self._dragged = True
            self._close_panel()
            self.label.hide()
        self.move(clamp(target, self.size(), _screens()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            if self._dragged:
                save(self._path, self.pos())   # o desligamento do Windows não passa por shut()
            else:
                if self.panel.isVisible():
                    self._close_panel()
                else:
                    self._open_panel()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Abrir o Therion', lambda: self._on_open_main and self._on_open_main())
        menu.addAction('Esconder até reiniciar', self._dismiss)
        menu.exec(event.globalPos())

    def _dismiss(self):
        self._dismissed = True
        self._close_panel()
        self.label.hide()
        self.hide()
        self._sync_renderer()

    def enterEvent(self, event):
        self._hover = True
        if not self.panel.isVisible():
            self._show_label(self._last_quick)
            self._request('quick')

    def leaveEvent(self, event):
        self._hover = False
        self.label.hide()

    # ---- etiqueta e painel ----
    def _place(self, widget):
        widget.adjustSize()
        center = self.frameGeometry().center()
        screens = _screens()
        screen = min(screens, key=lambda rect: _distance(rect, center)) if screens else QRect()
        widget.move(beside(self.frameGeometry(), widget.size(), screen))

    def _open_panel(self):
        self.label.hide()
        self.panel.show_reading(self._last_full or self._last_quick or {}, partial=self._last_full is None)
        self._place(self.panel)
        self.panel.show()
        self.refresh_timer.start()
        self.watch_timer.start()
        self._request('full')

    def _close_panel(self):
        self.refresh_timer.stop()
        self.watch_timer.stop()
        self.panel.hide()

    def _watch(self):
        if self._key_state(VK_ESCAPE):
            self._close_panel()
        elif self._key_state(VK_LBUTTON):
            point = self._cursor_pos()
            if not (self.frameGeometry().contains(point) or self.panel.frameGeometry().contains(point)):
                self._close_panel()

    def _show_label(self, reading):
        if reading is not None and not self.panel.isVisible():
            self.label.setText(label_text(reading))
            self._place(self.label)
            self.label.show()

    # ---- leituras fora da thread da janela ----
    def _request(self, kind):
        if self._shut:
            return
        if self._busy:
            self._pending = kind
            return
        self._busy, self._pending = True, None
        reader = self._readers[1 if kind == 'full' else 0]
        self._thread = threading.Thread(target=self._work, args=(reader,), daemon=True)
        self._thread.start()

    def _work(self, reader):
        try:
            reading = reader()
        except Exception:
            reading = {}
        try:
            self.reading_ready.emit(reading)
        except RuntimeError:   # janela já destruída
            pass

    def _deliver(self, reading):
        self._busy = False
        if self._shut:
            return
        if 'ram_used' in reading:
            self._last_full = reading
            if self.panel.isVisible():
                self.panel.show_reading(reading)
                self._place(self.panel)
        elif reading.get('ram') is not None:
            self._last_quick = reading
            if self._hover:
                self._show_label(reading)
        pending, self._pending = self._pending, None
        if pending:
            self._request(pending)

    # ---- encerramento ----
    def shut(self):
        if self._shut:
            return
        self._shut = True
        self.refresh_timer.stop()
        self.watch_timer.stop()
        if self._thread is not None:
            self._thread.join(2)
        if self._renderer is not None:
            self._renderer.disabled = True   # um quadro atrasado não pode religar o timer do GL
            self._renderer.cleanup()
        save(self._path, self.pos())
        self.panel.close()
        self.label.close()
        self.close()
