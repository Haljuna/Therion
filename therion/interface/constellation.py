"""Campo de partículas Obsidiana. Apenas apresentação; sem acesso a serviços."""
import math
import os
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QSurfaceFormat
from PySide6.QtWidgets import QWidget, QStackedWidget, QLabel
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                             QOpenGLFramebufferObject)
from .presentation import QualityController
from .graphics import FRAME_INTERVAL_MS
from .orb_motion import OrbMotion
from .scene_motion import SceneMotion


VERTEX = """
#version 120
attribute vec4 particle;
attribute vec4 detail;
uniform float clock, aspect, fit, energy, tension, life, pixelRatio, glowPass;
uniform vec2 center;
uniform vec4 mode, presence, expression;
varying float emission, temperature, sparkle;
void main() {
    float seed=particle.w;
    float radial=mix(.16,1.18,pow(seed,.65));
    vec3 p=particle.xyz*radial;
    float phase=clock*.22;
    float flow=atan(p.z,p.x)+phase*(.18+seed*.18);
    float wave=sin(p.y*5.+flow*3.-phase*1.3);
    p.xz=mat2(cos(phase),-sin(phase),sin(phase),cos(phase))*p.xz;
    p.y+=life*.10*wave*(.3+seed);
    p.x+=life*.07*sin(flow*2.+phase);
    // Gathering is a state gesture; only measured audio drives expansion.
    p*=1.-mode.y*.16+energy*.18+expression.x*.08;
    p.y*=1.+presence.x*.12-presence.y*.08;
    float depth=1./(3.1-p.z*.48);
    gl_Position=vec4(p.x*depth*2.05*fit/aspect+center.x,
                     p.y*depth*2.05*fit+center.y,0.,1.);
    sparkle=smoothstep(.96,1.,seed);
    temperature=seed;
    gl_PointSize=pixelRatio*(1.15+seed*1.5+sparkle*1.4)*(glowPass>.5?1.4:1.);
    // Núcleo mais luminoso que a poeira externa: a orbe mantém presença.
    float core=1.-smoothstep(.16,1.,radial);
    emission=(.17+seed*.30+sparkle*.26+core*.22)*(1.+energy*.38);
}
"""
FRAGMENT = """
#version 120
uniform float glowPass;
uniform vec4 mode;
varying float emission, temperature, sparkle;
void main() {
    float r=length(gl_PointCoord-vec2(.5))*2.;
    if(r>1.)discard;
    float light=exp(-r*r*3.)*(1.-smoothstep(.7,1.,r));
    vec3 color=mix(vec3(.40,.24,.78),vec3(.79,.68,1.),temperature);
    color=mix(color,vec3(.95,.93,1.),sparkle*.7);
    color=mix(color,vec3(.99,.83,.30),mode.z*.65);
    color=mix(color,vec3(.99,.42,.47),mode.w*.75);
    gl_FragColor=vec4(color*light*emission*(glowPass>.5?.38:1.),0.);
}
"""
QUAD_VERTEX = '''
#version 120
attribute vec2 position;
varying vec2 uv;
void main() { uv = position*.5+.5; gl_Position=vec4(position,0.,1.); }
'''
BLOOM_FRAGMENT = '''
#version 120
uniform sampler2D image;
uniform vec4 params;
uniform vec4 anchor;
uniform vec4 aura;
varying vec2 uv;
void main() {
    vec2 s=params.xy;
    vec3 c=vec3(0.);
    if (params.z > 0.) {
        c=texture2D(image,uv).rgb*.28;
        c+=texture2D(image,uv+vec2(s.x,0.)).rgb*.13;
        c+=texture2D(image,uv-vec2(s.x,0.)).rgb*.13;
        c+=texture2D(image,uv+vec2(0.,s.y)).rgb*.13;
        c+=texture2D(image,uv-vec2(0.,s.y)).rgb*.13;
        c+=texture2D(image,uv+s).rgb*.05;
        c+=texture2D(image,uv-s).rgb*.05;
        c+=texture2D(image,uv+vec2(s.x,-s.y)).rgb*.05;
        c+=texture2D(image,uv+vec2(-s.x,s.y)).rgb*.05;
    }
    float scale=max(.15,anchor.z);
    vec2 floorUV = (uv - vec2(anchor.x,anchor.y-scale*.42)) * vec2(params.w, 8.0)/scale;
    float floorGlow = exp(-dot(floorUV,floorUV)*20.0);
    vec2 haloUV=(uv-anchor.xy)*vec2(params.w,1.)/scale;
    float halo = exp(-dot(haloUV,haloUV)*16.0);
    float breathing = 1.0 + aura.z * .10 * sin(aura.x * .95) + aura.y * .20 + aura.w * .08;
    gl_FragColor=vec4(c*params.z + vec3(.014,.007,.030)*floorGlow*breathing
                      + vec3(.020,.010,.044)*halo*breathing,0.);
}
'''


def particle_data(count=48000):
    """Mistura intercalada em todos os níveis: superfície, fitas e poeira exterior.

    O prefixo de 12 mil mantém a mesma distribuição do nível alto, sem virar
    uma casca vazia. As últimas quatro colunas são atributos dos shaders.
    """
    rng = np.random.default_rng(419)
    y = rng.uniform(-.99, .99, count)
    theta = rng.uniform(0, math.tau, count)
    seed = rng.random(count)
    kind = rng.choice([0.,1.,2.],count,p=[.72,.20,.08])
    radius = rng.uniform(.975,1.015,count)
    radius[kind==2] = rng.uniform(1.06,1.22,np.count_nonzero(kind==2))
    band = rng.choice([-.28,.27],count)
    thickness = rng.normal(0,.032,count)
    ribbon = kind==1
    y[ribbon] = band[ribbon]+.19*np.sin(theta[ribbon]*2)+.065*np.sin(theta[ribbon]*5)+thickness[ribbon]
    ring = np.sqrt(np.maximum(.03,1-y*y))
    glow = np.where(kind==2,.30, np.where(ribbon,.95,1.0))
    return np.column_stack((ring*np.cos(theta)*radius,y*radius,
                            ring*np.sin(theta)*radius,seed,kind,band,thickness,glow)).astype('float32')


def visible_particle_count(quality, width, height):
    """Densidade por área lógica evita que a esfera pequena vire uma mancha."""
    budget=QualityController.COUNTS[quality]
    side=max(1,min(width,height))
    return min(budget,max(1200,round(budget*min(1.,side/500.)**2)))


class StaticConstellation(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = particle_data(2400)
        self.focus_rect = None
        self.setMinimumSize(160, 160)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#09090F'))
        focus=self.focus_rect or QRectF(self.rect())
        cx,cy=focus.center().x(),focus.center().y()
        radius = min(focus.width(),focus.height()) * .38
        glow = QRadialGradient(cx, cy, radius*1.25)
        glow.setColorAt(0, QColor(139, 92, 246, 46))
        glow.setColorAt(1, QColor(9, 9, 15, 0))
        painter.fillRect(self.rect(), glow)
        for x, y, z, seed in self.points[:, :4]:
            radial=float(.16+1.02*seed**.65)
            x=float(x)*radial; yy=float(y)*radial
            core=1.-min(1.,max(0.,(radial-.16)/.84))
            painter.setPen(QPen(QColor(int(125+seed*86), int(96+seed*90), 252,
                                      int(min(255,60+seed*140+core*50))), float(.8+seed)))
            painter.drawPoint(round(cx+x*radius), round(cy-yy*radius))


class ParticleGL(QOpenGLWidget):
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
        self.program = self.bloom = self.buffer = self.quad = self.fbo = None
        self.failure_detail=''
        self.last_frame = None
        self.frame_times = []
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(FRAME_INTERVAL_MS)
        self.timer.timeout.connect(self.update)

    def initializeGL(self):
        try:
            self.gl = self.context().functions()
            self.program = self._program(VERTEX, FRAGMENT)
            self.bloom = self._program(QUAD_VERTEX, BLOOM_FRAGMENT)
            self.buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            self.buffer.create(); self.buffer.bind()
            data = particle_data().tobytes()
            self.buffer.allocate(data, len(data)); self.buffer.release()
            self.quad = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            self.quad.create(); self.quad.bind()
            data = np.array([-1,-1, 1,-1, -1,1, 1,1], dtype='float32').tobytes()
            self.quad.allocate(data, len(data)); self.quad.release()
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.ready = True
        except Exception as error:
            self.ready = False
            self.failure_detail=str(error)
            self.failed.emit('Animação indisponível: não foi possível iniciar OpenGL.')

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
        self.animation.set_visual(state,intensity)
        if self.reduced and changed:
            self.animation.advance(0.,reduced=True)
            self.update()

    def set_quality(self, quality):
        self.quality = QualityController(quality)
        self.timer.setInterval(FRAME_INTERVAL_MS)
        self.last_frame = None
        self.update()

    def _focus(self):
        return (self.focus_rect or QRectF(self.rect())).intersected(QRectF(self.rect()))

    def _count(self):
        rect=self._focus()
        return visible_particle_count(self.quality.level,rect.width(),rect.height())

    def paintGL(self):
        try:
            self._paint_frame()
        except Exception:
            self.ready = False
            self.timer.stop()
            self.failed.emit('Animação indisponível: houve uma falha na renderização OpenGL.')

    def _paint_frame(self):
        if not self.ready:
            return
        now = time.monotonic()
        dt = min(.1, now-self.last_frame) if self.last_frame else 0.
        if self.last_frame:
            elapsed = now-self.last_frame
            self.frame_times.append(elapsed)
            self.quality.observe(elapsed)
            if len(self.frame_times) >= 60:
                self.metrics.emit({'fps': round(len(self.frame_times)/sum(self.frame_times), 1),
                                   'frame_ms': round(1000*sum(self.frame_times)/len(self.frame_times), 2),
                                   'quality': self.quality.level,
                                   'particles': self._count()})
                self.frame_times.clear()
        self.last_frame = now
        self.animation.advance(dt*getattr(self,'scene_attention',1.),reduced=self.reduced)
        attention=getattr(self,'scene_attention',1.)
        self.scene_attention=attention+(getattr(self,'target_scene_attention',1.)-attention)*(1.-math.exp(-dt/.14))
        self.scene_motion.advance(dt*self.scene_attention,reduced=self.reduced)
        width = max(1, round(self.width()*self.devicePixelRatioF()))
        height = max(1, round(self.height()*self.devicePixelRatioF()))
        gl = self.gl
        gl.glClearColor(9/255, 9/255, 15/255, 1.)
        gl.glEnable(0x0BE2)  # GL_BLEND
        gl.glBlendFunc(1, 1)  # Emissão pré-multiplicada: ONE, ONE.
        gl.glEnable(0x8642)  # programmable point size
        gl.glEnable(0x8861)  # point sprites (compatibility context)
        if self.quality.level != 'low':
            size = QSize(max(1,width//3), max(1,height//3))
            if self.fbo is None or self.fbo.size() != size:
                self.fbo = QOpenGLFramebufferObject(size)
            self.fbo.bind()
            gl.glViewport(0,0,size.width(),size.height())
            gl.glClearColor(0.,0.,0.,1.); gl.glClear(0x4000)
            self._particles(width/height, self.devicePixelRatioF()/3., glow=True)
            gl.glBindFramebuffer(0x8D40, self.defaultFramebufferObject())
        gl.glViewport(0,0,width,height)
        gl.glClearColor(9/255,9/255,15/255,1.); gl.glClear(0x4000)
        if self.bloom:
            self.bloom.bind(); self.quad.bind()
            self.bloom.enableAttributeArray('position')
            self.bloom.setAttributeBuffer('position',0x1406,0,2,8)
            gl.glActiveTexture(0x84C0)
            glowing = self.quality.level != 'low' and self.fbo is not None
            gl.glBindTexture(0x0DE1,self.fbo.texture() if glowing else 0)
            gl.glUniform1i(self.bloom.uniformLocation('image'),0)
            gl.glUniform4f(self.bloom.uniformLocation('params'),
                           1.0/self.fbo.width() if glowing else 0.,
                           1.0/self.fbo.height() if glowing else 0.,
                           .65 if glowing else 0.,float(width/height))
            focus=self._focus()
            gl.glUniform4f(self.bloom.uniformLocation('anchor'),
                           focus.center().x()/max(1,self.width()),
                           1.-focus.center().y()/max(1,self.height())+.0275*focus.height()/max(1,self.height()),
                           focus.height()/max(1,self.height()),focus.width()/max(1,self.width()))
            gl.glUniform4f(self.bloom.uniformLocation('aura'),
                           self.animation.phase,self.animation.energy,float(not self.reduced),self.animation.pulse)
            gl.glDrawArrays(0x0005,0,4)
            self.bloom.disableAttributeArray('position'); self.quad.release(); self.bloom.release()
            gl.glBindTexture(0x0DE1,0)
        self._particles(width/height, self.devicePixelRatioF())
        gl.glDisable(0x0BE2)

    def _particles(self, aspect, ratio, *, glow=False):
        p = self.program
        p.bind(); self.buffer.bind()
        p.enableAttributeArray('particle')
        p.setAttributeBuffer('particle',0x1406,0,4,32)
        p.enableAttributeArray('detail')
        p.setAttributeBuffer('detail',0x1406,16,4,32)
        self.gl.glUniform1f(p.uniformLocation('clock'),float(self.animation.phase))
        self.gl.glUniform1f(p.uniformLocation('aspect'),float(aspect))
        focus=self._focus()
        fit=min(focus.height()/max(1,self.height()),focus.width()/max(1,self.height())*1.05)
        self.gl.glUniform1f(p.uniformLocation('fit'),float(fit))
        self.gl.glUniform2f(p.uniformLocation('center'),
                           2.*focus.center().x()/max(1,self.width())-1.,
                           1.-2.*focus.center().y()/max(1,self.height())+.055*focus.height()/max(1,self.height()))
        self.gl.glUniform1f(p.uniformLocation('energy'),float(self.animation.energy))
        self.gl.glUniform1f(p.uniformLocation('tension'),float(self.animation.tension))
        self.gl.glUniform1f(p.uniformLocation('life'),float(not self.reduced))
        self.gl.glUniform1f(p.uniformLocation('pixelRatio'),float(ratio)*min(1.,max(.28,focus.width()/240.)))
        self.gl.glUniform1f(p.uniformLocation('glowPass'),float(glow))
        self.gl.glUniform4f(p.uniformLocation('mode'),*self.animation.mode)
        self.gl.glUniform4f(p.uniformLocation('presence'),*self.animation.presence)
        self.gl.glUniform4f(p.uniformLocation('expression'),*self.animation.expression)
        count=min(100,self._count()) if focus.width()<120 else self._count()
        self.gl.glDrawArrays(0x0000,0,count)
        p.disableAttributeArray('particle'); p.disableAttributeArray('detail')
        self.buffer.release(); p.release()

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
        if not self.ready:return
        self.ready=False
        context=self.context()
        if context is None or not context.isValid():return
        try:context.aboutToBeDestroyed.disconnect(self.cleanup)
        except (RuntimeError,TypeError):pass
        self.makeCurrent()
        self.fbo = None
        for buffer in (self.buffer,self.quad):
            if buffer is not None:
                buffer.destroy()
        self.program = self.bloom = None
        self.doneCurrent()
        self.gl=None


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
            self.renderer = ParticleGL()
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
