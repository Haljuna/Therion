"""AICore — camada central de classificação de IA (A1).

Recebe mensagem + contexto, pede inferência ao AIProvider,
valida deterministicamente a resposta e devolve AIResponse ou None.
"""

from dataclasses import dataclass
from typing import Optional

from therion.core.ai_provider import (
    AIProvider,
    AIResponse,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)

FAILURE_PROVIDER_UNAVAILABLE = "provider_unavailable"
FAILURE_PROVIDER_TIMEOUT = "provider_timeout"
FAILURE_INVALID_RESPONSE = "invalid_response"
FAILURE_REJECTED_BY_POLICY = "rejected_by_policy"


@dataclass(frozen=True)
class ClassifyOutcome:
    """Resultado detalhado da classificação: resposta válida OU motivo de falha."""

    response: Optional[AIResponse] = None
    failure: Optional[str] = None


class AICore:
    """Ponto central de classificação de IA.

    Não executa ferramentas, não acessa APIs, não altera memória.
    Texto gerado pela IA nunca é executado diretamente.
    """

    VALID_TYPES = {"chat", "action", "clarification"}
    ACTION_ALLOWLIST = {
        "abrir aplicativo",
        "listar aliases",
        "buscar segundo cérebro",
        "calendário hoje",
        "criar evento calendário",
    }

    def __init__(self, provider: AIProvider, available_intents: list[str]) -> None:
        self._provider = provider
        self._available_intents = list(available_intents)

    def classify(
        self,
        message: str,
        context: dict,
    ) -> Optional[AIResponse]:
        """Compatibilidade: devolve a resposta válida ou None em falha controlada."""
        return self.classify_detailed(message, context).response

    def classify_detailed(
        self,
        message: str,
        context: dict,
    ) -> ClassifyOutcome:
        """Classifica a mensagem preservando o motivo interno de falha.

        Returns:
            ClassifyOutcome com response válida OU failure com um dos motivos:
            provider_unavailable, provider_timeout, invalid_response,
            rejected_by_policy.
        """
        try:
            raw = self._provider.generate(
                message=message,
                context=context,
                available_intents=self._available_intents,
            )
        except ProviderTimeoutError:
            return ClassifyOutcome(failure=FAILURE_PROVIDER_TIMEOUT)
        except ProviderTransportError:
            return ClassifyOutcome(failure=FAILURE_PROVIDER_UNAVAILABLE)
        except ProviderResponseError:
            return ClassifyOutcome(failure=FAILURE_INVALID_RESPONSE)
        except Exception:
            return ClassifyOutcome(failure=FAILURE_PROVIDER_UNAVAILABLE)

        if raw is None:
            return ClassifyOutcome(failure=FAILURE_INVALID_RESPONSE)

        if not self._validate(raw):
            return ClassifyOutcome(failure=FAILURE_REJECTED_BY_POLICY)
        return ClassifyOutcome(response=raw)

    def _validate(self, response: Optional[AIResponse]) -> bool:
        """Validação determinística da resposta do provider."""
        if response is None:
            return False

        if response.type not in self.VALID_TYPES:
            return False

        if not isinstance(response.message, str) or not response.message.strip():
            return False

        if response.type == "action":
            if not isinstance(response.intent, str) or not response.intent:
                return False
            if response.intent not in self._available_intents:
                return False
            if response.intent not in self.ACTION_ALLOWLIST:
                return False
            if not isinstance(response.arguments, dict):
                return False
            if not self._validate_action_arguments(response.intent, response.arguments):
                return False

        if response.type in ("chat", "clarification"):
            if response.intent is not None:
                return False
            if response.arguments != {}:
                return False

        return True

    def _validate_action_arguments(self, intent: str, args: dict) -> bool:
        """Validação de arguments contra o schema fechado da intent."""
        if intent == "abrir aplicativo":
            if set(args.keys()) != {"target"}:
                return False
            target = args["target"]
            return isinstance(target, str) and bool(target.strip())

        if intent == "listar aliases":
            return args == {}

        if intent == "buscar segundo cérebro":
            if set(args.keys()) != {"term"}:
                return False
            term = args["term"]
            return isinstance(term, str) and bool(term.strip())

        if intent == "calendário hoje":
            return args == {}

        if intent == "criar evento calendário":
            keys = set(args.keys())
            required = {"title", "date", "start_time"}
            if not required.issubset(keys):
                return False
            allowed = required | {"duration_minutes"}
            if not keys.issubset(allowed):
                return False
            for field in required:
                val = args[field]
                if not isinstance(val, str) or not val.strip():
                    return False
            if "duration_minutes" in args:
                dur = args["duration_minutes"]
                if type(dur) is not int or dur <= 0:
                    return False
            return True

        return False
