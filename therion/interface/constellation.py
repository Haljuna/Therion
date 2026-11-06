"""Moldura da orbe holográfica do Therion. Apenas apresentação; sem acesso a serviços."""
import os
import numpy as np
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget, QStackedWidget, QLabel
from .orb_geometry import build_orb
from .orb_renderer import OrbGL


class StaticConstellation(QWidget):
    """Reserva sem OpenGL: a forma da orbe parada, projetada em 2D."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lines = build_orb().lines
        self.segments = lines[::6, :6]   # um vértice por segmento: ponta e outra ponta
        self.glow = lines[::6, 10]
        self.focus_rect = None
        self.setMinimumSize(160, 160)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#09090F'))
        focus = self.focus_rect or QRectF(self.rect())
        cx, cy = focus.center().x(), focus.center().y()
        radius = min(focus.width(), focus.height())*.38
        glow = QRadialGradient(cx, cy, radius*1.25)
        glow.setColorAt(0, QColor(124, 77, 255, 46))
        glow.setColorAt(1, QColor(9, 9, 15, 0))
        painter.fillRect(self.rect(), glow)
        for (x0, y0, z0, x1, y1, _), g in zip(self.segments, self.glow):
            back = .35 if z0 < 0 else 1.
            color = QColor(201, 184, 255) if g > .8 else QColor(124, 77, 255)
            color.setAlpha(int(min(255, 70+150*g*back)))
            painter.setPen(QPen(color, 1.))
            painter.drawLine(QPointF(cx+x0*radius, cy-y0*radius), QPointF(cx+x1*radius, cy-y1*radius))


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
