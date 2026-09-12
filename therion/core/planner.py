"""Planejador de etapas e mini-planos da V0."""

from dataclasses import dataclass
from typing import List

from therion.core.intent import Intent


@dataclass
class Plan:
    """Estrutura do mini-plano gerado."""

    intent: Intent
    steps: List[str]


class Planner:
    """Gerador de mini-planos para ações da V0."""

    def create_plan(self, intent: Intent) -> Plan:
        """Gera as etapas de execução e verificação proporcionais à intenção."""
        if intent.action == "abrir aplicativo":
            steps = [
                f"Abrir o {intent.target}.",
                "Verificar se o processo iniciou.",
            ]
            return Plan(intent=intent, steps=steps)

        return Plan(intent=intent, steps=["Ação não reconhecida no planejamento."])
