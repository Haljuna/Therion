"""Desenho OpenGL da orbe holográfica. Apenas apresentação; sem acesso a serviços."""
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QSize
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                             QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat)
from .graphics import FRAME_INTERVAL_MS
from .orb_geometry import build_orb, VERTEX_FLOATS
from .orb_motion import OrbMotion, THINKING_STATES
from .orb_shaders import (SCENE_VERTEX, SCENE_FRAGMENT, QUAD_VERTEX, BLOOM_FRAGMENT,
                          BLUR_FRAGMENT, COMPOSITE_FRAGMENT)
from .presentation import QualityController
from .scene_motion import SceneMotion

THINKING_INTERVAL_MS = 33
STRIDE = VERTEX_FLOATS*4
_GL_FLOAT, _TRIANGLES, _POINTS, _STRIP = 0x1406, 0x0004, 0x0000, 0x0005
_TEXTURE_2D, _LINEAR, _CLAMP = 0x0DE1, 0x2601, 0x812F
GLOW_WEIGHTS = (.55, .45, .35)
GROUP_GAIN = {'surfaces': .45, 'lines': .85, 'points': 1.}


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
        self.program = self.bloom = self.quad = self.blur = self.composite = None
        self.scene_ms = self.scene_fbo = None
        self._chain = []   # pares (temporário, saída) por escala de brilho
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
            self.blur = self._program(QUAD_VERTEX, BLUR_FRAGMENT)
            self.composite = self._program(QUAD_VERTEX, COMPOSITE_FRAGMENT)
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
        levels = bloom_levels(self.quality.level, self.state)
        self._ensure_targets(width, height, levels)
        gl.glEnable(0x8642)   # tamanho de ponto programável
        gl.glEnable(0x8861)   # point sprites (contexto de compatibilidade)
        # 1. Cena num FBO com MSAA, resolvida para uma textura.
        self.scene_ms.bind()
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(0., 0., 0., 1.); gl.glClear(0x4000)
        gl.glEnable(0x0BE2); gl.glBlendFunc(1, 1)   # emissão aditiva: ONE, ONE
        self._scene(width, height)
        gl.glDisable(0x0BE2)
        QOpenGLFramebufferObject.blitFramebuffer(self.scene_fbo, self.scene_ms)
        # 2. Brilho: cada escala desfoca a anterior (1/2, 1/4, 1/8).
        source = self.scene_fbo
        for temp, out in self._chain:
            self._blur_pass(source, temp, (1./source.width(), 0.))
            self._blur_pass(temp, out, (0., 1./temp.height()))
            source = out
        # 3. Fundo, halo e chão; depois cena e brilho somados.
        gl.glBindFramebuffer(0x8D40, self.defaultFramebufferObject())
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(9/255, 9/255, 15/255, 1.); gl.glClear(0x4000)
        gl.glEnable(0x0BE2); gl.glBlendFunc(1, 1)
        self._aura(width, height)
        self._composite()
        gl.glDisable(0x0BE2)

    def bloom_chain_sizes(self):
        return [out.size() for _, out in self._chain]

    def _target(self, size, samples=0):
        fmt = QOpenGLFramebufferObjectFormat(); fmt.setSamples(samples)
        fbo = QOpenGLFramebufferObject(size, fmt)
        if not samples:
            gl = self.gl
            gl.glBindTexture(_TEXTURE_2D, fbo.texture())
            for name, value in ((0x2801, _LINEAR), (0x2800, _LINEAR), (0x2802, _CLAMP), (0x2803, _CLAMP)):
                gl.glTexParameteri(_TEXTURE_2D, name, value)
            gl.glBindTexture(_TEXTURE_2D, 0)
        return fbo

    def _ensure_targets(self, width, height, levels):
        size = QSize(width, height)
        if self.scene_fbo is None or self.scene_fbo.size() != size:
            self.scene_ms = self._target(size, 4)
            self.scene_fbo = self._target(size)
            self._chain = []
        if len(self._chain) != levels:
            self._chain = []
            for i in range(1, levels+1):
                small = QSize(max(1, round(width/2**i)), max(1, round(height/2**i)))
                self._chain.append((self._target(small), self._target(small)))

    def _quad(self, program):
        self.quad.bind()
        program.enableAttributeArray('position'); program.setAttributeBuffer('position', _GL_FLOAT, 0, 2, 8)
        self.gl.glDrawArrays(_STRIP, 0, 4)
        program.disableAttributeArray('position'); self.quad.release()

    def _blur_pass(self, source, target, step):
        gl = self.gl; b = self.blur
        target.bind(); gl.glViewport(0, 0, target.width(), target.height())
        b.bind()
        gl.glActiveTexture(0x84C0); gl.glBindTexture(_TEXTURE_2D, source.texture())
        gl.glUniform1i(b.uniformLocation('image'), 0)
        gl.glUniform2f(b.uniformLocation('step'), *step)
        self._quad(b); b.release()

    def _composite(self):
        gl = self.gl; c = self.composite
        c.bind()
        textures = [self.scene_fbo.texture()]+[out.texture() for _, out in self._chain]
        textures += [self.scene_fbo.texture()]*(4-len(textures))
        for unit, (name, texture) in enumerate(zip(('scene', 'glow0', 'glow1', 'glow2'), textures)):
            gl.glActiveTexture(0x84C0+unit); gl.glBindTexture(_TEXTURE_2D, texture)
            gl.glUniform1i(c.uniformLocation(name), unit)
        weights = [w if i < len(self._chain) else 0. for i, w in enumerate(GLOW_WEIGHTS)]
        gl.glUniform3f(c.uniformLocation('weights'), *weights)
        self._quad(c); c.release()
        for unit in range(4):
            gl.glActiveTexture(0x84C0+unit); gl.glBindTexture(_TEXTURE_2D, 0)
        gl.glActiveTexture(0x84C0)

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
        uniform('relief', 0. if self.reduced else a.relief)
        for name, mode in (('surfaces', _TRIANGLES), ('lines', _TRIANGLES), ('points', _POINTS)):
            buffer, count = self.buffers[name]
            uniform('isPoint', mode == _POINTS); uniform('groupGain', GROUP_GAIN[name])
            buffer.bind()
            for attr, offset, size in (('position', 0, 3), ('other', 12, 3), ('meta', 24, 4),
                                       ('extra', 40, 2), ('rise', 48, 2)):
                p.enableAttributeArray(attr); p.setAttributeBuffer(attr, _GL_FLOAT, offset, size, STRIDE)
            gl.glDrawArrays(mode, 0, count)
            for attr in ('position', 'other', 'meta', 'extra', 'rise'):
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
        self.scene_ms = self.scene_fbo = None; self._chain = []
        self.program = self.bloom = self.blur = self.composite = None
        self.doneCurrent()
        self.gl = None
