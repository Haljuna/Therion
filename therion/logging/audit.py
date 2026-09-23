"""Sistema de logs e auditoria técnica mínima da V0."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AuditLogger:
    """Registrador de auditoria estruturada em formato JSON Lines (.jsonl)."""

    DEFAULT_LOG_DIR = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
        )
    )

    # Padrões regex para mascarar credenciais e segredos conhecidos.
    # Cada entrada é uma tupla (pattern, replacement) para permitir replacements
    # distintos: patterns com grupo capturado usam \1, sem grupo usam literal.
    _SENSITIVE_PATTERNS = [
        (
            re.compile(r"(?i)(password|senha)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?"),
            r"\1: [REDACTED]",
        ),
        (
            re.compile(r"(?i)(token|bearer|api[_\-]?key)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?"),
            r"\1: [REDACTED]",
        ),
        (
            re.compile(r"sk-[a-zA-Z0-9]{20,}"),
            "[REDACTED]",
        ),
    ]
    _PATH_REDACTION = "[CAMINHO ABSOLUTO REDIGIDO]"
    # Uma raiz Windows absoluta começa por letra de drive + separador ou por
    # servidor UNC + separador. Caminhos relativos não casam esses prefixos.
    _PATH_PREFIX = r"(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/])"
    _QUOTED_PATH = re.compile(
        r"(['\"])" + _PATH_PREFIX + r"[^\r\n]*?\1"
    )
    _UNQUOTED_PATH = re.compile(
        r"(?<![A-Za-z0-9])" + _PATH_PREFIX + r"[^\r\n]*"
    )

    def __init__(
        self, log_dir: Optional[str] = None, log_file: str = "audit.jsonl"
    ) -> None:
        self.log_dir = os.path.abspath(log_dir or self.DEFAULT_LOG_DIR)
        self.log_file = log_file
        self.log_path = os.path.join(self.log_dir, self.log_file)

    def sanitize(self, text: Optional[str]) -> Optional[str]:
        """Mascara segredos e caminhos absolutos Windows antes de serializar."""
        if text is None:
            return None

        sanitized = text
        for pattern, replacement in self._SENSITIVE_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)

        # Entre aspas, a mesma aspa delimita o caminho e o restante da frase
        # permanece. O padrão nunca cruza uma quebra de linha.
        sanitized = self._QUOTED_PATH.sub(
            lambda match: match.group(1) + self._PATH_REDACTION + match.group(1),
            sanitized,
        )
        # Sem aspas, espaços tornam o fim do caminho ambíguo. Redigir até o
        # fim da linha evita deixar fragmentos do caminho no audit log.
        sanitized = self._UNQUOTED_PATH.sub(self._PATH_REDACTION, sanitized)

        return sanitized

    def sanitize_context_queries(
        self, queries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Garante que apenas metadados (caminho/status) sejam registrados, sem o conteúdo das notas."""
        sanitized_queries = []
        for q in queries:
            sanitized_queries.append(
                {
                    "path": self.sanitize(q.get("path")),
                    "success": q.get("success"),
                    "error": self.sanitize(q.get("error")),
                }
            )
        return sanitized_queries

    def log_task(self, task_context: Any) -> bool:
        """Grava uma entrada de auditoria estruturada referente a uma tarefa concluída ou encerrada."""
        if not task_context:
            return False

        try:
            os.makedirs(self.log_dir, exist_ok=True)

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_id": getattr(task_context, "task_id", "unknown"),
                "command": self.sanitize(getattr(task_context, "command", "")),
                "intent": getattr(task_context, "intent", None),
                "target": self.sanitize(getattr(task_context, "target", None)),
                "plan": getattr(task_context, "plan_steps", []),
                "confirmation_status": getattr(
                    task_context, "confirmation_status", "nao_requerida"
                ),
                "execution_mode": getattr(
                    task_context, "execution_mode", "simulado"
                ),
                "execution_result": self.sanitize(
                    getattr(task_context, "execution_result", None)
                ),
                "verification_result": self.sanitize(
                    getattr(task_context, "verification_result", None)
                ),
                "error": self.sanitize(getattr(task_context, "error", None)),
                "task_status": getattr(task_context, "task_status", "desconhecido"),
                "context_queries": self.sanitize_context_queries(
                    getattr(task_context, "context_queries", [])
                ),
            }

            line = json.dumps(record, ensure_ascii=False)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

            return True

        except Exception as err:
            # Resiliência obrigatória: falha de auditoria não deve derrubar a aplicação
            sys.stderr.write(f"[AVISO] Falha ao registrar log de auditoria: {err}\n")
            return False
