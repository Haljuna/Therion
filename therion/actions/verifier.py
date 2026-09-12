"""Verificador de resultados e evidências pós-execução da V0."""

import subprocess
import time
from dataclasses import dataclass

from therion.core.intent import Intent


@dataclass
class VerificationResult:
    """Resultado da verificação pós-execução."""

    success: bool
    message: str


class ActionVerifier:
    """Verificador de evidências de processos no Windows."""

    _PROCESS_MAP = {
        "Obsidian": "Obsidian.exe",
    }

    def verify_simulated(self, intent: Intent) -> str:
        """Verifica resultado em modo simulado."""
        if intent.action == "abrir aplicativo":
            return f"[Simulação] Processo do '{intent.target}' verificado como ativo."
        return f"[Simulação] Ação '{intent.action}' verificada com sucesso."

    def verify_real(
        self, intent: Intent, max_attempts: int = 3, interval: float = 0.5
    ) -> VerificationResult:
        """Verifica se o processo correspondente ao alvo foi iniciado no Windows."""
        if intent.action != "abrir aplicativo":
            return VerificationResult(
                success=False,
                message=f"Verificação não suportada para ação '{intent.action}'.",
            )

        process_name = self._PROCESS_MAP.get(intent.target)
        if not process_name:
            return VerificationResult(
                success=False,
                message=f"Nenhum processo conhecido mapeado para o alvo '{intent.target}'.",
            )

        # Checagem com tentativas curtas para acomodar o tempo de spawn no Windows
        for _ in range(max_attempts):
            try:
                res = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                )
                if process_name.lower() in res.stdout.lower():
                    return VerificationResult(
                        success=True,
                        message=f"Processo '{process_name}' verificado e ativo no Windows.",
                    )
            except Exception as err:
                return VerificationResult(
                    success=False,
                    message=f"Erro ao interrogar lista de processos: {err}",
                )

            time.sleep(interval)

        return VerificationResult(
            success=False,
            message=f"Processo '{process_name}' não foi localizado após a inicialização.",
        )
