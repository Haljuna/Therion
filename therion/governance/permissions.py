"""Verificação de permissões e níveis de autonomia da V0."""

from therion.core.intent import Intent


class PermissionManager:
    """Gerenciador de permissões da V0 com allowlist estrita."""

    # Allowlist estrita de ações e alvos da V0
    ALLOWED_ACTIONS = {"abrir aplicativo"}
    ALLOWED_TARGETS = {"Obsidian"}

    def is_allowed(self, intent: Intent) -> bool:
        """Verifica se ação e alvo constam na allowlist estrita da V0."""
        if intent.action not in self.ALLOWED_ACTIONS:
            return False
        if intent.target not in self.ALLOWED_TARGETS:
            return False
        return True

    def requires_confirmation(self, intent: Intent) -> bool:
        """Determina se a ação exige confirmação explícita do usuário (DEC-008)."""
        # Ações com efeito externo no Windows exigem confirmação obrigatória
        return True
