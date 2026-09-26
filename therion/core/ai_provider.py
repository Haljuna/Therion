"""Contrato de IA central: AIResponse e AIProvider (A1)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import FrozenSet, List, Literal, Optional


PLAN_REQUEST = "plan_request"
PLAN_REFERENCE = "plan_reference"

NON_EXECUTABLE_TYPES: FrozenSet[str] = frozenset({PLAN_REQUEST, PLAN_REFERENCE})

PLAN_REFERENCE_SELECTORS: FrozenSet[str] = frozenset(
    {"first", "second", "last", "previous", "same"}
)


class ProviderTransportError(RuntimeError):
    """Falha de transporte ou indisponibilidade do provedor de IA."""


class ProviderTimeoutError(RuntimeError):
    """Timeout na chamada ao provedor de IA."""


class ProviderResponseError(ValueError):
    """Resposta malformada ou inválida do provedor de IA."""


@dataclass(frozen=True)
class AIResponse:
    """Resposta estruturada de um AIProvider."""

    type: Literal[
        "chat", "action", "clarification", "plan_request", "plan_reference"
    ]
    intent: Optional[str] = None
    arguments: dict = field(default_factory=dict)
    message: Optional[str] = None


@dataclass(frozen=True)
class PlanSection:
    """Seção mínima de plano: heading + body."""

    heading: str
    body: str


@dataclass(frozen=True)
class PlanContent:
    """Estrutura mínima de conteúdo de plano conversacional (E1).

    title é opcional (default None); sections é obrigatório e carrega
    o conteúdo estruturado real. Não existe campo complete.
    """

    sections: List[PlanSection]
    title: Optional[str] = None


class AIProvider(ABC):
    """Interface abstrata para provedores de inferência de IA."""

    @abstractmethod
    def generate(
        self,
        message: str,
        context: dict,
        available_intents: list[str],
    ) -> AIResponse:
        """Gera uma classificação estruturada a partir da mensagem do usuário.

        Args:
            message: Texto do usuário.
            context: Snapshot somente leitura do contexto da sessão.
            available_intents: Allowlist de intents que o sistema aceita.

        Returns:
            AIResponse com type, intent, arguments e/ou message.
        """
        ...

    @abstractmethod
    def generate_plan(
        self,
        message: str,
        context: dict,
    ) -> PlanContent:
        """Gera conteúdo de plano dirigido a partir da mensagem do usuário.

        Args:
            message: Texto do usuário.
            context: Snapshot somente leitura do contexto da sessão.

        Returns:
            PlanContent estruturado (E1/M1).
        """
        ...
