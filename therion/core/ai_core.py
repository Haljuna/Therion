"""AICore — camada central de classificação de IA (A1).

Recebe mensagem + contexto, pede inferência ao AIProvider,
valida deterministicamente a resposta e devolve AIResponse ou None.
"""

from typing import Optional

from therion.core.ai_provider import AIProvider, AIResponse


class AICore:
    """Ponto central de classificação de IA.

    Não executa ferramentas, não acessa APIs, não altera memória.
    Texto gerado pela IA nunca é executado diretamente.
    """

    VALID_TYPES = {"chat", "action", "clarification"}

    def __init__(self, provider: AIProvider, available_intents: list[str]) -> None:
        self._provider = provider
        self._available_intents = list(available_intents)

    def classify(
        self,
        message: str,
        context: dict,
    ) -> Optional[AIResponse]:
        """Classifica a mensagem do usuário.

        Returns:
            AIResponse validada, ou None em falha controlada (fallback seguro).
        """
        try:
            raw = self._provider.generate(
                message=message,
                context=context,
                available_intents=self._available_intents,
            )
        except Exception:
            return None

        if not self._validate(raw):
            return None
        return raw

    def _validate(self, response: Optional[AIResponse]) -> bool:
        """Validação determinística da resposta do provider."""
        if response is None:
            return False

        if response.type not in self.VALID_TYPES:
            return False

        if response.type == "action":
            if not isinstance(response.intent, str) or not response.intent:
                return False
            if response.intent not in self._available_intents:
                return False
            if not isinstance(response.arguments, dict):
                return False

        if response.type in ("chat", "clarification"):
            if not isinstance(response.message, str) or not response.message.strip():
                return False

        return True
