"""Dados da Orbe HUD: cores, nomes, aparência por estado e proporções. Sem Qt."""
from dataclasses import dataclass, fields

DOT = (200, 185, 255)
HOT = (200, 255, 250)
CORE = (110, 90, 230)
FRAME = (120, 215, 232)
AMBER = (255, 180, 90)
GAME_RED = (255, 60, 55)     # modo de jogo: arcos e nome do estado
GAME_CORE = (200, 40, 70)    # modo de jogo: brilho atrás da esfera
GAME_LABEL = 'MODO DE JOGO'


@dataclass(frozen=True)
class HudLook:
    spin_seconds: float    # segundos por volta; 0 = parada
    ripple: float
    sweep: float
    sweep_speed: float
    listen_wave: float
    voice_bulge: float
    breathe: float
    arc_deg: float
    arc_spin: float
    arc_blink: float
    arc_scale: float
    core: float
    dim: float
    amber: float
    jitter: float
    orbit_speed: float
    trail: float
    voice_ring: float


_TABLE = {
    #                         rótulo                spin rip  swp  sws  lis voi bre arc  asp abl asc  core dim  amb  jit orb  trl  ring
    'idle':                  ('EM REPOUSO',          40, 1.,  0.,  0.,  0., 0., 0., 38., 0., 0., 1.,  .32, 1.,  0.,  0., 1.,  0.,  0.),
    'preparing':             ('PREPARANDO',          20, .6,  0.,  0.,  0., 0., 0., 38., 0., 0., 1.,  .40, 1.,  0.,  0., 1.,  0.,  0.),
    'listening':             ('OUVINDO',             60, .6,  0.,  0.,  1., 0., 0., 68., 0., 0., 1.,  .57, 1.,  0.,  0., .8,  0.,  0.),
    'transcribing':          ('TRANSCREVENDO',       20, .6,  .5,  .5,  0., 0., 0., 38., .4, 0., 1.,  .45, 1.,  0.,  0., 1.2, 0.,  0.),
    'thinking':              ('PENSANDO',             6, .8,  1.,  1.8, 0., 0., 0., 38., 1., 0., 1.,  .52, 1.,  0.,  0., 1.6, .35, 0.),
    'executing':             ('EXECUTANDO',           6, .8,  1.,  1.8, 0., 0., 0., 38., 1., 0., 1.,  .52, 1.,  0.,  0., 2.5, .5,  0.),
    'synthesizing':          ('PREPARANDO A FALA',   25, .6,  0.,  0.,  0., 0., 1., 38., 0., 0., 1.,  .45, 1.,  0.,  0., 1.,  0.,  .3),
    'speaking':              ('FALANDO',             20, .5,  0.,  0.,  0., 1., 0., 38., 0., 0., 1.,  .45, 1.,  0.,  0., 1.,  0.,  1.),
    'awaiting_confirmation': ('AGUARDANDO VOCÊ',    120, .4,  0.,  0.,  0., 0., 0., 38., 0., 1., 1.,  .30, 1.,  0.,  0., .3,  0.,  0.),
    'clarification':         ('AGUARDANDO RESPOSTA', 120, .4, 0.,  0.,  0., 0., 0., 38., 0., 1., 1.,  .30, 1.,  0.,  0., .3,  0.,  0.),
    'error':                 ('ATENÇÃO',              0, .2,  0.,  0.,  0., 0., 0., 38., 0., 0., 1.,  .20, .5,  1.,  0., .3,  0.,  0.),
    'uncertain':             ('INCERTO',              0, .3,  0.,  0.,  0., 0., 0., 38., 0., 0., 1.,  .25, .7,  .6,  .3, .5,  0.,  0.),
    'partial':               ('RESULTADO PARCIAL',   40, 1.,  0.,  0.,  0., 0., 0., 38., 0., 0., .5,  .32, 1.,  0.,  0., 1.,  0.,  0.),
}
STATES = tuple(_TABLE)
HUD_LABELS = {state: row[0] for state, row in _TABLE.items()}
LOOKS = {state: HudLook(*map(float, row[1:])) for state, row in _TABLE.items()}
LOOK_FIELDS = tuple(f.name for f in fields(HudLook))


def look_for(state: str) -> HudLook:
    return LOOKS.get(state, LOOKS['idle'])


def label_for(state: str) -> str:
    return HUD_LABELS.get(state, HUD_LABELS['idle'])


def point_count(quality: str, orb_px: float) -> int:
    return 1800 if quality == 'low' or orb_px < 260 else 3200


@dataclass(frozen=True)
class HudLayout:
    cx: float
    cy: float
    R: float
    Rf: float
    label_y: float


def hud_layout(x: float, y: float, w: float, h: float) -> HudLayout:
    cy, R = y+.44*h, .215*min(w, h)
    Rf = 1.62*R
    return HudLayout(x+w/2, cy, R, Rf, cy+1.3*Rf)
