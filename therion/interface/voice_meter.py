"""Indicador visual da intensidade já medida pelo Therion; não captura áudio."""
import math
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget
from .presentation import normalized_level


class VoiceMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120,38)
        self.setAccessibleName('Intensidade da voz')
        self.level=0.
        self.active=False

    def set_level(self, state, level):
        self.active=state in {'speaking','listening'}
        self.level=normalized_level(level) if self.active else 0.
        self.setAccessibleDescription('Áudio em reprodução ou captura' if self.active else 'Sem áudio ativo')
        self.update()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#AA8FEA' if self.active else '#452B86'),1.4,Qt.SolidLine,Qt.RoundCap))
        amplitude=1.0+self.level*12
        phase=time.monotonic()*8 if self.active else 0.
        for x in range(6,self.width()-5,4):
            envelope=math.exp(-((x-self.width()*.48)/(self.width()*.30))**2)
            value=(.25+.75*abs(math.sin(x*.48-phase)))*amplitude*envelope
            painter.drawLine(x,round(self.height()/2-value),x,round(self.height()/2+value))
