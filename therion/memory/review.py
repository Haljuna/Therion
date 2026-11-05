"""Revisão transitória de sensibilidade, separada de candidatos salváveis."""
from dataclasses import dataclass,replace
import time
import uuid
from therion.memory.knowledge import MemoryError,validate_candidate


@dataclass(frozen=True)
class LearningReview:
    id: str
    candidate: object
    policy: object
    deadline: float


class LearningReviews:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.items=[]
        self.notifications=[]

    def clear(self):
        self.items.clear();self.notifications.clear()

    def offer(self,candidate,policy):
        if candidate.sensitivity!='uncertain':
            raise MemoryError('Revisão reservada a sensibilidade incerta.')
        validate_candidate(candidate,for_review=True)
        self.items[:]=[r for r in self.items if self.clock()<r.deadline and r.policy==policy]
        if any(r.candidate.fingerprint==candidate.fingerprint and r.candidate.source==candidate.source for r in self.items):
            return
        if len(self.items)>=3:
            raise MemoryError('Limite de três revisões transitórias atingido.')
        row=LearningReview('REV-MEM-'+uuid.uuid4().hex[:12].upper(),candidate,policy,self.clock()+300)
        self.items.append(row);self.notifications.append(row.id)

    def current(self,session,policy,roots,resolver=None):
        self.items[:]=[r for r in self.items if r.candidate.session_id==session and r.policy==policy
            and self.clock()<r.deadline and r.candidate.source.valid(roots,resolver)]
        return tuple(self.items)

    def select(self,identifier,session,policy,roots,resolver=None):
        row=next((r for r in self.current(session,policy,roots,resolver) if r.id==identifier),None)
        if row is None:
            raise MemoryError('Revisão ausente, vencida ou invalidada por mudança de fonte, acesso ou sessão.')
        return row

    def reviewed_candidate(self,row):
        # Chamado somente após comando humano específico; ainda não autoriza escrita.
        candidate=replace(row.candidate,sensitivity='non_sensitive',
            reason=(row.candidate.reason[:220]+' Sensibilidade classificada explicitamente como não sensível pelo usuário; gravação ainda depende de prévia e confirmação.'))
        return validate_candidate(candidate)

    def remove(self,row):
        self.items.remove(row)
        self.notifications[:]=[value for value in self.notifications if value!=row.id]


def review_preview(row):
    c=row.candidate
    return (f'{row.id} — revisão necessária, não é candidato salvável.\nUtilidade: indício de {c.kind}. '
        f'Sensibilidade: incerta; não classifiquei como segura.\nConteúdo proposto: {c.summary}\n'
        f'Motivo: {c.reason}\nEvidência literal: {c.evidence}\nFonte: {c.source.identifier}\nVersão: {c.source.version}\n'
        f'Confira o conteúdo e a fonte. Para classificar explicitamente: "classifique a revisão {row.id} como não sensível". '
        f'Para descartar: "descarte a revisão {row.id}". Sim/não não classifica sensibilidade. '
        'Nada foi salvo; revisão volátil por cinco minutos. A classificação não substitui confirmação de gravação.')
