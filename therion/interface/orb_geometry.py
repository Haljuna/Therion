"""Forma da orbe holográfica em camadas. Apenas numpy; sem OpenGL.

Raio da esfera = 1. Cada vértice tem 12 floats:
x,y,z, ox,oy,oz (outra ponta da linha), side, layer, spin, detail, glow, seed.
"""
import math
from dataclasses import dataclass
import numpy as np

ANTENNA, CAGE, SHELL, CORE, GYRO, EYE, SPARKS = range(7)
VERTEX_FLOATS = 12
SHELL_RADIUS = .96
_STEP = math.radians(3)        # curvas: no máximo 3° por segmento
_FILL_STEP = math.radians(6)
_TAU = math.tau


@dataclass(frozen=True)
class OrbMesh:
    surfaces: np.ndarray
    lines: np.ndarray
    points: np.ndarray


def _sphere(r, lat, lon):
    lat, lon = np.broadcast_arrays(np.asarray(lat, float), np.asarray(lon, float))
    out = np.stack((r*np.cos(lat)*np.cos(lon), r*np.sin(lat), r*np.cos(lat)*np.sin(lon)), axis=-1)
    return out if out.ndim == 3 else out.reshape(-1, 3)


def _steps(angle, step=_STEP):
    return max(2, math.ceil(abs(angle)/step)+1)


def _arc_xy(r, a0, a1, center=(0., 0., 0.)):
    a = np.linspace(a0, a1, _steps(a1-a0))
    return np.column_stack((r*np.cos(a), r*np.sin(a), np.zeros_like(a)))+center


def _rows(pos, other, side, layer, spin, detail, glow, seed):
    n = len(pos)
    col = lambda v: np.broadcast_to(np.asarray(v, float), (n,))
    return np.column_stack((pos, other, col(side), col(layer), col(spin), col(detail), col(glow), col(seed)))


class _Builder:
    def __init__(self, rng):
        self.rng = rng
        self.surfaces, self.lines, self.points = [], [], []

    def line(self, pts, layer, spin, detail=0, glow=1.):
        """Polilinha → 6 vértices por segmento. A ponta final guarda side invertido,
        porque a direção (outra - posição) se inverte e o shader usa a mesma normal."""
        pts = np.asarray(pts, float)
        g = np.broadcast_to(np.asarray(glow, float), (len(pts),))
        p0, p1, g0, g1 = pts[:-1], pts[1:], g[:-1], g[1:]
        seed = self.rng.random(len(p0))
        corners = ((p0, p1, -1, g0), (p0, p1, 1, g0), (p1, p0, 1, g1),
                   (p1, p0, 1, g1), (p0, p1, 1, g0), (p1, p0, -1, g1))
        quad = [_rows(pos, other, side, layer, spin, detail, gl, seed) for pos, other, side, gl in corners]
        self.lines.append(np.stack(quad, axis=1).reshape(-1, VERTEX_FLOATS))

    def triangles(self, tri, layer, spin, detail=0, glow=.1):
        tri = np.asarray(tri, float).reshape(-1, 3)
        seed = np.repeat(self.rng.random(len(tri)//3), 3)
        self.surfaces.append(_rows(tri, tri, 0, layer, spin, detail, glow, seed))

    def dots(self, pos, layer, spin, detail, glow):
        self.points.append(_rows(pos, pos, 0, layer, spin, detail, glow, self.rng.random(len(pos))))

    def mesh(self):
        stack = lambda parts: np.vstack(parts).astype(np.float32)
        return OrbMesh(stack(self.surfaces), stack(self.lines), stack(self.points))


def _covered(plates, lat, lon):
    hit = np.zeros(len(lat), bool)
    for lat0, lat1, lon0, lon1 in plates:
        hit |= (lat >= lat0) & (lat <= lat1) & (np.mod(lon-lon0, _TAU) <= np.mod(lon1-lon0, _TAU))
    return hit


def shell_plates(seed: int = 419) -> np.ndarray:
    """Placas (lat0, lat1, lon0, lon1) sorteadas até cobrir ~60% da casca."""
    rng = np.random.default_rng(seed)
    probe = np.random.default_rng(7).normal(size=(6000, 3))
    probe /= np.linalg.norm(probe, axis=1)[:, None]
    lat, lon = np.arcsin(probe[:, 1]), np.mod(np.arctan2(probe[:, 2], probe[:, 0]), _TAU)
    plates, hit = [], np.zeros(len(probe), bool)
    while len(plates) < 80 and (len(plates) < 60 or hit.mean() < .58):
        lat0 = rng.uniform(-1.25, 1.15); lat1 = min(1.45, lat0+rng.uniform(.18, .5))
        lon0 = rng.uniform(0, _TAU); lon1 = np.mod(lon0+rng.uniform(.25, .8), _TAU)
        plates.append((lat0, lat1, lon0, lon1))
        hit |= _covered(plates[-1:], lat, lon)
    return np.array(plates)


def _shell(b, rng, seed):
    r = SHELL_RADIUS
    for lat0, lat1, lon0, lon1 in shell_plates(seed):
        dlon = np.mod(lon1-lon0, _TAU); lon1 = lon0+dlon
        top = np.linspace(lon0, lon1, _steps(dlon)); side = np.linspace(lat1, lat0, _steps(lat1-lat0))
        outline = np.vstack((_sphere(r, lat1, top), _sphere(r, side, lon1),
                             _sphere(r, lat0, top[::-1]), _sphere(r, side[::-1], lon0)))
        b.line(outline, SHELL, 1.)
        la = np.linspace(lat0, lat1, _steps(lat1-lat0, _FILL_STEP))
        lo = np.linspace(lon0, lon1, _steps(dlon, _FILL_STEP))
        grid = _sphere(r, la[:, None], lo[None, :]).reshape(len(la), len(lo), 3)
        a, c, d, e = grid[:-1, :-1], grid[1:, :-1], grid[:-1, 1:], grid[1:, 1:]
        b.triangles(np.stack((a, c, d, d, c, e), axis=2), SHELL, 1., glow=rng.uniform(.10, .18))
        if rng.random() < .3:
            if rng.random() < .5:
                b.line(_sphere(r, side, lon0+dlon/2), SHELL, 1., detail=1)
            else:
                for f in (1/3, 2/3):
                    b.line(_sphere(r, lat0+(lat1-lat0)*f, top), SHELL, 1., detail=1)


def _cage(b):
    half = math.radians(4)
    for row, lat in enumerate(np.radians(np.arange(-60, 61, 3))):
        for lon in np.radians(np.arange(0, 360, 60)):
            b.line(_sphere(1., lat, np.linspace(lon-half, lon+half, _steps(2*half))),
                   CAGE, 1., detail=row % 2, glow=.9)


def _antenna(b):
    b.line([[0, 1., 0], [0, 1.18, 0]], ANTENNA, 1., glow=.8)
    b.line(_arc_xy(.12, math.radians(60), math.pi, center=(.10, 1., 0)), ANTENNA, 1., glow=.8)


_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7))
_FACES = ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5))


def _core(b, rng):
    for i in range(60):
        detail = 1 if i < 51 else 0
        lat, lon, r = rng.uniform(-1, 1), rng.uniform(0, _TAU), rng.uniform(.25, .8)
        w, d, h = rng.uniform(.04, .13), rng.uniform(.04, .13), rng.uniform(.07, .30)
        corner = np.array([[x, y, z] for x in (-w/2, w/2) for y in (-h/2, h/2) for z in (-d/2, d/2)])
        c, s = math.cos(lon), math.sin(lon)
        corner = corner@np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])+_sphere(r, lat, lon)
        for p, q in _EDGES:
            b.line(corner[[p, q]], CORE, -.5, detail=detail, glow=.6)
        quads = corner[np.array(_FACES)]
        b.triangles(quads[:, [0, 1, 2, 0, 2, 3]], CORE, -.5, detail=detail, glow=.05)


def _gyro(b):
    for start in (0, 120, 240):
        b.line(_arc_xy(.55, math.radians(start), math.radians(start+100)), GYRO, 1.5, glow=1.)


def _eye(b, rng):
    b.line(_arc_xy(.10, 0, _TAU), EYE, 0., glow=1.6)
    b.line(_arc_xy(.05, 0, _TAU), EYE, 0., glow=1.2)
    comet = _arc_xy(.16, 0, math.radians(270))
    b.line(comet, EYE, 2., glow=np.linspace(0, 1.8, len(comet)))
    r, a = .05*np.sqrt(rng.random(300)), rng.uniform(0, _TAU, 300)
    core = np.column_stack((r*np.cos(a), r*np.sin(a), rng.normal(0, .01, 300)))
    b.dots(core, EYE, 0., 0, 2.)


def _sparks(b, rng):
    n = 1500
    v = rng.normal(size=(n, 3)); v /= np.linalg.norm(v, axis=1)[:, None]
    r = rng.uniform(.3, 1.05, n)
    detail = (np.arange(n) < 1050).astype(float)
    b.dots(v*r[:, None], SPARKS, np.where(r < .8, -.5, 1.), detail, rng.uniform(.4, 1.2, n))


def build_orb(seed: int = 419) -> OrbMesh:
    rng = np.random.default_rng(seed)
    b = _Builder(rng)
    _antenna(b); _cage(b); _shell(b, rng, seed); _core(b, rng); _gyro(b); _eye(b, rng); _sparks(b, rng)
    return b.mesh()
