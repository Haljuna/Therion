"""Estado efêmero de planos da sessão (E1/M3).

Nada é persistido em disco; o estado vive apenas na sessão em memória.
Nenhum método concede autoridade, permissão ou acesso.
"""

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PlanCandidate:
    """Candidate pendente a plano, com identidade estável."""

    candidate_id: str
    text: str


@dataclass(frozen=True)
class RegisteredPlan:
    """Plano registrado na sessão, com texto integral preservado."""

    plan_id: str
    text: str


@dataclass(frozen=True)
class PlanAckResult:
    """Resultado do registro/ACK de um candidate exibido.

    status: "registered" ou "displayed_not_registered".
    plan_id presente somente quando status == "registered".
    reason presente somente quando status == "displayed_not_registered".
    """

    status: str
    plan_id: Optional[str] = None
    reason: Optional[str] = None


class PlanSessionState:
    """Estado efêmero de planos da sessão (E1/M3).

    Regras:
    - no máximo 1 candidate pendente;
    - candidate recusado não substitui o pendente;
    - registro preserva o texto integral e a ordem de registro;
    - plan_id é estável após o registro;
    - current_plan_id aponta para o plano registrado mais recente;
    - clear_session limpa candidate, registry, ordem e current_plan_id.
    """

    def __init__(self) -> None:
        self._candidate: Optional[PlanCandidate] = None
        self._registry: Dict[str, RegisteredPlan] = {}
        self._order: List[str] = []
        self._current_plan_id: Optional[str] = None

    @property
    def candidate(self) -> Optional[PlanCandidate]:
        """Candidate pendente, ou None."""
        return self._candidate

    @property
    def current_plan_id(self) -> Optional[str]:
        """plan_id do plano registrado atual, ou None."""
        return self._current_plan_id

    @property
    def order(self) -> Tuple[str, ...]:
        """Ordem estável de registro dos plan_id."""
        return tuple(self._order)

    def get_plan(self, plan_id: str) -> Optional[RegisteredPlan]:
        """Recupera um plano registrado pelo plan_id, ou None."""
        return self._registry.get(plan_id)

    def ack_registered_plan_displayed(self, plan_id: str) -> bool:
        """Aponta current_plan_id para um plano já registrado.

        Retorna False sem alterar estado se o plan_id não existir.
        Retorna True e atualiza apenas current_plan_id se existir.
        """
        if plan_id not in self._registry:
            return False
        self._current_plan_id = plan_id
        return True

    def resolve_plan_reference(self, selector: str) -> Optional[str]:
        """Resolve um seletor canônico para plan_id, sem mutar estado (E1/M7b).

        Selectors: first, second, last, same, previous.
        Caso canônico porém impossível (sem planos, sem current, current
        primeiro) retorna None. Selector fora do conjunto canônico levanta
        ValueError. A resolução não altera candidate, registry, order,
        current_plan_id nem limites.
        """
        if selector == "first":
            return self._order[0] if self._order else None
        if selector == "second":
            return self._order[1] if len(self._order) > 1 else None
        if selector == "last":
            return self._order[-1] if self._order else None
        if selector == "same":
            return self._current_plan_id
        if selector == "previous":
            if self._current_plan_id is None:
                return None
            index = self._order.index(self._current_plan_id)
            return self._order[index - 1] if index > 0 else None
        raise ValueError(f"selector de plano desconhecido: {selector!r}")

    def set_candidate(self, text: str) -> Optional[str]:
        """Cria o candidate pendente e devolve seu candidate_id.

        Se já houver candidate pendente, recusa (None) sem substituir.
        Texto deve ser string não vazia após strip.
        """
        if self._candidate is not None:
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        candidate = PlanCandidate(candidate_id=str(uuid.uuid4())[:8], text=text)
        self._candidate = candidate
        return candidate.candidate_id

    def register_candidate(self, candidate_id: str) -> PlanAckResult:
        """Registra o candidate pendente identificado por candidate_id.

        Sem candidate pendente: displayed_not_registered(candidate_missing).
        candidate_id diferente do pendente: displayed_not_registered(
        candidate_mismatch), sem consumir o candidate atual.
        Limites na ordem: per_plan_limit (texto > 6000), count_limit
        (registrados >= 5), total_limit (total registrado + texto > 15000).
        Rejeição por limite é terminal: remove candidate, zera
        current_plan_id e não cria plan_id nem altera registry/ordem.
        Sucesso: texto integral preservado, plan_id novo, registry e ordem
        atualizados, candidate consumido.
        """
        if self._candidate is None:
            return PlanAckResult(
                status="displayed_not_registered", reason="candidate_missing"
            )
        if candidate_id != self._candidate.candidate_id:
            return PlanAckResult(
                status="displayed_not_registered", reason="candidate_mismatch"
            )

        text = self._candidate.text
        reason: Optional[str] = None
        if len(text) > 6000:
            reason = "per_plan_limit"
        elif len(self._order) >= 5:
            reason = "count_limit"
        else:
            total = sum(len(self._registry[p].text) for p in self._order)
            if total + len(text) > 15000:
                reason = "total_limit"

        if reason is not None:
            self._candidate = None
            self._current_plan_id = None
            return PlanAckResult(status="displayed_not_registered", reason=reason)

        plan_id = str(uuid.uuid4())[:8]
        while plan_id in self._registry:
            plan_id = str(uuid.uuid4())[:8]
        plan = RegisteredPlan(plan_id=plan_id, text=text)
        self._registry[plan_id] = plan
        self._order.append(plan_id)
        self._current_plan_id = plan_id
        self._candidate = None
        return PlanAckResult(status="registered", plan_id=plan_id)

    def clear_session(self) -> None:
        """Limpa candidate, registry, ordem e current_plan_id."""
        self._candidate = None
        self._registry.clear()
        self._order.clear()
        self._current_plan_id = None
