"""GLSL da Orbe HUD (OpenGL 2.1, #version 120). Apenas texto."""

# Vértice: posição, outra ponta da linha, meta = (side, layer, índice da órbita, velocidade),
# extra = (glow, seed). Camadas: 0 pontos da esfera, 1 órbita, 2 eixo, 3 ponto que corre na órbita.
# Fórmulas de movimento portadas do protótipo (draw() em specs/2026-11-13-orbe-hud-prototipo.html).
SCENE_VERTEX = '''
#version 120
attribute vec3 position;
attribute vec3 other;
attribute vec4 meta;
attribute vec2 extra;
uniform float spin, clock, ripple, sweep, sweepPhase, listenWave, energy, voice, breathe;
uniform float dim, jitter, orbitPhase, assembly, flash;
uniform float pointSize, radiusPx, lineWidth, aspect, fit, isPoint;
uniform vec2 center, viewport;
varying float vLight, vHot, vLayer;
const float F = 3.4;                              // distância da câmera, em raios
const vec3 D1 = vec3(.6189, .3094, .7220);
const vec3 D2 = vec3(-.4364, .8729, .2182);
const vec3 D3 = vec3(.2074, -.5185, .8296);

vec3 rotY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x*c+p.z*s, p.y, -p.x*s+p.z*c); }
vec3 rotX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, p.y*c-p.z*s, p.y*s+p.z*c); }

// Órbitas acompanham a esfera a 30% do giro; o eixo, a 50% e mais deitado.
vec3 placeLine(vec3 p, float layer) {
    return abs(layer-2.) < .5 ? rotX(rotY(p, spin*.5), .75) : rotX(rotY(p, spin*.3), .25);
}

vec2 project(vec3 p) {
    float k = F/(F-p.z);
    return vec2(p.x*k*fit/aspect+center.x, p.y*k*fit+center.y);
}

void main() {
    float layer = meta.y, light, hot = 0.;
    vec3 p;
    if (layer < .5) {
        vec3 b = position;
        float seed = extra.y;
        float r = 1.+ripple*.035*sin(dot(b, D1)*5.+clock*1.2)*sin(dot(b, D2)*4.-clock*.8);
        float lum = .55+.45*sin(clock*2.2+seed*40.);
        float w = max(0., sin(dot(b, D3)*7.+clock*6.));          // pulso da voz do Therion
        r += voice*(.06+.12*w); lum += voice*w;
        float band = b.y-sin(sweepPhase);                        // faixa de luz varrendo
        lum += sweep*1.4*exp(-band*band/.006);
        r += breathe*.04*sin(clock*1.6)+jitter*.02*sin(clock*31.+seed*50.);
        vec3 v = rotX(rotY(b, spin), .28);
        float ang = acos(clamp(v.z, -1., 1.));                   // ondas correm para quem olha
        float wave = max(0., sin(ang*9.+clock*6.));
        r += listenWave*(.03+.05*energy)*wave; lum += listenWave*.8*wave*(1.-ang/3.14159);
        float grow = smoothstep(seed*.6, seed*.6+.4, assembly);  // montagem: vem de dentro e acende
        p = v*r*mix(.6, 1., grow);
        float depth = (v.z+1.)*.5;                               // frente maior e clara, fundo menor e escuro
        float a = min(1., (.12+.88*depth)*lum*.85);
        hot = smoothstep(.45, .8, a);
        light = a*grow*dim;
        gl_PointSize = max(1.5, pointSize*(.6+1.2*depth));
    } else {
        if (layer > 2.5) {
            float a = 6.2832*orbitPhase*meta.w;
            p = placeLine(position*cos(a)+other*sin(a), 1.);
            light = p.z >= 0. ? 1. : .35;
            gl_PointSize = max(4., radiusPx*.18);
        } else {
            p = placeLine(position, layer);
            light = extra.x*mix(.3, 1., smoothstep(-.1, .1, p.z));   // metade de trás com 30%
            gl_PointSize = max(3., radiusPx*.04);
        }
        hot = isPoint;
        light *= smoothstep(.3, 1., assembly);
    }
    vec2 at = project(p);
    vec2 n = vec2(0.);
    if (abs(meta.x) > .5) {
        vec2 d = (project(placeLine(other, layer))-at)*viewport*.5;
        if (length(d) > 1e-4) n = normalize(vec2(-d.y, d.x));
    }
    gl_Position = vec4(at+n*meta.x*lineWidth/viewport, 0., 1.);
    vLight = light*(1.+1.5*flash);
    vHot = hot;
    vLayer = layer;
}
'''

SCENE_FRAGMENT = '''
#version 120
uniform float isPoint, amber;
uniform vec3 colDot, colHot, colFrame, colAmber;
varying float vLight, vHot, vLayer;
void main() {
    float shape = 1.;
    if (isPoint > .5) {
        float r = length(gl_PointCoord-vec2(.5))*2.;
        if (r > 1.) discard;
        shape = vLayer > 2.5 ? (1.-r)*(1.-r) : exp(-r*r*2.5);
    }
    // No alerta só o que é ciano vira âmbar: órbitas, eixo e os pontos mais acesos.
    vec3 warm = mix(colHot, colAmber, amber);
    vec3 color = vLayer < .5 ? mix(colDot, warm, vHot) : mix(mix(colFrame, colAmber, amber), warm, vHot);
    gl_FragColor = vec4(color*vLight*shape, 0.);
}
'''

QUAD_VERTEX = '''
#version 120
attribute vec2 position;
varying vec2 uv;
void main() { uv = position*.5+.5; gl_Position=vec4(position,0.,1.); }
'''

# Núcleo: brilho radial atrás da esfera (até 1,25 R) e um halo largo e fraco (até 2,4 R).
AURA_FRAGMENT = '''
#version 120
uniform vec4 anchor;   // centro em uv, raio da esfera em altura de uv, proporção da tela
uniform float strength;
uniform vec3 colCore;
varying vec2 uv;
void main() {
    float r = length((uv-anchor.xy)*vec2(anchor.w, 1.)/anchor.z);
    float t = r/1.25;
    float core = t < .55 ? mix(1., .45, t/.55) : mix(.45, 0., clamp((t-.55)/.45, 0., 1.));
    float halo = .16*max(0., 1.-r/2.4);
    gl_FragColor = vec4(colCore*(core*strength+halo), 0.);
}
'''

# Desfoque gaussiano separável de 9 amostras; step = (1/largura, 0) ou (0, 1/altura).
BLUR_FRAGMENT = '''
#version 120
uniform sampler2D image;
uniform vec2 step;
varying vec2 uv;
void main() {
    vec3 c = texture2D(image, uv).rgb*.227027;
    c += (texture2D(image, uv+step).rgb+texture2D(image, uv-step).rgb)*.1945946;
    c += (texture2D(image, uv+step*2.).rgb+texture2D(image, uv-step*2.).rgb)*.1216216;
    c += (texture2D(image, uv+step*3.).rgb+texture2D(image, uv-step*3.).rgb)*.054054;
    c += (texture2D(image, uv+step*4.).rgb+texture2D(image, uv-step*4.).rgb)*.016216;
    gl_FragColor = vec4(c, 1.);
}
'''

# Rastro: o quadro anterior apaga aos poucos. max() em vez de soma, para o que está
# parado não acumular brilho; só o que se move deixa cauda.
TRAIL_FRAGMENT = '''
#version 120
uniform sampler2D scene, previous;
uniform float keep;
varying vec2 uv;
void main() {
    gl_FragColor = vec4(max(texture2D(scene, uv).rgb, texture2D(previous, uv).rgb*keep), 1.);
}
'''

# Cena + brilho em até 3 escalas, somados ao fundo (halo e chão já desenhados).
COMPOSITE_FRAGMENT = '''
#version 120
uniform sampler2D scene, glow0, glow1, glow2;
uniform vec3 weights;
varying vec2 uv;
void main() {
    vec3 c = texture2D(scene, uv).rgb;
    c += texture2D(glow0, uv).rgb*weights.x+texture2D(glow1, uv).rgb*weights.y
         +texture2D(glow2, uv).rgb*weights.z;
    gl_FragColor = vec4(c, 1.);
}
'''
