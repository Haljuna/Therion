"""Posição da mini orbe flutuante: funções puras sobre QRect/QPoint/QSize em coordenadas lógicas.

`screens` são as áreas úteis (sem barra de tarefas).
"""
import json
import os

from PySide6.QtCore import QPoint, QRect, QSize


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
