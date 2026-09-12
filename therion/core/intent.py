"""Interpretação e representação de intenções da V0."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Intent:
    """Representação estruturada de uma intenção."""

    action: str
    target: str
    raw_command: str
    requires_confirmation: bool = True


class IntentRecognizer:
    """Reconhecedor determinístico de intenções para a V0."""

    _OPEN_APP_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:abra|abrir)\s+(?:o\s+)?([a-zA-Z0-9_\-\.]+)\s*$",
        re.IGNORECASE,
    )

    def parse(self, command: str) -> Optional[Intent]:
        """Extrai ação e alvo de um comando textual simples."""
        cleaned = command.strip()
        match = self._OPEN_APP_PATTERN.match(cleaned)
        if match:
            target_raw = match.group(1)
            # Preserva capitalização amigável (ex: obsidian -> Obsidian)
            target = target_raw.capitalize() if target_raw.islower() else target_raw
            return Intent(
                action="abrir aplicativo",
                target=target,
                raw_command=command,
                requires_confirmation=True,
            )
        return None
