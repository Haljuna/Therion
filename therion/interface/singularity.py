"""Materiais e geometria da Câmara de Singularidade; tudo é apresentação."""
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLTexture
from .scene_flow import TerrainFlow, LANDSCAPE_GLSL


ENVIRONMENT=Path(__file__).resolve().parents[1]/'assets/constellation/singularity-environment.png'
FIBERS={'high':88,'medium':56,'low':32}
SEGMENTS=224

# Compartilhado entre filamentos, partículas, casca e satélites: um único corpo.
MOTION_GLSL='''
uniform vec4 expression;
vec3 embody(vec3 p,float phase,float life,vec4 mode,float tension) {
    float calm=1.0-.90*max(mode.z,mode.w);
    float breath=life*calm*(.034*sin(phase*.95)+.012*sin(phase*.41+.6));
    p*=1.0-mode.x*.09+breath;
    float tilt=life*calm*(.055*sin(phase*.43)+expression.y*.13*sin(phase*.71));
    p.yz=mat2(cos(tilt),-sin(tilt),sin(tilt),cos(tilt))*p.yz;
    float sway=life*calm*(.035*sin(phase*.32)+expression.z*.075*sin(phase*.59));
    p.xy=mat2(cos(sway),-sin(sway),sin(sway),cos(sway))*p.xy;
    p.x+=life*calm*.012*sin(phase*.31);
    p.y+=life*calm*.015*sin(phase*.64);
    return p;
}
'''


def environment_crop(width,height,image_width,image_height):
    """Mesmo enquadramento cover no QPainter e na textura OpenGL."""
    scale=max(width/max(1,image_width),height/max(1,image_height))
    w=width/scale;h=height/scale
    return QRectF((image_width-w)/2,(image_height-h)/2,w,h)


@lru_cache(maxsize=3)
def filament_mesh(count):
    rows=[]
    for kind,number in [(0,count),(1,12),(2,3),(3,1)]:
        for index in range(number):
            theta=(index*2.399963229728653)%math.tau if kind==0 else math.tau*index/number
            end=math.pi if kind==3 else math.tau
            start=-math.pi/2 if kind==3 else 0.
            end=end+start
            for step in range(SEGMENTS):
                a=start+(end-start)*step/SEGMENTS;b=start+(end-start)*(step+1)/SEGMENTS
                for t,side in [(a,-1),(b,-1),(a,1),(a,1),(b,-1),(b,1)]:
                    rows.append((t,theta,side,float(kind)))
    result=np.asarray(rows,dtype='float32');result.setflags(write=False);return result


LINE_VERTEX='''
#version 120
'''+MOTION_GLSL+'''
attribute vec4 curve;
uniform float clock;
uniform float aspect;
uniform float fit;
uniform vec2 center;
uniform float viewportHeight;
uniform float pixelRatio;
uniform float glowPass;
uniform vec4 mode;
uniform vec4 movement;
varying float edge;
varying float radiance;
varying float temperature;
vec3 path(float t) {
    float phase=clock;
    float theta=curve.y;
    float kind=curve.w;
    vec3 p;
    if(kind<.5) {
        float seed=fract(sin(theta*127.1)*43758.5453);
        float b=t*2.0+theta+.44*sin(t*3.0+seed*6.2832)+.26*cos(t+theta*.73)
                +movement.z*(.14+expression.y*.32)*sin(t*2.0-phase*.5+expression.y*.45);
        float tube=(.22+.13*seed)*(1.0-expression.x*.28);
        float ring=.655+expression.x*.10+tube*cos(b);
        p=vec3(ring*cos(t+.10*sin(t*2.0+theta*2.0)),ring*sin(t),tube*sin(b)*1.3);
        float a=.20+.25*seed+movement.z*(.055+expression.y*.12)*sin(phase*.45+theta);
        p.yz=mat2(cos(a),-sin(a),sin(a),cos(a))*p.yz;
        float swirl=phase*.09*movement.z-.18+.36*seed
                   +movement.z*expression.y*.14*sin(phase*.53+theta);
        p.xy=mat2(cos(swirl),-sin(swirl),sin(swirl),cos(swirl))*p.xy;
        p*=1.0+movement.x*.090*sin(t*6.0-phase*3.2)+movement.w*.035;
        p.z+=movement.z*expression.y*.065*sin(t*3.0-phase*.9+theta);
    } else if(kind<1.5) {
        p=vec3(cos(t)*sin(theta),sin(t),cos(t)*cos(theta))*.985;
        p.xz=mat2(.94,-.342,.342,.94)*p.xz;
    } else if(kind<2.5) {
        float a=theta*.22-.22+movement.z*(.07+expression.z*.18)*sin(phase*.45+theta);
        p=vec3(1.48*cos(t),.24*sin(t),.77*sin(t));
        p.xy=mat2(cos(a),-sin(a),sin(a),cos(a))*p.xy;
    } else {
        p=vec3(1.16*cos(t),1.16*sin(t),0.0);
    }
    return embody(p,phase,movement.z,mode,movement.x);
}
vec2 project(vec3 p) {
    float depth=1.0/(3.15-p.z*.48);
    return p.xy*depth*2.35*fit/vec2(aspect,1.0)+center;
}
void main() {
    vec3 p=path(curve.x);
    vec2 a=project(p),b=project(path(curve.x+.001));
    vec2 direction=normalize((b-a)*vec2(aspect,1.0));
    vec2 normal=vec2(-direction.y,direction.x)/vec2(aspect,1.0);
    float seed=fract(sin(curve.y*127.1)*43758.5453);
    float width=curve.w<.5?.55+pow(seed,6.0)*1.4:.8;
    width=max(glowPass>.5?.65:.55,width*pixelRatio);
    gl_Position=vec4(a+normal*curve.z*width*2.0/viewportHeight,0.0,1.0);
    edge=curve.z;
    float front=smoothstep(-.4,.4,p.z);
    float packet=pow(.5+.5*cos(curve.x*4.0-clock*1.55+expression.z*.55*sin(clock*.6)+curve.y*2.0),16.0);
    radiance=(.035+seed*seed*.30)*mix(.3,1.0,front);
    radiance+=packet*(.10+mode.y*.42+movement.y*.58);
    if(seed>.88 && curve.w<.5)radiance*=2.4;
    if(curve.w> .5 && curve.w<1.5) radiance*=.18*smoothstep(.5,.95,length(p.xy));
    if(curve.w>1.5 && curve.w<2.5) {
        radiance=.30+packet*(.16+movement.y*.65);
        if(length(p.xy)<.99 && p.z<0.0) radiance*=.07;
    }
    if(curve.w>2.5) radiance=.45;
    radiance*=1.0+movement.w*.25+movement.x*.65+expression.w*.35;
    temperature=clamp(.25+front*.3+packet*.15+seed*.20+expression.w*.12,0.0,1.0);
}
'''
LINE_FRAGMENT='''
#version 120
uniform vec4 mode;
uniform float glowPass;
varying float edge;
varying float radiance;
varying float temperature;
void main() {
    float coverage=1.0-smoothstep(.2,1.0,abs(edge));
    vec3 color=mix(vec3(1.0,.29,.025),vec3(1.0,.78,.43),temperature);
    color=mix(color,vec3(.57,.24,.07),mode.w*.65);
    float gain=glowPass>.5?.7:1.5;
    gl_FragColor=vec4(color*coverage*radiance*gain,0.0);
}
'''

SURFACE_FRAGMENT='''
#version 120
'''+MOTION_GLSL+'''
uniform float aspect;
uniform float fit;
uniform vec2 center;
uniform vec4 dynamics;
uniform vec4 mode;
varying vec2 uv;
void main() {
    vec3 body=embody(vec3(0.0),dynamics.x,dynamics.z,mode,dynamics.y);
    float calm=1.0-.90*max(mode.z,mode.w);
    float breath=dynamics.z*calm*(.034*sin(dynamics.x*.95)+.012*sin(dynamics.x*.41+.6));
    float size=.755*fit*(1.0-mode.x*.09+breath);
    vec2 q=((uv*2.0-1.0-center)*vec2(aspect,1.0)-body.xy*.746*fit)/max(.01,size);
    float r=length(q);
    if(r>1.035) discard;
    float z=sqrt(max(0.0,1.0-r*r));
    vec3 normal=normalize(vec3(q,z));
    float fresnel=pow(1.0-z,6.0)*.20;
    float rim=exp(-abs(r-1.0)*380.0)*.5;
    float inner=exp(-abs(r-.973)*420.0)*.12;
    float spot=pow(max(0.0,dot(normal,normalize(vec3(.48,.65,.45)))),95.0)*.75;
    vec3 orange=mix(vec3(1.0,.43,.12),vec3(.57,.24,.07),mode.w*.65);
    vec3 light=orange*(fresnel+rim+inner)*(1.0+dynamics.y*.55+expression.w*.24)
                +vec3(1.0,.87,.61)*spot;
    float alpha=(.08+fresnel*.15)*(1.0-smoothstep(.99,1.035,r));
    gl_FragColor=vec4(light,alpha);
}
'''

BACKGROUND_FRAGMENT='''
#version 120
'''+LANDSCAPE_GLSL+'''
uniform sampler2D environment;
uniform vec4 mapping;
uniform vec4 dynamics;
uniform vec4 response;
uniform vec4 camera;
uniform vec2 origin;
uniform vec2 viewport;
uniform float attention;
varying vec2 uv;
void main() {
    float life=dynamics.z;
    float calm=1.0-.85*max(response.z,response.w);
    float phase=dynamics.x;
    vec2 displacement=landscape_offset(uv,camera.xy,phase,life,calm,dynamics.y);
    vec2 sampleUV=mapping.xy+(uv+displacement/max(viewport,vec2(1.0)))*mapping.zw;
    vec3 material=texture2D(environment,clamp(sampleUV,vec2(.0001),vec2(.9999))).rgb;
    float amber=smoothstep(.06,.62,material.r)*smoothstep(.035,.23,material.r-material.b);
    float distanceToCore=length((uv-origin)*vec2(viewport.x/max(1.0,viewport.y),1.0));
    float flow=pow(.5+.5*sin(uv.x*19.0+uv.y*13.0-phase*(1.25+dynamics.w*.8)),10.0);
    float ripple=pow(.5+.5*cos(distanceToCore*32.0-phase*(1.8+response.y*.6)),14.0);
    float breathing=.5+.5*sin(phase*.55+uv.x*2.0);
    float influence=life*calm*amber;
    float energy=dynamics.y;
    float gain=1.0+influence*(-.035+.09*breathing+.26*flow+
                   (.14+.42*energy+.20*dynamics.w)*ripple+energy*.18+camera.z*.20);
    vec3 illumination=vec3(1.0,.48,.10)*influence*flow*(.012+.025*energy);
    gl_FragColor=vec4((material*gain+illumination)*attention,1.0);
}
'''

SATELLITE_VERTEX='''
#version 120
'''+MOTION_GLSL+'''
attribute vec4 satellite;
uniform float clock;
uniform float aspect;
uniform float fit;
uniform vec2 center;
uniform float pixelRatio;
uniform float life;
uniform vec4 mode;
varying float exposure;
void main() {
    float t=satellite.x+clock*.10*life+life*expression.z*.18*sin(clock*.47+satellite.x);
    vec3 p=vec3(1.48*cos(t),.24*sin(t),.77*sin(t));
    float a=satellite.y+life*(.07+expression.z*.18)*sin(clock*.45+satellite.w);
    p.xy=mat2(cos(a),-sin(a),sin(a),cos(a))*p.xy;
    p=embody(p,clock,life,mode,0.0);
    float depth=1.0/(3.15-p.z*.48);
    gl_Position=vec4(p.xy*depth*2.35*fit/vec2(aspect,1.0)+center,0.0,1.0);
    gl_PointSize=satellite.z*pixelRatio;
    exposure=length(p.xy)<.98 && p.z<0.0?.03:1.0;
}
'''
SATELLITE_FRAGMENT='''
#version 120
varying float exposure;
uniform vec4 mode;
void main() {
    if(exposure<.1)discard;
    vec2 q=(gl_PointCoord-.5)*2.0;
    float r=dot(q,q);if(r>1.0)discard;
    vec3 n=vec3(q.x,-q.y,sqrt(1.0-r));
    float shine=pow(max(dot(n,normalize(vec3(.25,.65,.7))),0.0),32.0);
    float rim=pow(1.0-n.z,5.0)*.22;
    vec3 color=vec3(.035,.025,.017)+vec3(.32,.13,.035)*max(n.y,0.0)
               +vec3(1.0,.76,.38)*shine+vec3(.7,.30,.06)*rim;
    color=mix(color,color*vec3(.57,.24,.07),mode.w*.4)*exposure;
    gl_FragColor=vec4(color,1.0-smoothstep(.94,1.0,r));
}
'''


class SingularityPass:
    def __init__(self,owner,quad_vertex):
        self.owner=owner;self.buffers={}
        self.lines=owner._program(LINE_VERTEX,LINE_FRAGMENT)
        self.surface=owner._program(quad_vertex,SURFACE_FRAGMENT)
        self.background=owner._program(quad_vertex,BACKGROUND_FRAGMENT)
        self.satellites=owner._program(SATELLITE_VERTEX,SATELLITE_FRAGMENT)
        for quality,count in FIBERS.items():
            data=filament_mesh(count)
            buffer=QOpenGLBuffer(QOpenGLBuffer.VertexBuffer);buffer.create();buffer.bind()
            raw=data.tobytes();buffer.allocate(raw,len(raw));buffer.release()
            self.buffers[quality]=(buffer,len(data))
        self.satellite_buffer=QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.satellite_buffer.create();self.satellite_buffer.bind()
        raw=np.asarray([[.3,-.22,20,0],[2.65,.24,32,0],[3.7,0,24,0],[5.1,.0,15,0]],dtype='float32').tobytes()
        self.satellite_buffer.allocate(raw,len(raw));self.satellite_buffer.release()
        self.image=QImage(str(ENVIRONMENT))
        self.texture=QOpenGLTexture(self.image.mirrored()) if not self.image.isNull() else None
        self.terrain=None
        if self.texture:
            self.texture.setMinificationFilter(QOpenGLTexture.Linear)
            self.texture.setMagnificationFilter(QOpenGLTexture.Linear)
            self.terrain=TerrainFlow(owner,self.image,self.texture)

    def uniforms(self,p,aspect):
        o=self.owner;g=o.gl;focus=o._focus();a=o.animation
        fit=min(focus.height()/max(1,o.height()),focus.width()/max(1,o.height())*1.05)
        g.glUniform1f(p.uniformLocation('aspect'),float(aspect));g.glUniform1f(p.uniformLocation('fit'),float(fit))
        g.glUniform2f(p.uniformLocation('center'),2.*focus.center().x()/max(1,o.width())-1.,
                     1.-2.*focus.center().y()/max(1,o.height())+.055*focus.height()/max(1,o.height()))
        g.glUniform1f(p.uniformLocation('clock'),a.phase)
        g.glUniform4f(p.uniformLocation('mode'),*a.mode)
        g.glUniform4f(p.uniformLocation('expression'),*a.expression)

    def quad(self,p):
        o=self.owner;p.bind();o.quad.bind();p.enableAttributeArray('position')
        p.setAttributeBuffer('position',0x1406,0,2,8);o.gl.glDrawArrays(0x0005,0,4)
        p.disableAttributeArray('position');o.quad.release();p.release()

    def draw_background(self):
        if not self.texture:return
        o=self.owner;p=self.background;p.bind();self.texture.bind(0)
        o.gl.glUniform1i(p.uniformLocation('environment'),0)
        mapping=getattr(o,'environment_mapping',(0.,0.,1.,1.))
        o.gl.glUniform4f(p.uniformLocation('mapping'),*mapping)
        a=o.animation;focus=o._focus()
        o.gl.glUniform4f(p.uniformLocation('dynamics'),o.scene_motion.phase,a.energy,float(not o.reduced),a.action)
        o.gl.glUniform1f(p.uniformLocation('attention'),getattr(o,'scene_attention',1.))
        o.gl.glUniform4f(p.uniformLocation('response'),*a.mode)
        o.gl.glUniform4f(p.uniformLocation('camera'),*o.scene_motion.pointer,a.pulse,0.)
        o.gl.glUniform2f(p.uniformLocation('origin'),focus.center().x()/max(1,o.width()),1.-focus.center().y()/max(1,o.height()))
        o.gl.glUniform2f(p.uniformLocation('viewport'),float(o.width()),float(o.height()))
        o.gl.glDisable(0x0BE2);self.quad(p);self.texture.release();o.gl.glEnable(0x0BE2)
        if self.terrain:self.terrain.draw()

    def draw_surface(self,aspect):
        o=self.owner;p=self.surface;p.bind();self.uniforms(p,aspect);a=o.animation
        o.gl.glUniform4f(p.uniformLocation('dynamics'),a.phase,a.energy,float(not o.reduced),a.pulse)
        o.gl.glBlendFunc(1,0x0303);self.quad(p);o.gl.glBlendFunc(1,1)

    def draw_lines(self,aspect,ratio,viewport_height,glow=False):
        o=self.owner;p=self.lines;p.bind();self.uniforms(p,aspect);a=o.animation
        o.gl.glUniform4f(p.uniformLocation('movement'),a.tension,a.action,float(not o.reduced),a.pulse)
        o.gl.glUniform1f(p.uniformLocation('viewportHeight'),float(viewport_height))
        o.gl.glUniform1f(p.uniformLocation('pixelRatio'),float(ratio))
        o.gl.glUniform1f(p.uniformLocation('glowPass'),float(glow))
        buffer,count=self.buffers[o.quality.level];buffer.bind();p.enableAttributeArray('curve')
        p.setAttributeBuffer('curve',0x1406,0,4,16)
        if o._focus().width()<120:
            o.gl.glDrawArrays(0x0004,0,8*SEGMENTS*6)
            o.gl.glDrawArrays(0x0004,(FIBERS[o.quality.level]+12)*SEGMENTS*6,4*SEGMENTS*6)
        else:o.gl.glDrawArrays(0x0004,0,count)
        p.disableAttributeArray('curve');buffer.release();p.release()

    def draw_satellites(self,aspect,ratio):
        if self.owner._focus().width()<120:return
        o=self.owner;p=self.satellites;p.bind();self.uniforms(p,aspect)
        o.gl.glUniform1f(p.uniformLocation('pixelRatio'),float(ratio))
        o.gl.glUniform1f(p.uniformLocation('life'),float(not o.reduced))
        self.satellite_buffer.bind();p.enableAttributeArray('satellite');p.setAttributeBuffer('satellite',0x1406,0,4,16)
        o.gl.glBlendFunc(0x0302,0x0303);o.gl.glDrawArrays(0,0,4);o.gl.glBlendFunc(1,1)
        p.disableAttributeArray('satellite');self.satellite_buffer.release();p.release()

    def cleanup(self):
        if self.terrain:self.terrain.cleanup()
        for buffer,_ in self.buffers.values():buffer.destroy()
        self.satellite_buffer.destroy()
        if self.texture:self.texture.destroy()
