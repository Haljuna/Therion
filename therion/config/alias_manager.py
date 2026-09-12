"""Gerenciamento de aliases da V1 — CRUD seguro e resolução."""

from dataclasses import dataclass
from typing import Any
from therion.config import load_config, save_config


@dataclass
class AliasResult:
    """Resultado de operação de alias."""
    success: bool
    message: str
    data: Any = None


class AliasManager:
    """Gerencia aliases: resolução, listagem, adição, remoção, substituição.

    Carrega aliases na inicialização (sem hot-reload).
    Operações destrutivas exigem confirm=True como proteção interna da API.
    A confirmação real do usuário é responsabilidade da camada conversacional.
    """

    def __init__(self) -> None:
        config = load_config()
        raw_aliases = config.get("aliases", {})
        self._aliases: dict[str, str] = {}

        if isinstance(raw_aliases, dict):
            for key, value in raw_aliases.items():
                if isinstance(key, str) and isinstance(value, str):
                    normalized_key = key.strip().lower()
                    normalized_value = value.strip()
                    if normalized_key and normalized_value:
                        self._aliases[normalized_key] = normalized_value

    def _save(self) -> None:
        """Persiste aliases atuais no config (usa save_config atômico)."""
        config = load_config()
        config["aliases"] = self._aliases.copy()
        save_config(config)

    def resolve(self, target: str) -> str:
        """Resolve alias para alvo canônico; retorna original se não for alias."""
        if not isinstance(target, str):
            return target
        normalized = target.strip().lower()
        resolved = self._aliases.get(normalized, None)
        if resolved is None:
            return target
        # Mantém capitalização amigável (compatível com IntentRecognizer)
        if isinstance(resolved, str) and resolved.islower():
            return resolved.capitalize()
        return resolved

    def list_aliases(self) -> dict[str, str]:
        """Retorna cópia dos aliases atuais (somente leitura)."""
        return self._aliases.copy()

    def add_alias(self, key: str, target: str) -> AliasResult:
        """Adiciona alias se válido e não existente."""
        if not isinstance(key, str) or not isinstance(target, str):
            return AliasResult(False, "Chave e alvo devem ser strings")
        normalized_key = key.strip().lower()
        normalized_target = target.strip()
        if not normalized_key:
            return AliasResult(False, "Chave não pode ser vazia")
        if not normalized_target:
            return AliasResult(False, "Alvo não pode ser vazio")
        if normalized_key in self._aliases:
            return AliasResult(
                False,
                f"Alias '{normalized_key}' já existe. Use replace_alias com confirm=True para substituir.",
                {"existing": self._aliases[normalized_key]}
            )
        self._aliases[normalized_key] = normalized_target
        self._save()
        return AliasResult(True, f"Alias '{normalized_key}' -> '{normalized_target}' adicionado", {"key": normalized_key, "target": normalized_target})

    def remove_alias(self, key: str, confirm: bool = False) -> AliasResult:
        """Remove alias se existir. Exige confirm=True como proteção interna."""
        if not isinstance(key, str):
            return AliasResult(False, "Chave deve ser string")
        normalized_key = key.strip().lower()
        if not normalized_key:
            return AliasResult(False, "Chave não pode ser vazia")
        if normalized_key not in self._aliases:
            return AliasResult(False, f"Alias '{normalized_key}' não encontrado", {"key": normalized_key})
        if not confirm:
            return AliasResult(
                False,
                f"Alias '{normalized_key}' existe. Remoção requer confirm=True (proteção interna).",
                {"existing": self._aliases[normalized_key]}
            )
        removed = self._aliases.pop(normalized_key)
        self._save()
        return AliasResult(True, f"Alias '{normalized_key}' removido", {"removed": removed})

    def replace_alias(self, key: str, new_target: str, confirm: bool = False) -> AliasResult:
        """Substitui alias existente. Exige confirm=True como proteção interna."""
        if not isinstance(key, str) or not isinstance(new_target, str):
            return AliasResult(False, "Chave e novo alvo devem ser strings")
        normalized_key = key.strip().lower()
        normalized_target = new_target.strip()
        if not normalized_key:
            return AliasResult(False, "Chave não pode ser vazia")
        if not normalized_target:
            return AliasResult(False, "Novo alvo não pode ser vazio")
        if normalized_key not in self._aliases:
            return AliasResult(False, f"Alias '{normalized_key}' não encontrado para substituição")
        if not confirm:
            return AliasResult(
                False,
                f"Alias '{normalized_key}' existe. Substituição requer confirm=True (proteção interna).",
                {"existing": self._aliases[normalized_key]}
            )
        old = self._aliases[normalized_key]
        self._aliases[normalized_key] = normalized_target
        self._save()
        return AliasResult(True, f"Alias '{normalized_key}' atualizado: '{old}' -> '{normalized_target}'", {"key": normalized_key, "old": old, "new": normalized_target})