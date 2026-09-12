"""Protocolo e fluxo de confirmação com o usuário."""

from typing import Optional


class ConfirmationHandler:
    """Validador e interpretador de respostas de confirmação."""

    POSITIVE_RESPONSES = {"s", "sim", "y", "yes"}
    NEGATIVE_RESPONSES = {"n", "nao", "não", "no"}

    def evaluate_response(self, response: str) -> Optional[bool]:
        """Interpreta a resposta do usuário sem ambiguidade.

        Retorna True para afirmativo, False para negativo, ou None para resposta ambígua/inválida.
        """
        cleaned = response.strip().lower()
        if cleaned in self.POSITIVE_RESPONSES:
            return True
        if cleaned in self.NEGATIVE_RESPONSES:
            return False
        return None
