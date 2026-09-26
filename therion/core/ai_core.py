"""AICore — camada central de classificação de IA (A1).

Recebe mensagem + contexto, pede inferência ao AIProvider,
valida deterministicamente a resposta e devolve AIResponse ou None.
"""

from dataclasses import dataclass
from typing import Optional

from therion.core.ai_provider import (
    AIProvider,
    AIResponse,
    NON_EXECUTABLE_TYPES,
    PLAN_REFERENCE,
    PLAN_REFERENCE_SELECTORS,
    PLAN_REQUEST,
    PlanContent,
    PlanSection,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransportError,
)

FAILURE_PROVIDER_UNAVAILABLE = "provider_unavailable"
FAILURE_PROVIDER_TIMEOUT = "provider_timeout"
FAILURE_INVALID_RESPONSE = "invalid_response"
FAILURE_REJECTED_BY_POLICY = "rejected_by_policy"


def validate_plan_content(plan: object) -> bool:
    """Validação estrutural determinística de PlanContent (E1/M1).

    Regras:
    - plan deve ser PlanContent;
    - sections deve ter pelo menos 1 item;
    - cada item deve ser PlanSection;
    - heading: str não vazia após strip;
    - body: str não vazia após strip;
    - title pode ser None; se presente, deve ser str;
    - não usa campo complete;
    - não valida limite de tamanho (posteriores à M1).
    """
    if not isinstance(plan, PlanContent):
        return False

    if not isinstance(plan.sections, list) or len(plan.sections) < 1:
        return False

    for section in plan.sections:
        if not isinstance(section, PlanSection):
            return False
        if not isinstance(section.heading, str) or not section.heading.strip():
            return False
        if not isinstance(section.body, str) or not section.body.strip():
            return False

    if plan.title is not None and not isinstance(plan.title, str):
        return False

    return True


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

    VALID_TYPES = {"chat", "action", "clarification"} | set(NON_EXECUTABLE_TYPES)
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

    def generate_plan_detailed(
        self,
        message: str,
        context: dict,
    ) -> tuple[Optional[PlanContent], Optional[str]]:
        """Gera plano dirigido preservando o motivo interno de falha.

        Returns:
            Tupla (plan, failure): sucesso = (PlanContent válido por
            validate_plan_content, None); falha = (None, uma das
            constantes FAILURE_* existentes).
        """
        try:
            plan = self._provider.generate_plan(message=message, context=context)
        except ProviderTimeoutError:
            return None, FAILURE_PROVIDER_TIMEOUT
        except ProviderTransportError:
            return None, FAILURE_PROVIDER_UNAVAILABLE
        except ProviderResponseError:
            return None, FAILURE_INVALID_RESPONSE
        except Exception:
            return None, FAILURE_PROVIDER_UNAVAILABLE

        if plan is None:
            return None, FAILURE_INVALID_RESPONSE

        if not validate_plan_content(plan):
            return None, FAILURE_REJECTED_BY_POLICY

        return plan, None

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

        if response.type in NON_EXECUTABLE_TYPES:
            if response.intent is not None:
                return False
            if not isinstance(response.arguments, dict):
                return False
            if response.type == PLAN_REQUEST:
                if response.arguments != {}:
                    return False
            elif response.type == PLAN_REFERENCE:
                if not self._validate_plan_reference_arguments(response.arguments):
                    return False

        return True

    def _validate_plan_reference_arguments(self, args: dict) -> bool:
        """Validação da referência fechada a plano existente (E1/M2).

        Regras:
        - arguments deve ter exatamente a chave "reference";
        - o valor deve ser uma string do conjunto fechado:
          first, second, last, previous, same.
        """
        if set(args.keys()) != {"reference"}:
            return False
        selector = args["reference"]
        if not isinstance(selector, str):
            return False
        return selector in PLAN_REFERENCE_SELECTORS

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
