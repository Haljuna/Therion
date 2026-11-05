"""Estado visual puro; não concede permissões nem executa ações."""
from dataclasses import dataclass
import math


LABELS = {
    'idle': 'Pronto para conversar', 'preparing': 'Preparando recursos…',
    'listening': 'Estou ouvindo…', 'transcribing': 'Transcrevendo…',
    'thinking': 'Pensando…', 'executing': 'Executando tarefa…',
    'synthesizing': 'Preparando a fala…', 'speaking': 'Falando…',
    'awaiting_confirmation': 'Aguardando sua confirmação',
    'error': 'Preciso da sua atenção', 'uncertain': 'Resultado incerto',
    'clarification': 'Aguardando sua resposta', 'partial': 'Resultado parcial',
}


@dataclass(frozen=True)
class WorkspacePresentation:
    """Contexto visual apenas; nenhuma autorização ou dado de serviço."""
    active_window: str = ''
    visible_windows: tuple = ()
    orb_rect: tuple = ()
    attention: float = 1.0


@dataclass
class Presentation:
    interaction: str = 'idle'
    speech: str = 'idle'
    capture: str = 'idle'
    confirmation: bool = False
    last_response: str = ''
    intensity: float = 0.0

    @property
    def state(self):
        if self.confirmation:
            return 'awaiting_confirmation'
        if self.interaction in {'error', 'uncertain'}:
            return self.interaction
        if self.speech == 'playing':
            return 'speaking'
        if self.capture == 'recording':
            return 'listening'
        if self.capture == 'transcribing':
            return 'transcribing'
        if self.interaction in {'thinking', 'executing'}:
            return self.interaction
        if self.speech in {'warming', 'synthesizing'}:
            return 'synthesizing'
        return self.interaction if self.interaction in LABELS else 'idle'

    @property
    def label(self):
        return LABELS[self.state]


def normalized_level(value):
    try:
        value = float(value)
        return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


class QualityController:
    """Ajuste por janelas estáveis; evita oscilar e nunca interfere na voz."""
    LEVELS = ('low', 'medium', 'high')
    COUNTS = {'low': 12000, 'medium': 28000, 'high': 48000}

    def __init__(self, requested='auto'):
        self.requested = requested
        self.level = requested if requested in self.LEVELS else 'medium'
        self.samples = []
        self.good_windows = 0

    def observe(self, seconds):
        if self.requested != 'auto' or seconds <= 0:
            return False
        self.samples.append(seconds)
        if len(self.samples) < 150:
            return False
        average = sum(self.samples) / len(self.samples)
        self.samples.clear()
        index = self.LEVELS.index(self.level)
        if average > 0.040 and index:
            self.level = self.LEVELS[index - 1]
            self.good_windows = 0
            return True
        self.good_windows = self.good_windows + 1 if average < 0.035 else 0
        # Alto só é tentado após três janelas estáveis; se cair, volta ao médio.
        if self.good_windows >= 3 and index < 2:
            self.level = self.LEVELS[index + 1]
            self.good_windows = 0
            return True
        return False
