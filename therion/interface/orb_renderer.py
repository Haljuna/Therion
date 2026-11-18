"""Desenho OpenGL da Orbe HUD. Apenas apresentação; sem acesso a serviços."""
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QRectF, QSize
from PySide6.QtGui import QImage, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                             QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat)
from .graphics import FRAME_INTERVAL_MS
from .hud_frame import paint_hud_frame
from .hud_style import AMBER, CORE, DOT, FRAME, HOT, hud_layout, point_count
from .orb_geometry import build_orb, VERTEX_FLOATS
from .orb_motion import OrbMotion, THINKING_STATES
from .orb_shaders import (SCENE_VERTEX, SCENE_FRAGMENT, QUAD_VERTEX, AURA_FRAGMENT,
                          BLUR_FRAGMENT, COMPOSITE_FRAGMENT, TRAIL_FRAGMENT)
from .presentation import QualityController
from .scene_motion import SceneMotion

THINKING_INTERVAL_MS = 33
STRIDE = VERTEX_FLOATS*4
_GL_FLOAT, _TRIANGLES, _POINTS, _STRIP = 0x1406, 0x0004, 0x0000, 0x0005
_TEXTURE_2D, _LINEAR, _CLAMP = 0x0DE1, 0x2601, 0x812F
GLOW_WEIGHTS = (.55, .45, .35)
# Ponto suave e redondo com luz parecida com a do quadradinho do protótipo (que valia para 2600 pontos e R = 170).
POINT_SCALE = 2.7


def line_width_px(orb_px: float) -> float:
    return max(1., 1.2*max(0., float(orb_px))/500.)


def point_size_px(radius_px: float, points: int) -> float:
    return POINT_SCALE*math.sqrt(2600./max(1, points))*max(0., float(radius_px))/170.


def shader_clocks(animation) -> dict:
    """Relógios dobrados em períodos exatos: o shader recebe float32, e depois de horas
    ligada os valores crus perderiam precisão e o movimento andaria aos trancos."""
    return {'clock': animation.clock % (10.*math.pi),      # todas as frequências são múltiplas de 0,2
            'spin': animation.spin % (20.*math.pi),        # usado ×1, ×0,3 e ×0,5
            'orbitPhase': animation.orbit_phase % 20.,     # velocidades 0,7 · 0,5 · 0,35
            'sweepPhase': animation.sweep_phase % math.tau}


def trail_keep(trail: float, dt: float) -> float:
    """Fração do quadro anterior mantida: ~2 quadros parado, ~0,5 s no giro mais rápido."""
    return math.exp(-max(0., dt)/(.02+.16*trail))


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
        fmt.setSamples(0)   # a cena tem MSAA própria (scene_ms); a janela só recebe quadros cheios
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
        self.min_interval_ms = 0   # a mini orbe pede 33: o piso do intervalo; 0 deixa a orbe grande como está
        self.program = self.aura = self.quad = self.blur = self.composite = self.trail = None
        self._trail_fresh = True
        self.scene_ms = self.scene_fbo = None
        self._chain = []   # pares (temporário, saída) por escala de brilho
        self._trail = []   # dois FBOs alternados para o rastro
        self.trail_cleared = False
        self._was_reduced = False
        self.buffers = {}
        self.point_count = 0
        self._frame_image = None
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
            self.aura = self._program(QUAD_VERTEX, AURA_FRAGMENT)
            self.blur = self._program(QUAD_VERTEX, BLUR_FRAGMENT)
            self.composite = self._program(QUAD_VERTEX, COMPOSITE_FRAGMENT)
            self.trail = self._program(QUAD_VERTEX, TRAIL_FRAGMENT)
            lines = build_orb(0).lines
            self.buffers['lines'] = (self._buffer(lines.tobytes()), len(lines))
            self._ensure_points()
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
        # Enquanto o modelo usa a placa (pensando/executando), a orbe desenha a 30 quadros/s.
        # Só quando muda: setInterval reinicia o timer, e o painel chama isto a cada 50 ms.
        interval = max(frame_interval_ms(state), self.min_interval_ms)
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        if self.reduced and changed:
            self.animation.advance(0., reduced=True)
            self.update()

    def set_quality(self, quality):
        self.quality = QualityController(quality)
        self.last_frame = None
        self.update()

    def _focus(self):
        return (self.focus_rect or QRectF(self.rect())).intersected(QRectF(self.rect()))

    def _layout(self):
        focus = self._focus()
        return hud_layout(focus.x(), focus.y(), focus.width(), focus.height())

    def _ensure_points(self):
        """A quantidade de pontos segue a qualidade e o tamanho; ao mudar, só esse buffer é refeito."""
        focus = self._focus()
        wanted = point_count(self.quality.level, min(focus.width(), focus.height()))
        if wanted == self.point_count and 'points' in self.buffers:
            return
        if 'points' in self.buffers:
            self.buffers['points'][0].destroy()
        data = build_orb(wanted).points
        self.buffers['points'] = (self._buffer(data.tobytes()), len(data))
        self.point_count = wanted

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
                                   'quality': self.quality.level, 'points': self.point_count})
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
        self._ensure_points()
        gl.glEnable(0x809D)   # multisample: o QPainter da moldura desliga a cada quadro
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
        # 2. Rastro: só em pensando/executando; no resto borraria os pontos.
        trail = self.animation.trail
        keep = trail_keep(trail, dt)
        clear = (self.reduced or (self.reduced != self._was_reduced) or trail < .01 or keep < .01
                 or self._trail_fresh)
        self._was_reduced = self.reduced; self._trail_fresh = False
        self.trail_cleared = clear
        source = self._trail_pass(0. if clear else keep)
        # 3. Brilho: cada escala desfoca a anterior (1/2, 1/4, 1/8).
        for temp, out in self._chain:
            self._blur_pass(source, temp, (1./source.width(), 0.))
            self._blur_pass(temp, out, (0., 1./temp.height()))
            source = out
        # 4. Fundo e núcleo; depois cena e brilho somados; por fim a moldura, nítida, por cima.
        gl.glBindFramebuffer(0x8D40, self.defaultFramebufferObject())
        gl.glViewport(0, 0, width, height)
        gl.glClearColor(9/255, 9/255, 15/255, 1.); gl.glClear(0x4000)
        gl.glEnable(0x0BE2); gl.glBlendFunc(1, 1)
        self._aura(width, height)
        self._composite(self._trail[0])
        gl.glDisable(0x0BE2)
        self._paint_hud()

    def _paint_hud(self):
        """A moldura é desenhada numa imagem (com suavização de verdade) e colada por cima:
        o pintor OpenGL do Qt só suaviza com multisample, que a janela não tem."""
        lay = self._layout(); ratio = self.devicePixelRatioF()
        reach = 1.25*lay.Rf   # as marcas fixas vão até 1,22 Rf
        left, top = math.floor(lay.cx-reach), math.floor(lay.cy-reach)
        width = math.ceil(2*reach)+1
        height = math.ceil(lay.label_y+max(22., .3*lay.R))-top
        size = QSize(round(width*ratio), round(height*ratio))
        if self._frame_image is None or self._frame_image.size() != size:
            self._frame_image = QImage(size, QImage.Format_ARGB32_Premultiplied)
            self._frame_image.setDevicePixelRatio(ratio)
        image = self._frame_image
        image.fill(0)
        painter = QPainter(image)
        painter.translate(-left, -top)
        paint_hud_frame(painter, lay, self.animation.frame_state())
        painter.end()
        painter = QPainter(self)
        painter.drawImage(left, top, image)
        painter.end()

    def _trail_pass(self, keep):
        gl = self.gl; t = self.trail
        target, previous = self._trail[1], self._trail[0]
        target.bind(); gl.glViewport(0, 0, target.width(), target.height())
        t.bind()
        for unit, (name, fbo) in enumerate((('scene', self.scene_fbo), ('previous', previous))):
            gl.glActiveTexture(0x84C0+unit); gl.glBindTexture(_TEXTURE_2D, fbo.texture())
            gl.glUniform1i(t.uniformLocation(name), unit)
        gl.glUniform1f(t.uniformLocation('keep'), float(keep))
        self._quad(t); t.release()
        gl.glActiveTexture(0x84C1); gl.glBindTexture(_TEXTURE_2D, 0); gl.glActiveTexture(0x84C0)
        self._trail.reverse()   # o recém-desenhado vira o "anterior" do próximo quadro
        return self._trail[0]

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
            self._trail = [self._target(size), self._target(size)]
            self._trail_fresh = True
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

    def _composite(self, scene):
        gl = self.gl; c = self.composite
        c.bind()
        textures = [scene.texture()]+[out.texture() for _, out in self._chain]
        textures += [scene.texture()]*(4-len(textures))
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
        """Núcleo roxo atrás da esfera e halo largo."""
        b = self.aura; gl = self.gl; a = self.animation; lay = self._layout()
        b.bind()
        gl.glUniform4f(b.uniformLocation('anchor'), lay.cx/max(1, self.width()), 1.-lay.cy/max(1, self.height()),
                       lay.R/max(1, self.height()), float(width/height))
        gl.glUniform1f(b.uniformLocation('strength'), a.look.core+.35*a.voice+.1*a.energy+.08*a.pulse)
        gl.glUniform3f(b.uniformLocation('colCore'), *(c/255. for c in CORE))
        self._quad(b); b.release()

    def _scene(self, width, height):
        p = self.program; gl = self.gl; a = self.animation; look = a.look; lay = self._layout()
        ratio = self.devicePixelRatioF()
        still = self.reduced   # modo reduzido: sem ondulação nem giro
        p.bind()
        uniform = lambda name, *v: getattr(gl, f'glUniform{len(v)}f')(p.uniformLocation(name), *map(float, v))
        for name, value in (*shader_clocks(a).items(), ('ripple', 0. if still else look.ripple),
                            ('sweep', look.sweep),
                            ('listenWave', look.listen_wave), ('energy', a.energy), ('voice', a.voice),
                            ('breathe', 0. if still else look.breathe), ('dim', look.dim),
                            ('amber', look.amber), ('jitter', 0. if still else look.jitter),
                            ('assembly', a.assembly), ('flash', a.flash),
                            ('pointSize', point_size_px(lay.R, self.point_count)*ratio),
                            ('radiusPx', lay.R*ratio), ('lineWidth', line_width_px(lay.R/.215)*ratio),
                            ('aspect', width/height), ('fit', 2.*lay.R/max(1, self.height()))):
            uniform(name, value)
        uniform('center', 2.*lay.cx/max(1, self.width())-1., 1.-2.*lay.cy/max(1, self.height()))
        uniform('viewport', width, height)
        for name, color in (('colDot', DOT), ('colHot', HOT), ('colFrame', FRAME), ('colAmber', AMBER)):
            uniform(name, *(c/255. for c in color))
        for name, mode in (('lines', _TRIANGLES), ('points', _POINTS)):
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
        self.scene_ms = self.scene_fbo = None; self._chain = []; self._trail = []
        self.program = self.aura = self.blur = self.composite = self.trail = None
        self.doneCurrent()
        self.gl = None
