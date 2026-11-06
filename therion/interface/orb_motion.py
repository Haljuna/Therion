"""Movimento contínuo da presença do Therion, sem acesso a áudio ou serviços."""
import math
from .presentation import normalized_level


SPEEDS = {
    'idle': 1.0, 'preparing': 1.15, 'listening': .8,
    'transcribing': 1.45, 'thinking': 1.65, 'executing': 1.85,
    'synthesizing': .95, 'speaking': 1.15,
    'awaiting_confirmation': .3, 'clarification': .4,
    'error': .28, 'uncertain': .3, 'partial': 1.0,
}
# Segundos por volta da casca da orbe holográfica; 0 = parada.
SPIN_SECONDS = {
    'idle': 40, 'preparing': 20, 'listening': 120, 'transcribing': 12,
    'thinking': 6, 'executing': 4, 'synthesizing': 20, 'speaking': 14,
    'awaiting_confirmation': 90, 'clarification': 90, 'error': 0, 'uncertain': 0, 'partial': 40,
}
EYE_LEVELS = {'error': .25, 'uncertain': .25, 'partial': .55}
THINKING_STATES = {'thinking', 'executing'}
SPEECH_STATES = {'synthesizing', 'speaking'}
WAITING_STATES = {'awaiting_confirmation', 'clarification'}
_IDLE_RATE, _FAST_RATE = math.tau/40, math.tau/4
FLASH_COOLDOWN = 4.
ASSEMBLY_SECONDS = 1.2


def spin_rate_for(state):
    seconds = SPIN_SECONDS.get(state, 40)
    return math.tau/seconds if seconds else 0.


MODE_STATES = ({'listening'}, {'thinking','transcribing','executing'},
               {'awaiting_confirmation','clarification'}, {'error','uncertain'})
ACTIVITY_STATES = ({'preparing'}, {'synthesizing'}, {'speaking'})
# Abertura, torção, atividade orbital e luz. São gestos do estado, não áudio.
EXPRESSIONS = {
    'idle': (0., .12, .18, .16),
    'preparing': (-.15, .45, .30, .35),
    'listening': (-.34, .18, .30, .35),
    'transcribing': (.10, .65, .50, .40),
    'thinking': (.18, .90, .65, .55),
    'executing': (.30, 1., 1., .80),
    'synthesizing': (-.12, .35, .25, .35),
    'speaking': (.08, .35, .40, .45),
    'awaiting_confirmation': (-.10, .03, 0., .20),
    'clarification': (-.10, .05, .03, .20),
    'error': (-.18, .02, 0., .05),
    'uncertain': (-.18, .02, 0., .08),
    'partial': (.08, .40, .35, .30),
}


class OrbMotion:
    """Um relógio integrado impede saltos ao mudar de estado ou de velocidade."""
    def __init__(self):
        self.state='idle'; self.phase=0.; self.speed=1.; self.energy=0.; self.tension=0.
        self.mode=[0.]*4; self.activity=[0.]*3; self.pulse=0.
        self.target_energy=0.; self._excitation=0.
        self.action=0.
        self.expression=list(EXPRESSIONS['idle'])
        # Canais da orbe holográfica.
        self.spin=0.; self.spin_rate=_IDLE_RATE; self.flash=0.; self.flash_ready_in=0.
        self.tint=0.; self.assembly=1.; self.clock=0.; self._eye_base=.7

    def set_visual(self,state,intensity=0.):
        state=state if state in SPEEDS else 'idle'
        if state!=self.state:
            self._excitation=1.
            if self.state in THINKING_STATES and state in SPEECH_STATES and self.flash_ready_in<=0:
                self.flash=1.; self.flash_ready_in=FLASH_COOLDOWN
            self.assembly=0. if state=='preparing' else 1.
            self.state=state
        reactive=state in {'listening','speaking'}
        self.target_energy=normalized_level(intensity) if reactive else 0.
        # Parar/cancelar a fala não deixa uma envoltória antiga modulando a cena.
        if not reactive: self.energy=0.

    def advance(self,seconds,*,reduced=False):
        target_mode=[float(self.state in states) for states in MODE_STATES]
        target_activity=[float(self.state in states) for states in ACTIVITY_STATES]
        if reduced:
            self.mode=target_mode; self.activity=target_activity
            self.action=float(self.state=='executing')
            self.expression=list(EXPRESSIONS[self.state])
            self.energy=self.tension=self.pulse=self._excitation=self.speed=0.
            self.spin_rate=self.flash=0.; self.assembly=1.
            self.tint=float(self.state in {'error','uncertain'})
            self._eye_base=EYE_LEVELS.get(self.state,.7)
            return
        dt=min(.1,max(0.,float(seconds))) if math.isfinite(seconds) else 0.
        if dt<=0.: return
        # Integração analítica: a cadência dos quadros não altera o movimento.
        target=SPEEDS[self.state]; decay=math.exp(-dt/.3)
        self.phase+=target*dt+(self.speed-target)*.3*(1.-decay)
        self.speed=target+(self.speed-target)*decay
        rate=spin_rate_for(self.state)
        self.spin+=rate*dt+(self.spin_rate-rate)*.3*(1.-decay)
        self.spin_rate=rate+(self.spin_rate-rate)*decay
        self.clock+=dt
        self.flash*=math.exp(-dt/.1); self.flash_ready_in-=dt
        self.assembly=min(1.,self.assembly+dt/ASSEMBLY_SECONDS) if self.state=='preparing' else 1.
        blend=1.-math.exp(-dt/.11)
        self.mode=[a+(b-a)*blend for a,b in zip(self.mode,target_mode)]
        self.activity=[a+(b-a)*blend for a,b in zip(self.activity,target_activity)]
        self.action+=(float(self.state=='executing')-self.action)*blend
        self.expression=[a+(b-a)*blend for a,b in zip(self.expression,EXPRESSIONS[self.state])]
        self.tint+=(float(self.state in {'error','uncertain'})-self.tint)*blend
        self._eye_base+=(EYE_LEVELS.get(self.state,.7)-self._eye_base)*blend
        tau=.065 if self.target_energy>self.energy else .17
        audio_decay=math.exp(-dt/tau); inertia=math.exp(-dt/.12)
        old_energy=self.energy
        self.energy=self.target_energy+(old_energy-self.target_energy)*audio_decay
        # A luz acompanha o áudio; a superfície retorna sem um corte de forma.
        self.tension=(self.target_energy+(self.tension-self.target_energy)*inertia
                      +(old_energy-self.target_energy)*tau/(tau-.12)*(audio_decay-inertia))
        # Um sinal de atenção suave, sem flashes e sem reiniciar o relógio.
        drive=math.exp(-dt/.28); response=math.exp(-dt/.13)
        self.pulse=self.pulse*response+self._excitation*.28/(.28-.13)*(drive-response)
        self._excitation*=drive

    @property
    def presence(self):
        return (*self.activity,self.pulse)

    @property
    def trail(self):
        return max(0.,min(1.,(self.spin_rate-_IDLE_RATE)/(_FAST_RATE-_IDLE_RATE)))

    @property
    def rim(self):
        if self.state=='listening': return self.energy
        if self.state in WAITING_STATES: return .5+.5*math.sin(math.pi*self.clock)
        return 0.

    @property
    def eye(self):
        speaking,synthesizing=self.activity[2],self.activity[1]
        return (self._eye_base+.5*self.energy*speaking
                +.15*math.sin(math.tau*self.clock/2.5)*synthesizing)
