"""Testes de importação e integridade estrutural da V0."""

import unittest


class TestStructure(unittest.TestCase):
    """Valida se todos os módulos essenciais da arquitetura V0 podem ser importados."""

    def test_package_import(self) -> None:
        import therion
        self.assertTrue(hasattr(therion, "__version__"))

    def test_core_imports(self) -> None:
        from therion.core.orchestrator import Orchestrator
        from therion.core.intent import Intent
        from therion.core.planner import Planner
        self.assertIsNotNone(Orchestrator)
        self.assertIsNotNone(Intent)
        self.assertIsNotNone(Planner)

    def test_governance_imports(self) -> None:
        from therion.governance.permissions import PermissionManager
        from therion.governance.confirmation import ConfirmationHandler
        self.assertIsNotNone(PermissionManager)
        self.assertIsNotNone(ConfirmationHandler)

    def test_actions_imports(self) -> None:
        from therion.actions.executor import ActionExecutor
        from therion.actions.verifier import ActionVerifier
        self.assertIsNotNone(ActionExecutor)
        self.assertIsNotNone(ActionVerifier)

    def test_memory_imports(self) -> None:
        from therion.memory.working_memory import WorkingMemory
        self.assertIsNotNone(WorkingMemory)

    def test_interface_imports(self) -> None:
        from therion.interface.cli import main
        self.assertTrue(callable(main))


if __name__ == "__main__":
    unittest.main()
