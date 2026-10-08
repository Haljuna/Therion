"""AICore — camada central de classificação de IA (A1).

Recebe mensagem + contexto, pede inferência ao AIProvider,
valida deterministicamente a resposta e devolve AIResponse ou None.
"""

import re
from dataclasses import dataclass, replace
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
    plan_duration_minutes,
    plan_blocks,
)

FAILURE_PROVIDER_UNAVAILABLE = "provider_unavailable"
FAILURE_PROVIDER_TIMEOUT = "provider_timeout"
FAILURE_INVALID_RESPONSE = "invalid_response"
FAILURE_REJECTED_BY_POLICY = "rejected_by_policy"
FAILURE_PLAN_DURATION = "plan_duration_invalid"
FAILURE_PLAN_CONTENT = "plan_content_invalid"
FAILURE_PLAN_BLOCKS = "plan_blocks_invalid"


def _explicit_plan_request(message: str) -> bool:
    """Pedido textual de geração; referências e comandos externos ficam fora."""
    if re.search(r"\b(?:abra|abrir|envie|enviar|execute|executar|agende|agendar|apague|exclua)\b", message, re.I):
        return False
    return re.match(
        r"^\s*(?:por favor[,\s]+)?(?:"
        r"(?:monte|gere|crie|prepare|elabore)\s+(?:um|uma|o|a)\s+"
        r"|(?:quero|preciso de)\s+(?:um|uma)\s+"
        r"|quero que (?:voc[eê] )?(?:monte|gere|crie|prepare|elabore)\s+(?:um|uma)\s+"
        r")(?:plano|roteiro)\b", message, re.I,
    ) is not None


def _resolved_plan_request(message: str, context: dict) -> Optional[str]:
    if _explicit_plan_request(message):
        return message
    if message.strip().casefold().rstrip(".!?") not in {
        "pode mandar", "pode mandar o plano", "pode gerar", "pode gerar o plano",
    }:
        return None
    history = (context or {}).get("recent_turns", [])
    if not isinstance(history, (list, tuple)) or len(history) < 2:
        return None
    user, assistant = history[-2:]
    if not isinstance(user, dict) or not isinstance(assistant, dict):
        return None
    request, reply = user.get("text"), assistant.get("text")
    if user.get("role") != "user" or assistant.get("role") != "therion":
        return None
    if not isinstance(request, str) or not isinstance(reply, str):
        return None
    if _explicit_plan_request(request) and re.search(
        r"\b(?:vou (?:montar|gerar|preparar)|aqui est[aá])\b.*\b(?:plano|roteiro)\b", reply, re.I,
    ):
        return request
    return None

_PLAN_REFERENCE_CUES = {
    "first": re.compile(r"\bprimeir[oa]\b", re.IGNORECASE),
    "second": re.compile(r"\bsegund[oa]\b", re.IGNORECASE),
    "last": re.compile(r"\b[úu]ltim[oa]\b", re.IGNORECASE),
    "previous": re.compile(r"\banterior\b", re.IGNORECASE),
    "same": re.compile(r"\bmesm[oa]\b", re.IGNORECASE),
}


def _explicit_plan_reference_selector(message: str) -> Optional[str]:
    """Devolve um seletor só quando o turno atual contém uma única pista explícita."""
    matches = [
        selector
        for selector, pattern in _PLAN_REFERENCE_CUES.items()
        if pattern.search(message)
    ]
    return matches[0] if len(matches) == 1 else None


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
        if _resolved_plan_request(message, context) is not None:
            return ClassifyOutcome(response=AIResponse(
                type=PLAN_REQUEST, message="Vou gerar o plano solicitado.",
            ))
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

        if raw.type == PLAN_REFERENCE and raw.intent is None and raw.arguments == {}:
            selector = _explicit_plan_reference_selector(message)
            if selector is not None:
                raw = replace(raw, arguments={"reference": selector})

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
        message = _resolved_plan_request(message, context) or message
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
            if plan_duration_minutes(message) is not None:
                return None, FAILURE_PLAN_CONTENT
            return None, FAILURE_REJECTED_BY_POLICY

        duration = plan_duration_minutes(message)
        if duration is not None:
            times = [section.duration_minutes for section in plan.sections]
            if any(type(value) is not int or value <= 0 for value in times):
                return None, FAILURE_PLAN_DURATION
            if sum(times) != duration:
                return None, FAILURE_PLAN_DURATION
            expected = plan_blocks(duration)
            if [(s.block_type, s.duration_minutes) for s in plan.sections] != expected:
                return None, FAILURE_PLAN_BLOCKS
            if any(s.block_type == "study" and re.match(
                r"\s*(?:pausa|descanso|intervalo)\b", s.heading, re.I,
            ) for s in plan.sections):
                return None, FAILURE_PLAN_BLOCKS

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
