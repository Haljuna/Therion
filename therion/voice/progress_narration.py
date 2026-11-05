"""Avisos de andamento a partir de estados reais; não executa ações nem captura áudio."""
import time


class ProgressNarration:
    PHRASES = {
        'preparing': 'Estou preparando a resposta.',
        'checking': 'Estou verificando as informações.',
        'executing': 'Estou executando essa etapa.',
        'verifying': 'Estou conferindo o resultado.',
    }

    # Tarefas curtas (abrir um app, uma consulta) terminam sem aviso; só espera longa é narrada.
    def __init__(self, clock=time.monotonic, delay=6., interval=12., settle=2.):
        self.clock=clock;self.started=clock();self.delay=delay;self.interval=interval;self.settle=settle
        self.phase='preparing';self.phase_since=self.started;self.last_at=None;self.said=set();self.closed=False

    def _enter(self,phase):
        if phase!=self.phase:self.phase=phase;self.phase_since=self.clock()

    def observe(self,event):
        if self.closed:return
        kind=event.type;payload=event.payload
        if kind in {'terminal','awaiting_confirmation','provider_failed'}:
            self._enter(None)
        elif kind in {'thinking','provider_activity','decision_rejected'}:
            # Atividade do provedor não substitui o estado de uma ferramenta em execução.
            if kind!='provider_activity' or self.phase in {None,'preparing'}:self._enter('preparing')
        elif kind=='tool_started':
            # Este evento precede a última autorização; nunca anuncia execução.
            self._enter('checking')
        elif kind=='tool_running':
            self._enter({'read':'checking','prepare':'preparing','write':'executing','external':'executing'}.get(payload.get('effect'),'checking'))
        elif kind=='tool_finished':
            self._enter('verifying' if payload.get('status')=='success' else None)

    def next_phrase(self):
        now=self.clock()
        # A etapa precisa durar: uma ferramenta que acabou de terminar costuma ter resposta logo em seguida.
        if (self.closed or self.phase not in self.PHRASES or self.phase in self.said
                or len(self.said)>=2 or now-self.started<self.delay or now-self.phase_since<self.settle
                or self.last_at is not None and now-self.last_at<self.interval):return None
        self.said.add(self.phase);self.last_at=now
        return self.PHRASES[self.phase]

    def cancel(self):
        self.closed=True
