"""Forma da Orbe HUD: esfera de pontos, órbitas e eixo. Apenas numpy; sem OpenGL.

Raio da esfera = 1. Cada vértice tem 14 floats:
x,y,z, ox,oy,oz (outra ponta da linha), side, layer, spin, detail, glow, seed, lift, olift.
Em ORBIT e RUNNER, spin = índice da órbita. Em RUNNER, posição e "outra" são os pontos
da órbita a 0° e 90° (o shader anda entre eles) e detail = velocidade relativa.
"""
import math
from dataclasses import dataclass
import numpy as np

DOTS, ORBIT, AXIS, RUNNER = range(4)
VERTEX_FLOATS = 14
# (raio, inclinação em X e Y em radianos, velocidade), do protótipo.
ORBITS = ((1.24, (1.4, -0.6), 0.7), (1.32, (0.9, 0.3), 0.5), (1.42, (-0.5, 1.1), -0.35))
AXIS_RADIUS, AXIS_TILT = 1.55, .3
_SEGMENTS = 120   # 3° por segmento


@dataclass(frozen=True)
class OrbMesh:
    surfaces: np.ndarray
    lines: np.ndarray
    points: np.ndarray


def fib_sphere(n: int) -> np.ndarray:
    """n pontos espalhados por igual na esfera unitária (espiral de Fibonacci)."""
    i = np.arange(n)
    y = 1.-(i+.5)/n*2.
    r, a = np.sqrt(1.-y*y), i*2.39996
    return np.column_stack((np.cos(a)*r, y, np.sin(a)*r))


def _rot_x(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.column_stack((p[:, 0], p[:, 1]*c-p[:, 2]*s, p[:, 1]*s+p[:, 2]*c))


def _rot_y(p, a):
    c, s = math.cos(a), math.sin(a)
    return np.column_stack((p[:, 0]*c+p[:, 2]*s, p[:, 1], -p[:, 0]*s+p[:, 2]*c))


def _rows(pos, other, side, layer, spin, detail, glow, seed):
    n = len(pos)
    col = lambda v: np.broadcast_to(np.asarray(v, float), (n,))
    return np.column_stack((pos, other, col(side), col(layer), col(spin), col(detail), col(glow), col(seed),
                            col(0.), col(0.)))


def _line(pts, layer, spin, glow):
    """Polilinha → 6 vértices por segmento. A ponta final guarda side invertido,
    porque a direção (outra - posição) se inverte e o shader usa a mesma normal."""
    p0, p1 = pts[:-1], pts[1:]
    corners = ((p0, p1, -1), (p0, p1, 1), (p1, p0, 1), (p1, p0, 1), (p0, p1, 1), (p1, p0, -1))
    quad = [_rows(pos, other, side, layer, spin, 0., glow, 0.) for pos, other, side in corners]
    return np.stack(quad, axis=1).reshape(-1, VERTEX_FLOATS)


def build_orb(points: int = 3200, seed: int = 419) -> OrbMesh:
    rng = np.random.default_rng(seed)
    sphere = fib_sphere(points)
    dots, lines = [_rows(sphere, sphere, 0., DOTS, 0., 0., 1., rng.random(points))], []
    angle = np.linspace(0., math.tau, _SEGMENTS+1)
    for index, (radius, (tilt_x, tilt_y), speed) in enumerate(ORBITS):
        ring = np.column_stack((np.cos(angle)*radius, np.zeros_like(angle), np.sin(angle)*radius))
        ring = _rot_y(_rot_x(ring, tilt_x), tilt_y)
        lines.append(_line(ring, ORBIT, index, .55))
        quarter = _SEGMENTS//4
        dots.append(_rows(ring[:1], ring[quarter:quarter+1], 0., RUNNER, index, speed, 1., 0.))
    axis = _rot_x(np.array([[0., -AXIS_RADIUS, 0.], [0., AXIS_RADIUS, 0.]]), AXIS_TILT)
    lines.append(_line(axis, AXIS, 0., .35))
    dots.append(_rows(axis, axis, 0., AXIS, 0., 0., .9, 0.))
    stack = lambda parts: np.vstack(parts).astype(np.float32)
    return OrbMesh(np.zeros((0, VERTEX_FLOATS), np.float32), stack(lines), stack(dots))
