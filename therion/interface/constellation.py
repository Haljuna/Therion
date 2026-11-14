"""Lugar da Orbe HUD na interface do Therion. Apenas apresentação; sem acesso a serviços."""
import os
import numpy as np
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget, QStackedWidget, QLabel
from .hud_frame import FrameState, paint_hud_frame
from .hud_style import CORE, DOT, hud_layout, label_for, look_for
from .orb_geometry import fib_sphere, _rot_x, _rot_y
from .orb_renderer import OrbGL

STATIC_POINTS = 1800


class StaticConstellation(QWidget):
    """Reserva sem OpenGL: a esfera de pontos parada, em 2D, com a moldura e o nome do estado."""
    def __init__(self, parent=None):
        super().__init__(parent)
        v = _rot_x(_rot_y(fib_sphere(STATIC_POINTS), .4), .28)
        k = 3.4/(3.4-v[:, 2])   # mesma perspectiva do shader
        self.dots = np.column_stack((v[:, 0]*k, -v[:, 1]*k, (v[:, 2]+1.)/2.))[np.argsort(v[:, 2])]
        self.state = 'idle'
        self.focus_rect = None
        self.setMinimumSize(160, 160)

    def set_state(self, state):
        # O painel repete o estado a cada 50 ms; só redesenha quando muda.
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#09090F'))
        focus = self.focus_rect or QRectF(self.rect())
        lay = hud_layout(focus.x(), focus.y(), focus.width(), focus.height())
        look = look_for(self.state)
        glow = QRadialGradient(lay.cx, lay.cy, lay.R*1.25)
        glow.setColorAt(0, QColor(*CORE, round(255*look.core)))
        glow.setColorAt(.55, QColor(*CORE, round(255*look.core*.45)))
        glow.setColorAt(1, QColor(*CORE, 0))
        painter.fillRect(self.rect(), glow)
        painter.setPen(Qt.NoPen)
        scale = (2600/STATIC_POINTS)**.5*lay.R/170.
        for x, y, depth in self.dots:   # frente maior e clara, fundo menor e escuro
            size = max(1., (.8+1.6*depth)*scale)
            painter.setBrush(QColor(*DOT, round(255*(.12+.88*depth)*.8*look.dim)))
            painter.drawEllipse(QRectF(lay.cx+x*lay.R-size/2, lay.cy+y*lay.R-size/2, size, size))
        paint_hud_frame(painter, lay, FrameState(
            label=label_for(self.state), level=0., arc_deg=look.arc_deg, arc_scale=look.arc_scale,
            arc_rotation=0., tick_rotation=0., dash_rotation=0., blink=1., amber=look.amber,
            voice_ring=0., voice=0.))


class Constellation(QWidget):
    def __init__(self, parent=None, *, static=False):
        super().__init__(parent)
        self.setAccessibleName('Presença visual do Therion')
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.focus_rect=None
        self.stack = QStackedWidget(self)
        self.still = StaticConstellation(); self.stack.addWidget(self.still)
        self.notice = QLabel('',self); self.notice.setWordWrap(True)
        self.notice.setObjectName('muted'); self.notice.setAlignment(Qt.AlignCenter)
        self.notice.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.renderer = None
        if not static and os.environ.get('QT_QPA_PLATFORM') not in {'offscreen','minimal'}:
            self.renderer = OrbGL()
            self.stack.addWidget(self.renderer); self.stack.setCurrentWidget(self.renderer)
            self.renderer.failed.connect(self._failed)
        else:
            self.notice.setText('Prévia estática · animação OpenGL indisponível neste modo.')
        self.notice.setVisible(bool(self.notice.text()))

    def paintEvent(self,event):
        # O mesmo fundo sustenta o campo estático e o campo animado.
        painter=QPainter(self); painter.fillRect(event.rect(),QColor('#09090F'))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'stack'): self._arrange_region()

    def _arrange_region(self):
        target=(self.focus_rect or QRectF(self.rect())).intersected(QRectF(self.rect()))
        # Cena inteira em resolução nativa: a paralaxe não pode terminar numa
        # emenda retangular ao redor da orbe. O bloom continua separado.
        region=self.rect()
        if region.isEmpty(): return
        self.stack.setGeometry(region)
        local=target.translated(-region.x(),-region.y())
        self.still.focus_rect=local.intersected(QRectF(self.stack.rect()))
        if self.renderer:
            self.renderer.focus_rect=local
            self.renderer.update()
        self.still.update()
        self.notice.setGeometry(12,max(0,self.height()-32),max(1,self.width()-24),28)
        self.notice.raise_()

    def _failed(self, message):
        if self.renderer:
            self.renderer.disabled = True
            self.renderer.set_active(False)
        QTimer.singleShot(0, lambda: self.stack.setCurrentWidget(self.still))
        self.notice.setText(message)
        self.notice.show()

    def set_visual(self, state, intensity=0.):
        if self.renderer:
            self.renderer.set_visual(state,intensity)
        self.still.set_state(state)
        self.setAccessibleDescription(state)

    def set_scene_pointer(self,x,y):
        if self.renderer:self.renderer.scene_motion.aim(x,y)

    def set_attention(self,value):
        if self.renderer:self.renderer.target_scene_attention=max(.4,min(1.,float(value)))

    def set_active(self, active):
        if self.renderer:
            self.renderer.set_active(active)

    def set_focus_rect(self, rect):
        rect=QRectF(rect)
        if self.focus_rect!=rect:
            self.focus_rect=rect
            self._arrange_region()

    def showEvent(self, event):
        super().showEvent(event)
        if self.renderer:
            QTimer.singleShot(1000, self._check_context)

    def _check_context(self):
        if self.isVisible() and self.renderer and not self.renderer.isValid():
            self.renderer.set_active(False)
            self._failed('Animação indisponível: o sistema não forneceu um contexto OpenGL.')
