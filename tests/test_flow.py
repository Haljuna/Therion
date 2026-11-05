"""Testes unitários do fluxo lógico simulado da V0."""

import unittest

from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator
from therion.core.planner import Planner
from therion.governance.confirmation import ConfirmationHandler
from therion.governance.permissions import PermissionManager


class TestV0Flow(unittest.TestCase):
    """Testa o ciclo lógico de ponta a ponta em modo simulado."""

    def setUp(self) -> None:
        self.orchestrator = Orchestrator(simulate=True)
        self.intent_recognizer = IntentRecognizer()
        self.planner = Planner()
        self.permission_manager = PermissionManager()
        self.confirmation_handler = ConfirmationHandler()

    def test_intent_recognition(self) -> None:
        """Critérios 1, 2 e 3: reconhecer 'abrir aplicativo' e alvo 'Obsidian'."""
        commands = [
            "Therion, abra o Obsidian",
            "therion abra o obsidian",
            "abra o Obsidian",
            "abrir Obsidian",
            "Therion, abra o obsidian",
        ]
        for cmd in commands:
            with self.subTest(command=cmd):
                intent = self.intent_recognizer.parse(cmd)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.action, "abrir aplicativo")
                self.assertEqual(intent.target, "Obsidian")
                self.assertTrue(intent.requires_confirmation)

    def test_planner_generates_mini_plan(self) -> None:
        """Critério 4: gerar mini-plano adequado para abrir aplicativo."""
        intent = self.intent_recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        plan = self.planner.create_plan(intent)
        self.assertEqual(len(plan.steps), 2)
        self.assertIn("Abrir o Obsidian.", plan.steps[0])
        self.assertIn("Verificar se o processo iniciou.", plan.steps[1])

    def test_permission_manager_requires_confirmation(self) -> None:
        """Critério 5: identificar que a ação exige confirmação."""
        intent = self.intent_recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertTrue(self.permission_manager.is_allowed(intent))
        self.assertTrue(self.permission_manager.requires_confirmation(intent))

    def test_confirmation_handler(self) -> None:
        """Critério 6: aceitar confirmações afirmativas e negativas."""
        self.assertTrue(self.confirmation_handler.evaluate_response("s"))
        self.assertTrue(self.confirmation_handler.evaluate_response("sim"))
        self.assertTrue(self.confirmation_handler.evaluate_response("y"))
        self.assertTrue(self.confirmation_handler.evaluate_response("yes"))

        self.assertFalse(self.confirmation_handler.evaluate_response("n"))
        self.assertFalse(self.confirmation_handler.evaluate_response("nao"))
        self.assertFalse(self.confirmation_handler.evaluate_response("não"))
        self.assertFalse(self.confirmation_handler.evaluate_response("no"))

        self.assertIsNone(self.confirmation_handler.evaluate_response("talvez"))
        self.assertIsNone(self.confirmation_handler.evaluate_response("depois"))

    def test_end_to_end_flow_with_positive_confirmation(self) -> None:
        """Critério 7: ciclo completo com confirmação positiva retorna execução simulada."""
        result = self.orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Posso realizar esta ação após sua confirmação: abrir aplicativo", result.message)
        self.assertIn("Alvo: Obsidian", result.message)
        self.assertIn("Esta ação exige confirmação.", result.message)
        self.assertIn("Continuar? [s/n]", result.message)

        # Confirmar positivamente
        final_result = self.orchestrator.confirm_and_execute(result.plan, confirmed=True)
        self.assertEqual(final_result.status, "executed_simulated")
        self.assertIn("[Simulação] Executado comando para abrir o aplicativo 'Obsidian'", final_result.message)
        self.assertIn("[Simulação] Processo do 'Obsidian' verificado como ativo", final_result.message)

    def test_end_to_end_flow_with_negative_confirmation(self) -> None:
        """Critério 8: ciclo completo com cancelamento."""
        result = self.orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")

        # Confirmar negativamente
        final_result = self.orchestrator.confirm_and_execute(result.plan, confirmed=False)
        self.assertEqual(final_result.status, "cancelled")
        self.assertIn("Operação cancelada pelo usuário.", final_result.message)

    def test_unknown_command(self) -> None:
        """Comando desconhecido é tratado sem exceção."""
        result = self.orchestrator.process_command("Therion, toque uma música")
        self.assertEqual(result.status, "unknown_intent")
        self.assertIn("Não consegui identificar a intenção", result.message)


if __name__ == "__main__":
    unittest.main()
