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
        r"^(?:therion[,\s]+)?(?:abra|abrir)\s+(?:o\s+)?([a-zA-Z0-9_\-\.\sàáâãéêíóôõúç]+)\s*$",
        re.IGNORECASE,
    )

    _LIST_ALIASES_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:liste|lista|mostre|exiba|listar|mostrar|exibir)\s+(?:meus?\s+)?(?:aliases?|apelidos?)\s*$",
        re.IGNORECASE,
    )

    _ADD_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:adicione|adicionar|crie|criar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _DELETE_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:exclua|excluir|remova|remover|apague|apagar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _REPLACE_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:substitua|substituir|altere|alterar|troque|trocar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _CONSULT_CONTEXT_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:leia|ler|consulte|consultar)\s+"
        r"(?:no\s+)?(?:segundo\s+cérebro|2º?\s*cérebro)\s+"
        r"(.+)$",
        re.IGNORECASE,
    )

    _SEARCH_CONTEXT_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:procure|procurar|busque|buscar|pesquise|pesquisar)\s+"
        r"(?:no\s+)?(?:segundo\s+cérebro|2º?\s*cérebro)\s+"
        r"(.+)$",
        re.IGNORECASE,
    )

    def parse(self, command: str) -> Optional[Intent]:
        """Extrai ação e alvo de um comando textual simples."""
        cleaned = command.strip()
        
        # Verificar padrão de listagem de aliases primeiro
        list_match = self._LIST_ALIASES_PATTERN.match(cleaned)
        if list_match:
            return Intent(
                action="listar aliases",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de adicionar alias
        add_match = self._ADD_ALIAS_PATTERN.match(cleaned)
        if add_match:
            return Intent(
                action="adicionar alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de excluir alias
        delete_match = self._DELETE_ALIAS_PATTERN.match(cleaned)
        if delete_match:
            return Intent(
                action="excluir alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de substituir alias
        replace_match = self._REPLACE_ALIAS_PATTERN.match(cleaned)
        if replace_match:
            return Intent(
                action="substituir alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de busca no Segundo Cérebro
        search_match = self._SEARCH_CONTEXT_PATTERN.match(cleaned)
        if search_match:
            return Intent(
                action="buscar segundo cérebro",
                target=search_match.group(1).strip(),
                raw_command=command,
                requires_confirmation=False,
            )

        # Verificar padrão de consulta ao Segundo Cérebro
        consult_match = self._CONSULT_CONTEXT_PATTERN.match(cleaned)
        if consult_match:
            return Intent(
                action="consultar segundo cérebro",
                target=consult_match.group(1).strip(),
                raw_command=command,
                requires_confirmation=False,
            )
        
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
