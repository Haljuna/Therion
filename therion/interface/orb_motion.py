"""Movimento contínuo da Orbe HUD, sem acesso a áudio ou serviços."""
import math
from .hud_frame import FrameState
from .hud_style import GAME_LABEL, HudLook, LOOKS, LOOK_FIELDS, label_for, look_for
from .presentation import normalized_level

THINKING_STATES = {'thinking', 'executing'}
SPEECH_STATES = {'synthesizing', 'speaking'}
VOICE_STATES = {'listening', 'speaking'}
FLASH_COOLDOWN = 4.
SPIN_EASE = .55   # segundos; acelerar e frear devagar parece menos mecânico
LOOK_EASE = .25
ASSEMBLY_SECONDS = 1.2
BLINK_SECONDS, ALERT_SECONDS = 1.6, 3.


def _wave(clock, period):
    """0 → 1 → 0 a cada período."""
    return .5-.5*math.cos(math.tau*clock/period)


class OrbMotion:
    """Relógios integrados impedem saltos ao mudar de estado ou de velocidade."""
    def __init__(self):
        self.state = 'idle'
        self.look = LOOKS['idle']
        self.clock = 0.
        self.energy = self.target_energy = 0.
        self.pulse = self._excitation = 0.
        self.spin = 0.; self.spin_rate = math.tau/LOOKS['idle'].spin_seconds
        self.flash = 0.; self.flash_ready_in = 0.; self.assembly = 1.
        self.sweep_phase = self.orbit_phase = self.frame_spin = self.arc_angle = 0.
        self.reduced = False
        self.game = self.game_target = 0.   # modo de jogo: 0 = azul, 1 = arcos e núcleo vermelhos

    def set_game(self, on):
        self.game_target = 1. if on else 0.

    def set_visual(self, state, intensity=0.):
        state = state if state in LOOKS else 'idle'
        if state != self.state:
            self._excitation = 1.
            if self.state in THINKING_STATES and state in SPEECH_STATES and self.flash_ready_in <= 0:
                self.flash = 1.; self.flash_ready_in = FLASH_COOLDOWN
            if state == 'preparing':
                self.assembly = 0.
            self.state = state
        reactive = state in VOICE_STATES
        self.target_energy = normalized_level(intensity) if reactive else 0.
        # Parar/cancelar a fala não deixa uma envoltória antiga modulando a cena.
        if not reactive:
            self.energy = 0.

    def advance(self, seconds, *, reduced=False):
        self.reduced = reduced
        target = look_for(self.state)
        if reduced:
            self.look = target
            self.energy = self.pulse = self._excitation = self.spin_rate = self.flash = 0.
            self.assembly = 1.
            self.game = self.game_target
            return
        dt = min(.1, max(0., float(seconds))) if math.isfinite(seconds) else 0.
        if dt <= 0.:
            return
        self.clock += dt
        blend = 1.-math.exp(-dt/LOOK_EASE)
        self.game += (self.game_target-self.game)*blend
        look = self.look = HudLook(*(getattr(self.look, name)+(getattr(target, name)-getattr(self.look, name))*blend
                                    for name in LOOK_FIELDS))
        # Integração analítica: a cadência dos quadros não altera o giro.
        rate = math.tau/target.spin_seconds if target.spin_seconds else 0.
        ease = math.exp(-dt/SPIN_EASE)
        self.spin += rate*dt+(self.spin_rate-rate)*SPIN_EASE*(1.-ease)
        self.spin_rate = rate+(self.spin_rate-rate)*ease
        self.sweep_phase += dt*look.sweep_speed
        self.orbit_phase += dt*look.orbit_speed
        self.frame_spin += dt*(.15+1.4*look.arc_spin)
        # Os arcos giram só enquanto o estado pede; depois assentam na posição de descanso
        # mais próxima (meia volta é igual, porque são dois arcos opostos).
        settle = max(0., 1.-look.arc_spin/.1)   # só puxa para o descanso quando o giro quase acabou
        rest = round(self.arc_angle/math.pi)*math.pi
        self.arc_angle += dt*.78*look.arc_spin-(self.arc_angle-rest)*settle*(1.-math.exp(-dt/.4))
        self.flash *= math.exp(-dt/.1); self.flash_ready_in -= dt
        # Continua montando mesmo se o estado mudar antes do fim: sair cedo não dá estalo.
        self.assembly = min(1., self.assembly+dt/ASSEMBLY_SECONDS)
        # A voz sobe rápido e desce devagar. Na fala do Therion (áudio limpo) a resposta é mais
        # curta para cada sílaba aparecer; no microfone do usuário fica suave por causa do ruído.
        rise, fall = (.03, .07) if self.state == 'speaking' else (.065, .17)
        tau = rise if self.target_energy > self.energy else fall
        self.energy = self.target_energy+(self.energy-self.target_energy)*math.exp(-dt/tau)
        # Um sinal de atenção suave na troca de estado, sem reiniciar relógios.
        drive = math.exp(-dt/.28); response = math.exp(-dt/.13)
        self.pulse = self.pulse*response+self._excitation*.28/(.28-.13)*(drive-response)
        self._excitation *= drive

    @property
    def trail(self):
        return 0. if self.reduced else self.look.trail

    @property
    def red(self):
        """Peso do vermelho do modo de jogo; o âmbar do alerta ganha dele."""
        return max(0., min(1., self.game*(1.-self.look.amber)))

    @property
    def voice(self):
        """A voz do próprio Therion empurrando a superfície."""
        return max(0., min(1., self.energy*self.look.voice_bulge))

    @property
    def level(self):
        look = self.look
        level = (.15+look.sweep*(.15+.1*math.sin(self.clock*4.))
                 +look.voice_bulge*self.energy+look.listen_wave*(.1+.75*self.energy))
        return max(0., min(1., level))

    @property
    def blink(self):
        """Opacidade dos arcos: pisca na espera, pulsa devagar no alerta."""
        if self.reduced:
            return 1.
        return (1.-self.look.arc_blink*_wave(self.clock, BLINK_SECONDS))*(
            1.-.4*self.look.amber*_wave(self.clock, ALERT_SECONDS))

    def frame_state(self) -> FrameState:
        look = self.look
        label = GAME_LABEL if self.state == 'idle' and self.game_target else label_for(self.state)
        return FrameState(label=label, level=self.level,
                          arc_deg=look.arc_deg+10.*self.voice,
                          arc_scale=look.arc_scale*(.3+.7*self.assembly),
                          arc_rotation=self.arc_angle, tick_rotation=self.frame_spin*.3,
                          dash_rotation=self.frame_spin*.6, blink=self.blink, amber=look.amber,
                          voice_ring=look.voice_ring, voice=self.voice, game=self.game)
