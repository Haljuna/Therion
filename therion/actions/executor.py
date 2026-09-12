"""Executor controlado de ações autorizadas da V0."""

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from therion.core.intent import Intent


@dataclass
class ActionResult:
    """Resultado da execução de uma ação."""

    success: bool
    message: str


class ActionExecutor:
    """Executor de ações permitidas na V0."""

    # Allowlist estrita contendo exclusivamente os caminhos seguros do Obsidian
    _ALLOWED_TARGETS = {
        "Obsidian": [
            os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "Programs", "Obsidian", "Obsidian.exe"
            ),
            r"C:\Program Files\Obsidian\Obsidian.exe",
        ]
    }

    def execute_simulated(self, intent: Intent) -> str:
        """Executa simulação lógica sem tocar no sistema operacional."""
        if intent.action == "abrir aplicativo":
            return f"[Simulação] Executado comando para abrir o aplicativo '{intent.target}'."
        return f"[Simulação] Ação '{intent.action}' executada."

    def execute_real(self, intent: Intent) -> ActionResult:
        """Executa a abertura real e controlada do aplicativo permitido no Windows."""
        if intent.action != "abrir aplicativo":
            return ActionResult(
                success=False,
                message=f"Ação '{intent.action}' não suportada para execução real.",
            )

        if intent.target not in self._ALLOWED_TARGETS:
            return ActionResult(
                success=False,
                message=f"Alvo '{intent.target}' não está na allowlist de execução.",
            )

        executable_path: Optional[str] = None
        for candidate_path in self._ALLOWED_TARGETS[intent.target]:
            if candidate_path and os.path.isfile(candidate_path):
                executable_path = candidate_path
                break

        if not executable_path:
            return ActionResult(
                success=False,
                message=(
                    f"Executável do '{intent.target}' não foi encontrado nos caminhos padrão."
                ),
            )

        try:
            # Execução segura: shell=False e lista estrita de argumentos (apenas o executável confiável)
            subprocess.Popen([executable_path], shell=False)
            return ActionResult(
                success=True,
                message=f"Comando de inicialização do {intent.target} enviado com sucesso.",
            )
        except Exception as err:
            return ActionResult(
                success=False,
                message=f"Erro ao iniciar {intent.target}: {err}",
            )
