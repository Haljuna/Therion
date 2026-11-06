"""GLSL da orbe holográfica (OpenGL 2.1, #version 120). Apenas texto."""

# Vértice: posição, outra ponta da linha, meta = (side, layer, spin, detail), extra = (glow, seed).
SCENE_VERTEX = '''
#version 120
attribute vec3 position;
attribute vec3 other;
attribute vec4 meta;
attribute vec2 extra;
uniform float spin, clock, detailLevel, lineWidth, pointSize, aspect, fit;
uniform float eye, tint, rim, flash, assembly, energy;
uniform vec2 center, viewport;
varying float vGlow, vLight, vLayer, vSeed;

vec3 place(vec3 p) {
    float layer = meta.y;
    float grow = smoothstep(extra.y*.6, extra.y*.6+.4, assembly);
    p = mix(p*.05, p, grow);
    float a = spin*meta.z;
    mat2 r = mat2(cos(a), sin(a), -sin(a), cos(a));
    if (abs(layer-4.) < .5) {               // giroscópio: gira no próprio plano e inclina 25°
        p.xy = r*p.xy;
        float t = radians(25.);
        p.yz = mat2(cos(t), sin(t), -sin(t), cos(t))*p.yz;
    } else if (abs(layer-5.) < .5) {        // olho: de frente para quem olha
        p.xy = r*p.xy;
    } else {
        p.xz = r*p.xz;
    }
    return p;
}

vec2 project(vec3 p) {
    float depth = 1./(3.1-p.z*.48);
    return vec2(p.x*depth*2.05*fit/aspect+center.x, p.y*depth*2.05*fit+center.y);
}

void main() {
    vec3 p = place(position);
    vec2 a = project(p);
    vec2 d = (project(place(other))-a)*viewport*.5;
    vec2 n = length(d) > 1e-4 ? normalize(vec2(-d.y, d.x)) : vec2(0.);
    gl_Position = vec4(a+n*meta.x*lineWidth/viewport, 0., 1.);
    gl_PointSize = pointSize*(.7+extra.y*.6);
    // Lado de trás com 35% do brilho; olho e giroscópio ficam de frente.
    float back = abs(meta.y-5.) < .5 ? 1. : mix(.35, 1., smoothstep(-.1, .1, p.z));
    float detail = mix(1., detailLevel, meta.w);
    vLight = back*detail;
    vGlow = extra.x;
    vLayer = meta.y;
    vSeed = extra.y;
}
'''

SCENE_FRAGMENT = '''
#version 120
uniform float isPoint, eye, tint, rim, flash;
varying float vGlow, vLight, vLayer, vSeed;
const vec3 BASE = vec3(.486, .302, 1.);    // #7C4DFF
const vec3 EDGE = vec3(.788, .722, 1.);    // #C9B8FF
const vec3 HOT = vec3(.957, .941, 1.);     // #F4F0FF
void main() {
    float shape = 1.;
    if (isPoint > .5) {
        float r = length(gl_PointCoord-vec2(.5))*2.;
        if (r > 1.) discard;
        shape = exp(-r*r*3.);
    }
    vec3 color = mix(BASE, EDGE, clamp(vGlow/1.2, 0., 1.));
    color = mix(color, HOT, clamp((vGlow-1.2)/.8, 0., 1.));
    gl_FragColor = vec4(color*vGlow*vLight*shape, 0.);
}
'''

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
