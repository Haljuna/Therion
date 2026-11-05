"""Protocolo e fluxo de confirmação com o usuário."""

from typing import Optional
import re


class ConfirmationHandler:
    """Validador e interpretador de respostas de confirmação."""

    POSITIVE_RESPONSES = {"s", "sim", "y", "yes"}
    NEGATIVE_RESPONSES = {"n", "nao", "não", "no", "cancela", "cancelar", "cancele"}

    def evaluate_response(self, response: str) -> Optional[bool]:
        """Interpreta a resposta do usuário sem ambiguidade.

        Retorna True para afirmativo, False para negativo, ou None para resposta ambígua/inválida.
        """
        cleaned = response.strip().lower()
        if re.fullmatch(r'pode[.!]*', cleaned):
            return True
        # Repetições orais homogêneas continuam sendo uma resposta inequívoca.
        # Misturas como "sim, não" ou frases adicionais não autorizam nada.
        repeated = re.split(r'[\s,.!?]+', cleaned.strip(' ,.!?'))
        if (2 <= len(repeated) <= 3 and len(set(repeated)) == 1
                and repeated[0] in self.POSITIVE_RESPONSES | self.NEGATIVE_RESPONSES):
            cleaned = repeated[0]
        if cleaned.rstrip('.!?').strip() in {'cancela', 'cancelar', 'cancele'}:
            return False
        if cleaned in self.POSITIVE_RESPONSES:
            return True
        if cleaned in self.NEGATIVE_RESPONSES:
            return False
        return None
