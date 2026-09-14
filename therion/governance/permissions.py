"""Verificação de permissões e níveis de autonomia da V0."""

from therion.core.intent import Intent


class PermissionManager:
    """Gerenciador de permissões da V0 com allowlist estrita."""

    # Allowlist estrita de ações e alvos da V0
    ALLOWED_ACTIONS = {"abrir aplicativo", "listar aliases", "adicionar alias", "excluir alias", "substituir alias"}
    ALLOWED_TARGETS = {"Obsidian"}

    def is_allowed(self, intent: Intent) -> bool:
        """Verifica se ação e alvo constam na allowlist estrita da V0."""
        if intent.action not in self.ALLOWED_ACTIONS:
            return False
        # Para ações sem alvo específico (listar, adicionar, excluir, substituir aliases), não verifica alvo
        if intent.action in ("listar aliases", "adicionar alias", "excluir alias", "substituir alias"):
            return True
        if intent.target not in self.ALLOWED_TARGETS:
            return False
        return True

    def requires_confirmation(self, intent: Intent) -> bool:
        """Determina se a ação exige confirmação explícita do usuário (DEC-008)."""
        # Ações de aliases (listar, adicionar, excluir, substituir) não exigem confirmação no nível de permissão
        # A confirmação do fluxo é gerenciada conversacionalmente
        if intent.action in ("listar aliases", "adicionar alias", "excluir alias", "substituir alias"):
            return False
        # Ações com efeito externo no Windows exigem confirmação obrigatória
        return True
