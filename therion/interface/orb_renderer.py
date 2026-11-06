"""Desenho OpenGL da orbe holográfica. Apenas apresentação; sem acesso a serviços."""
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
from .graphics import FRAME_INTERVAL_MS
from .orb_geometry import build_orb, VERTEX_FLOATS
from .orb_motion import OrbMotion, THINKING_STATES
from .orb_shaders import SCENE_VERTEX, SCENE_FRAGMENT, QUAD_VERTEX, BLOOM_FRAGMENT
from .presentation import QualityController
from .scene_motion import SceneMotion

THINKING_INTERVAL_MS = 33
STRIDE = VERTEX_FLOATS*4
_GL_FLOAT, _TRIANGLES, _POINTS, _STRIP = 0x1406, 0x0004, 0x0000, 0x0005


def line_width_px(orb_px: float) -> float:
    return max(1., 1.2*max(0., float(orb_px))/500.)


def detail_level(orb_px: float) -> float:
    t = min(1., max(0., (float(orb_px)-200.)/120.))
    return t*t*(3.-2.*t)


def frame_interval_ms(state: str) -> int:
    return THINKING_INTERVAL_MS if state in THINKING_STATES else FRAME_INTERVAL_MS


def bloom_levels(quality: str, state: str) -> int:
    levels = QualityController.BLOOM_LEVELS.get(quality, 2)
    return min(levels, 2) if state in THINKING_STATES else levels


class OrbGL(QOpenGLWidget):
    failed = Signal(str)
    metrics = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        fmt.setSwapInterval(0)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setMinimumSize(160, 160)
        self.quality = QualityController()
        self.state = 'idle'
        self.focus_rect = None
        self.animation = OrbMotion()
        self.scene_motion = SceneMotion()
        self.reduced = False
        self.ready = False
        self.disabled = False
        self.program = self.bloom = self.quad = None
        self.buffers = {}
        self.failure_detail = ''
        self.last_frame = None
        self.frame_times = []
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(FRAME_INTERVAL_MS)
        self.timer.timeout.connect(self.update)

    def initializeGL(self):
        try:
            self.gl = self.context().functions()
            self.program = self._program(SCENE_VERTEX, SCENE_FRAGMENT)
            self.bloom = self._program(QUAD_VERTEX, BLOOM_FRAGMENT)
            mesh = build_orb()
            for name in ('surfaces', 'lines', 'points'):
                data = getattr(mesh, name)
                self.buffers[name] = (self._buffer(data.tobytes()), len(data))
            self.quad = self._buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='float32').tobytes())
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.ready = True
        except Exception as error:
            self.ready = False
            self.failure_detail = str(error)
            self.failed.emit('Animação indisponível: não foi possível iniciar OpenGL.')

    @staticmethod
    def _buffer(raw):
        buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        buffer.create(); buffer.bind(); buffer.allocate(raw, len(raw)); buffer.release()
        return buffer

    def _program(self, vertex, fragment):
        program = QOpenGLShaderProgram(self)
        if not (program.addShaderFromSourceCode(QOpenGLShader.Vertex, vertex)
                and program.addShaderFromSourceCode(QOpenGLShader.Fragment, fragment)
                and program.link()):
            raise RuntimeError(program.log())
        return program

    def set_visual(self, state, intensity):
        changed = state != self.state
        self.state = state
        self.animation.set_visual(state, intensity)
        if self.reduced and changed:
            self.animation.advance(0., reduced=True)
            self.update()

    def set_quality(self, quality):
        self.quality = QualityController(quality)
        self.last_frame = None
        self.update()

    def _focus(self):
        return (self.focus_rect or QRectF(self.rect())).intersected(QRectF(self.rect()))

    def current_detail(self):
        focus = self._focus()
        return detail_level(min(focus.width(), focus.height()))

    def paintGL(self):
        try:
            self._paint_frame()
        except Exception:
            self.ready = False
            self.timer.stop()
            self.failed.emit('Animação indisponível: houve uma falha na renderização OpenGL.')

    def _observe(self, now):
        if self.last_frame:
            elapsed = now-self.last_frame
            self.frame_times.append(elapsed)
            self.quality.observe(elapsed)
            if len(self.frame_times) >= 60:
                self.metrics.emit({'fps': round(len(self.frame_times)/sum(self.frame_times), 1),
                                   'frame_ms': round(1000*sum(self.frame_times)/len(self.frame_times), 2),
                                   'quality': self.quality.level,
                                   'detail': round(self.current_detail(), 2)})
                self.frame_times.clear()

    def _paint_frame(self):
        if not self.ready:
            return
        now = time.monotonic()
        dt = min(.1, now-self.last_frame) if self.last_frame else 0.
        self._observe(now)
        self.last_frame = now
        attention = getattr(self, 'scene_attention', 1.)
        self.animation.advance(dt*attention, reduced=self.reduced)
        self.scene_attention = attention+(getattr(self, 'target_scene_attention', 1.)-attention)*(1.-math.exp(-dt/.14))
        self.scene_motion.advance(dt*self.scene_attention, reduced=self.reduced)
        width = max(1, round(self.width()*self.devicePixelRatioF()))
        height = max(1, round(self.height()*self.devicePixelRatioF()))
        gl = self.gl
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(9/255, 9/255, 15/255, 1.); gl.glClear(0x4000)
        gl.glEnable(0x0BE2)   # GL_BLEND
        gl.glBlendFunc(1, 1)  # emissão aditiva: ONE, ONE
        gl.glEnable(0x8642)   # tamanho de ponto programável
        gl.glEnable(0x8861)   # point sprites (contexto de compatibilidade)
        self._aura(width, height)
        self._scene(width, height)
        gl.glDisable(0x0BE2)

    def _aura(self, width, height):
        """Halo e reflexo no chão (sem textura nesta etapa)."""
        b = self.bloom; gl = self.gl
        b.bind(); self.quad.bind()
        b.enableAttributeArray('position'); b.setAttributeBuffer('position', _GL_FLOAT, 0, 2, 8)
        focus = self._focus()
        gl.glUniform4f(b.uniformLocation('params'), 0., 0., 0., float(width/height))
        gl.glUniform4f(b.uniformLocation('anchor'),
                       focus.center().x()/max(1, self.width()),
                       1.-focus.center().y()/max(1, self.height())+.0275*focus.height()/max(1, self.height()),
                       focus.height()/max(1, self.height()), focus.width()/max(1, self.width()))
        a = self.animation
        gl.glUniform4f(b.uniformLocation('aura'), a.phase, a.energy, float(not self.reduced), a.pulse)
        gl.glDrawArrays(_STRIP, 0, 4)
        b.disableAttributeArray('position'); self.quad.release(); b.release()

    def _scene(self, width, height):
        p = self.program; gl = self.gl; a = self.animation
        focus = self._focus()
        ratio = self.devicePixelRatioF()
        p.bind()
        uniform = lambda name, *v: getattr(gl, f'glUniform{len(v)}f')(p.uniformLocation(name), *map(float, v))
        uniform('spin', a.spin); uniform('clock', a.clock)
        uniform('detailLevel', self.current_detail())
        uniform('lineWidth', line_width_px(min(focus.width(), focus.height()))*ratio)
        uniform('pointSize', max(1., 2.2*min(focus.width(), focus.height())/500.)*ratio)
        uniform('aspect', width/height)
        uniform('fit', min(focus.height()/max(1, self.height()), focus.width()/max(1, self.height())*1.05))
        uniform('center', 2.*focus.center().x()/max(1, self.width())-1.,
                1.-2.*focus.center().y()/max(1, self.height())+.055*focus.height()/max(1, self.height()))
        uniform('viewport', width, height)
        uniform('eye', a.eye); uniform('tint', a.tint); uniform('rim', a.rim)
        uniform('flash', a.flash); uniform('assembly', a.assembly); uniform('energy', a.energy)
        for name, mode in (('surfaces', _TRIANGLES), ('lines', _TRIANGLES), ('points', _POINTS)):
            buffer, count = self.buffers[name]
            uniform('isPoint', mode == _POINTS)
            buffer.bind()
            for attr, offset, size in (('position', 0, 3), ('other', 12, 3), ('meta', 24, 4), ('extra', 40, 2)):
                p.enableAttributeArray(attr); p.setAttributeBuffer(attr, _GL_FLOAT, offset, size, STRIDE)
            gl.glDrawArrays(mode, 0, count)
            for attr in ('position', 'other', 'meta', 'extra'):
                p.disableAttributeArray(attr)
            buffer.release()
        p.release()

    def set_active(self, active):
        if active and not self.reduced and not self.disabled:
            self.last_frame = None
            self.timer.start()
        else:
            self.timer.stop()
        if active:
            self.update()

    def cleanup(self):
        self.timer.stop()
        if not self.ready: return
        self.ready = False
        context = self.context()
        if context is None or not context.isValid(): return
        try: context.aboutToBeDestroyed.disconnect(self.cleanup)
        except (RuntimeError, TypeError): pass
        self.makeCurrent()
        for buffer in [b for b, _ in self.buffers.values()]+[self.quad]:
            if buffer is not None:
                buffer.destroy()
        self.buffers = {}; self.quad = None
        self.program = self.bloom = None
        self.doneCurrent()
        self.gl = None
