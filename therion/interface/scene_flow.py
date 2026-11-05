"""Correntes luminosas presas ao terreno da imagem original, sem serviços."""
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLBuffer

FLOW_COUNTS={'low':160,'medium':280,'high':420}

# Compartilhado pela textura e pelos pontos: a luz acompanha o terreno durante
# a respiração da cena, sem deslizar numa camada independente da imagem.
LANDSCAPE_GLSL='''
vec2 landscape_offset(vec2 uv,vec2 pointer,float phase,float life,float calm,float energy) {
    float depth=1.0-smoothstep(.08,.57,uv.y);
    vec2 breath=vec2(sin(phase*.23)*4.5,cos(phase*.19)*2.4);
    float tide=sin(uv.x*10.0-phase*.42)*3.4+sin(uv.x*17.0+phase*.31)*1.3;
    vec2 offset=pointer*(.6+2.8*depth)+breath*(.22+.78*depth);
    offset.y+=tide*depth*(.70+.30*energy);
    return offset*life*calm;
}
'''

FLOW_VERTEX='''
#version 120
'''+LANDSCAPE_GLSL+'''
attribute vec4 route;
attribute vec4 detail;
uniform vec4 mapping;
uniform vec4 dynamics;
uniform vec4 response;
uniform vec2 pointer;
uniform vec2 viewport;
uniform float pixelRatio;
varying vec2 terrainUV;
varying vec2 direction;
varying float radiance;
void main() {
    float calm=1.0-.60*max(response.z,response.w);
    float movementCalm=1.0-.85*max(response.z,response.w);
    float t=fract(dynamics.x*detail.y+detail.x);
    vec2 imageUV=mix(route.xy,route.zw,t);
    imageUV.y+=sin(t*3.14159265)*detail.z;
    vec2 local=(imageUV-mapping.xy)/mapping.zw;
    local-=landscape_offset(local,pointer,dynamics.x,1.0,movementCalm,dynamics.y)/max(viewport,vec2(1.0));
    gl_Position=vec4(local*2.0-1.0,0.0,1.0);
    gl_PointSize=(10.0+detail.w*7.0)*pixelRatio;
    terrainUV=imageUV;
    vec2 delta=(route.zw-route.xy)/mapping.zw*viewport;
    direction=delta/max(.001,length(delta));
    float fade=smoothstep(0.0,.12,t)*(1.0-smoothstep(.86,1.0,t));
    radiance=fade*detail.w*calm*(.70+.70*dynamics.y+.36*dynamics.z+.24*dynamics.w);
}
'''

FLOW_FRAGMENT='''
#version 120
uniform sampler2D environment;
varying vec2 terrainUV;
varying vec2 direction;
varying float radiance;
void main() {
    vec2 q=vec2(gl_PointCoord.x-.5,.5-gl_PointCoord.y)*2.0;
    if (dot(q,q)>1.0) discard;
    float along=dot(q,direction);
    float across=dot(q,vec2(-direction.y,direction.x));
    float core=exp(-dot(q,q)*20.0);
    float trail=exp(-across*across*22.0-along*along*3.5)*.32;
    float halo=exp(-dot(q,q)*4.0)*.08;
    vec3 surface=texture2D(environment,terrainUV).rgb;
    float embedded=.18+.82*smoothstep(.025,.22,surface.r-surface.b);
    vec3 light=vec3(1.0,.52,.15)*(trail+halo)+vec3(1.0,.88,.57)*core;
    gl_FragColor=vec4(light*radiance*embedded,0.0);
}
'''


def terrain_routes(pixels,count=420):
    """Amostra trilhas âmbar no primeiro plano, uma única vez na inicialização."""
    height,width=pixels.shape[:2]
    if width<4 or height<4 or count<1:return np.empty((0,8),dtype='float32')
    stride=max(3,round(width/400));rgb=pixels[::stride,::stride,:3].astype('float32')
    mask=(rgb[:,:,0]>75)&(rgb[:,:,1]>22)&(rgb[:,:,0]-rgb[:,:,2]>30)
    mask[:round(mask.shape[0]*.55)]=False
    yy,xx=np.nonzero(mask)
    if len(xx)<2:return np.empty((0,8),dtype='float32')
    coords=np.column_stack(((xx*stride+.5)/width,1.-(yy*stride+.5)/height))
    rng=np.random.default_rng(8181);aspect=width/height;rows=[]
    starts=rng.choice(len(coords),size=count,replace=len(coords)<count)
    for index in starts:
        start=coords[index];delta=(coords-start)*np.array([aspect,1.])
        distance=np.linalg.norm(delta,axis=1)
        candidates=np.flatnonzero((distance>.012)&(distance<.085)&(abs(delta[:,1])<.055))
        if not len(candidates):continue
        desired=rng.uniform(.025,.065);order=np.argsort(abs(distance[candidates]-desired))[:12]
        pool=candidates[order];ends=coords[pool]
        samples=start[None,None,:]+(ends[:,None,:]-start)*np.linspace(.1,.9,5)[None,:,None]
        xs=np.clip((samples[:,:,0]*width).astype(int),0,width-1)
        ys=np.clip(((1.-samples[:,:,1])*height).astype(int),0,height-1)
        colors=pixels[ys,xs,:3].astype(float)
        score=np.maximum(0,colors[:,:,0]-colors[:,:,2]).mean(axis=1)
        end=ends[int(np.argmax(score+rng.uniform(0,10,len(score))))]
        length=max(.001,float(np.linalg.norm((end-start)*[aspect,1.])))
        rows.append([*start,*end,rng.random(),rng.uniform(.022,.040)/length,
                     rng.uniform(-.003,.003),rng.uniform(.65,1.0)])
    return np.asarray(rows,dtype='float32').reshape(-1,8)


class TerrainFlow:
    def __init__(self,owner,image,texture):
        self.owner=owner;self.texture=texture
        self.program=owner._program(FLOW_VERTEX,FLOW_FRAGMENT)
        rgba=image.convertToFormat(QImage.Format_RGBA8888)
        pixels=np.frombuffer(rgba.constBits(),dtype=np.uint8).reshape(rgba.height(),rgba.bytesPerLine()//4,4)[:,:rgba.width()]
        data=terrain_routes(pixels,max(FLOW_COUNTS.values()));self.count=len(data)
        self.buffer=QOpenGLBuffer(QOpenGLBuffer.VertexBuffer);self.buffer.create();self.buffer.bind()
        raw=data.tobytes();self.buffer.allocate(raw,len(raw));self.buffer.release()

    def draw(self):
        o=self.owner
        if o.reduced or not self.count:return
        p=self.program;p.bind();self.texture.bind(0);g=o.gl;a=o.animation
        g.glUniform1i(p.uniformLocation('environment'),0)
        g.glUniform4f(p.uniformLocation('mapping'),*getattr(o,'environment_mapping',(0.,0.,1.,1.)))
        g.glUniform4f(p.uniformLocation('dynamics'),o.scene_motion.phase,a.energy,a.action,a.pulse)
        g.glUniform4f(p.uniformLocation('response'),*a.mode)
        g.glUniform2f(p.uniformLocation('pointer'),*o.scene_motion.pointer)
        g.glUniform2f(p.uniformLocation('viewport'),float(o.width()),float(o.height()))
        g.glUniform1f(p.uniformLocation('pixelRatio'),float(o.devicePixelRatioF()))
        self.buffer.bind()
        for name,offset in [('route',0),('detail',16)]:
            p.enableAttributeArray(name);p.setAttributeBuffer(name,0x1406,offset,4,32)
        g.glBlendFunc(1,1);g.glDrawArrays(0,0,min(self.count,FLOW_COUNTS[o.quality.level]))
        p.disableAttributeArray('route');p.disableAttributeArray('detail')
        self.buffer.release();self.texture.release();p.release()

    def cleanup(self):
        self.buffer.destroy()
