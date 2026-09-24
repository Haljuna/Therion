"""Contrato de IA central: AIResponse e AIProvider (A1)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


class ProviderTransportError(RuntimeError):
    """Falha de transporte ou indisponibilidade do provedor de IA."""


class ProviderTimeoutError(RuntimeError):
    """Timeout na chamada ao provedor de IA."""


class ProviderResponseError(ValueError):
    """Resposta malformada ou inválida do provedor de IA."""


@dataclass(frozen=True)
class AIResponse:
    """Resposta estruturada de um AIProvider."""

    type: Literal["chat", "action", "clarification"]
    intent: Optional[str] = None
    arguments: dict = field(default_factory=dict)
    message: Optional[str] = None


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
