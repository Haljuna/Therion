"""Contrato de IA central: AIResponse e AIProvider (A1)."""

from abc import ABC, abstractmethod
import re
from dataclasses import dataclass, field
from typing import FrozenSet, List, Literal, Optional


PLAN_REQUEST = "plan_request"
PLAN_REFERENCE = "plan_reference"
CONTEXT_REQUEST = "context_request"
CONTEXT_PURPOSES = frozenset({'profile_read', 'personal_summary'})

NON_EXECUTABLE_TYPES: FrozenSet[str] = frozenset({PLAN_REQUEST, PLAN_REFERENCE, CONTEXT_REQUEST})

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
        "chat", "action", "clarification", "plan_request", "plan_reference", "context_request"
    ]
    intent: Optional[str] = None
    arguments: dict = field(default_factory=dict)
    message: Optional[str] = None


@dataclass(frozen=True)
class PlanSection:
    """Seção mínima de plano: heading + body."""

    heading: str
    body: str
    duration_minutes: Optional[int] = None
    block_type: Optional[Literal["study", "break"]] = None


def plan_blocks(duration: int) -> list[tuple[str, int]]:
    """Distribuição controlada pela aplicação, incluindo três pausas curtas."""
    if duration < 19:
        return [("study", duration)]
    focus, remainder = divmod(duration - 15, 4)
    return [("study", focus), ("break", 5), ("study", focus), ("break", 5),
            ("study", focus), ("break", 5), ("study", focus + remainder)]


def plan_duration_minutes(message: str) -> Optional[int]:
    """Duração explícita do pedido; repetições equivalentes não são conflito.

    Formatos ambíguos/compostos ficam fora deste reconhecimento restrito.
    """
    numbers = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3,
               "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
               "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
               "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40,
               "cinquenta": 50, "sessenta": 60, "noventa": 90}
    pattern = r"(?<![\w.,])(" + r"\d+|" + "|".join(numbers) + r")\s*(horas?|h|min(?:utos?)?)(?!\w)"
    matches = list(re.finditer(pattern, message.casefold()))
    if not matches:
        return None
    durations = set()
    for match in matches:
        prefix, suffix = message[:match.start()].casefold(), message[match.end():].casefold()
        if re.search(r"(?:\d+[.,]|umas?|mais ou menos|cerca de|aproximadamente|entre|até|ate|\w+ e)\s*$", prefix):
            return None
        if re.match(r"\s*e\s+(?:meia|um quarto|\d+|" + "|".join(numbers) + r")\b", suffix):
            return None
        value = int(match[1]) if match[1].isdigit() else numbers[match[1]]
        durations.add(value * 60 if match[2].startswith("h") else value)
    return durations.pop() if len(durations) == 1 else None


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

    def compare_knowledge(self, evidence: dict, timeout_seconds: int = 20):
        """Comparação opcional, somente sobre fontes selecionadas; nenhuma ação."""
        return None

    def interpret_workflow_commands(self, message: str, context: Optional[dict] = None,
                                    timeout_seconds: int = 20) -> Optional[dict]:
        """Decomposição opcional em trechos literais, sem ações ou argumentos."""
        return None

    def extract_memory_candidates(self, evidence: dict, timeout_seconds: int = 20) -> list:
        """Operação opcional, sem ações. Providers anteriores não propõem memórias."""
        return []

    def describe_result(self, message: str, evidence: dict, context: dict) -> Optional[str]:
        """Interpreta resultados já obtidos, sem solicitar ou executar ações."""
        return None

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
