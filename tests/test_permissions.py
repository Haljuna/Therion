"""Testes de governança e restrição estrita de alvos na V0."""

import unittest

from therion.core.intent import Intent, IntentRecognizer
from therion.core.orchestrator import Orchestrator
from therion.governance.permissions import PermissionManager


class TestPermissions(unittest.TestCase):
    """Garante que a allowlist seja estritamente respeitada."""

    def setUp(self) -> None:
        self.permission_manager = PermissionManager()
        self.orchestrator = Orchestrator(simulate=True)
        self.intent_recognizer = IntentRecognizer()

    def test_obsidian_is_allowed(self) -> None:
        """Obsidian deve ser o único alvo permitido na V0."""
        intent = Intent(action="abrir aplicativo", target="Obsidian", raw_command="abra o Obsidian")
        self.assertTrue(self.permission_manager.is_allowed(intent))

    def test_unauthorized_targets_are_blocked(self) -> None:
        """Qualquer aplicativo fora da allowlist deve ser bloqueado."""
        forbidden_targets = ["Chrome", "Notepad", "BlocoDeNotas", "Calc", "Cmd", "Powershell", "Firefox", "Spotify"]
        for target in forbidden_targets:
            with self.subTest(target=target):
                intent = Intent(action="abrir aplicativo", target=target, raw_command=f"abra o {target}")
                self.assertFalse(self.permission_manager.is_allowed(intent))

    def test_orchestrator_blocks_unauthorized_commands(self) -> None:
        """O orquestrador inicia fluxo de esclarecimento para alvos não autorizados."""
        result = self.orchestrator.process_command("Therion, abra o Chrome")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Não reconheci", result.message)
        self.assertIsNone(result.plan)


if __name__ == "__main__":
    unittest.main()
