"""Moldura da Orbe HUD desenhada com QPainter. Apenas apresentação; sem acesso a serviços."""
import math
from dataclasses import dataclass
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from .hud_style import AMBER, FRAME, HudLayout

LEVEL_DOTS = 25


@dataclass(frozen=True)
class FrameState:
    label: str
    level: float          # 0–1, pontinhos acesos do centro para fora
    arc_deg: float        # abertura de cada arco lateral
    arc_scale: float
    arc_rotation: float   # radianos
    tick_rotation: float
    dash_rotation: float
    blink: float          # opacidade dos arcos, 0–1
    amber: float          # 0 = ciano, 1 = âmbar
    voice_ring: float
    voice: float


def paint_hud_frame(painter: QPainter, layout: HudLayout, frame: FrameState) -> None:
    cx, cy, R, Rf = layout.cx, layout.cy, layout.R, layout.Rf
    unit = max(.75, R/170.)   # espessuras do protótipo valem para R ≈ 170 px
    rgb = [a+(b-a)*min(1., max(0., frame.amber)) for a, b in zip(FRAME, AMBER)]

    def pen(alpha, width, cap=Qt.FlatCap):
        color = QColor(*map(round, rgb)); color.setAlphaF(min(1., max(0., alpha)))
        return QPen(color, width*unit, Qt.SolidLine, cap)

    def circle(radius):
        return QRectF(cx-radius, cy-radius, 2*radius, 2*radius)

    def radial(angle, r0, r1):
        c, s = math.cos(angle), math.sin(angle)
        painter.drawLine(QPointF(cx+c*r0, cy+s*r0), QPointF(cx+c*r1, cy+s*r1))

    painter.save()
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    painter.setBrush(Qt.NoBrush)
    # Círculo fino e 72 marquinhas que giram (uma maior a cada 30°).
    painter.setPen(pen(.12, 1)); painter.drawEllipse(circle(Rf))
    for i in range(72):
        big = i % 6 == 0
        painter.setPen(pen(.4 if big else .16, 1))
        radial(math.radians(i*5)+frame.tick_rotation, Rf*1.03, Rf*(1.08 if big else 1.05))
    painter.setPen(pen(.6, 1.5))
    for quarter in range(4):
        radial(quarter*math.pi/2, Rf*1.14, Rf*1.22)
    # Anel tracejado, girando ao contrário.
    dashed = pen(.3, 1); dashed.setDashPattern([2, 7])
    painter.save(); painter.translate(cx, cy); painter.rotate(-math.degrees(frame.dash_rotation))
    painter.setPen(dashed); painter.drawEllipse(QRectF(-Rf*.88, -Rf*.88, Rf*1.76, Rf*1.76)); painter.restore()
    # Arcos grossos: uma passada larga e fraca por baixo faz o brilho.
    span = frame.arc_deg*frame.arc_scale
    for center in (180., 0.):
        start = center-span/2-math.degrees(frame.arc_rotation)
        for alpha, width in ((.2, 7), (.9, 2.2)):
            painter.setPen(pen(alpha*frame.blink, width))
            painter.drawArc(circle(Rf*.97), round(start*16), round(span*16))
    ring = .6*frame.voice_ring*frame.voice+.18*min(1., frame.voice_ring*3)
    if ring > .01:
        painter.setPen(pen(ring, 2)); painter.drawEllipse(circle(R*(1.12+.12*frame.voice)))
    # Nível em pontinhos e o nome do estado.
    painter.setPen(Qt.NoPen)
    gap, size, middle = max(3., 5*R/170.), max(1.5, 2*unit), (LEVEL_DOTS-1)/2
    for i in range(LEVEL_DOTS):
        on = abs(i-middle) < frame.level*LEVEL_DOTS/2+.5
        color = QColor(*map(round, rgb)); color.setAlphaF(.95 if on else .18)
        painter.setBrush(color)
        painter.drawRect(QRectF(cx+(i-middle)*gap-size/2, layout.label_y-10*unit, size, size))
    font = QFont(); font.setFamilies(['IBM Plex Mono', 'Consolas']); font.setStyleHint(QFont.Monospace)
    font.setWeight(QFont.Medium)
    pixels, room, count = max(10., .1*R), 2*1.22*Rf, max(1, len(frame.label))
    font.setPixelSize(round(pixels))
    width = QFontMetricsF(font).horizontalAdvance(frame.label)
    if width > room:   # nome longo em orbe pequena: encolhe a letra só depois de zerar o espaçamento
        font.setPixelSize(max(6, int(pixels*room/width)))
        width = QFontMetricsF(font).horizontalAdvance(frame.label)
    spacing = max(0., min(4*unit, (room-width)/count))
    font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    painter.setFont(font)
    color = QColor(*map(round, rgb)); color.setAlphaF(.95); painter.setPen(color)
    # O espaçamento também sobra depois da última letra; meio espaçamento recentra.
    box = QRectF(cx-room/2+spacing/2, layout.label_y, room, 4*pixels)
    painter.drawText(box, Qt.AlignHCenter | Qt.AlignTop | Qt.TextDontClip, frame.label)
    painter.restore()
