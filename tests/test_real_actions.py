"""Testes da lógica de execução e verificação real (com chamadas de SO mockadas)."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from therion.actions.executor import ActionExecutor
from therion.actions.verifier import ActionVerifier
from therion.core.intent import Intent
from therion.core.orchestrator import Orchestrator
from therion.core.planner import Plan


class TestRealActionsMocked(unittest.TestCase):
    """Valida o caminho de execução real sem produzir efeitos no sistema operacional."""

    def setUp(self) -> None:
        self.executor = ActionExecutor()
        self.verifier = ActionVerifier()
        self.obsidian_intent = Intent(
            action="abrir aplicativo",
            target="Obsidian",
            raw_command="Therion, abra o Obsidian",
            requires_confirmation=True,
        )

    @patch("therion.actions.executor.os.path.isfile", return_value=True)
    @patch("therion.actions.executor.subprocess.Popen")
    def test_executor_real_success(self, mock_popen: MagicMock, mock_isfile: MagicMock) -> None:
        """Testa sucesso no envio do comando real via Popen mockado."""
        result = self.executor.execute_real(self.obsidian_intent)
        self.assertTrue(result.success)
        self.assertIn("enviado com sucesso", result.message)
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertFalse(kwargs.get("shell", True))  # Garante shell=False
        self.assertIn("Obsidian.exe", args[0][0])

    @patch("therion.actions.executor.os.path.isfile", return_value=False)
    def test_executor_real_not_found(self, mock_isfile: MagicMock) -> None:
        """Testa falha amigável quando executável não é encontrado."""
        result = self.executor.execute_real(self.obsidian_intent)
        self.assertFalse(result.success)
        self.assertIn("não foi encontrado", result.message)

    def test_executor_blocks_unauthorized_target(self) -> None:
        """Garante que o executor rejeite qualquer alvo fora da allowlist interna."""
        unauthorized_intent = Intent(
            action="abrir aplicativo",
            target="MaliciousApp",
            raw_command="Therion, abra o MaliciousApp",
        )
        result = self.executor.execute_real(unauthorized_intent)
        self.assertFalse(result.success)
        self.assertIn("não está na allowlist", result.message)

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_success(self, mock_run: MagicMock) -> None:
        """Testa verificação bem-sucedida quando tasklist retorna Obsidian.exe."""
        mock_run.return_value = MagicMock(
            stdout="Obsidian.exe   14396 Console   1   97.560 K\n",
            returncode=0,
        )
        result = self.verifier.verify_real(self.obsidian_intent, max_attempts=1)
        self.assertTrue(result.success)
        self.assertIn("verificado e ativo", result.message)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0][:3], ["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"])
        self.assertFalse(kwargs.get("shell", True))

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_failure(self, mock_run: MagicMock) -> None:
        """Testa verificação quando tasklist não encontra o processo."""
        mock_run.return_value = MagicMock(
            stdout="INFORMACOES: nenhum processo encontrado\n",
            returncode=0,
        )
        result = self.verifier.verify_real(self.obsidian_intent, max_attempts=1, interval=0.01)
        self.assertFalse(result.success)
        self.assertIn("não foi localizado", result.message)

    @patch("therion.actions.executor.os.path.isfile", return_value=True)
    @patch("therion.actions.executor.subprocess.Popen")
    @patch("therion.actions.verifier.subprocess.run")
    def test_orchestrator_real_mode_end_to_end(
        self, mock_run: MagicMock, mock_popen: MagicMock, mock_isfile: MagicMock
    ) -> None:
        """Testa orquestrador em modo real (simulate=False) com SO mockado."""
        mock_run.return_value = MagicMock(stdout="Obsidian.exe 1234\n", returncode=0)

        orchestrator = Orchestrator(simulate=False)
        plan = Plan(intent=self.obsidian_intent, steps=["Abrir o Obsidian.", "Verificar."])

        # Execução com confirmação positiva
        result = orchestrator.confirm_and_execute(plan, confirmed=True)
        self.assertEqual(result.status, "success")
        self.assertIn("enviado com sucesso", result.message)
        self.assertIn("verificado e ativo", result.message)

        # Execução com cancelamento
        cancel_result = orchestrator.confirm_and_execute(plan, confirmed=False)
        self.assertEqual(cancel_result.status, "cancelled")
        self.assertIn("cancelada pelo usuário", cancel_result.message)

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_uses_timeout_5(self, mock_run: MagicMock) -> None:
        """Verifica que subprocess.run é chamado com timeout=5."""
        mock_run.return_value = MagicMock(
            stdout="Obsidian.exe   14396 Console   1   97.560 K\n",
            returncode=0,
        )
        self.verifier.verify_real(self.obsidian_intent, max_attempts=1)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("timeout"), 5)

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_timeout_expired_returns_failure(self, mock_run: MagicMock) -> None:
        """TimeoutExpired deve retornar VerificationResult(success=False)."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["tasklist"], timeout=5
        )
        result = self.verifier.verify_real(self.obsidian_intent, max_attempts=1)
        self.assertFalse(result.success)
        self.assertIn("expirou", result.message.lower())

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_timeout_expired_does_not_raise(self, mock_run: MagicMock) -> None:
        """TimeoutExpired NÃO deve escapar para o chamador."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["tasklist"], timeout=5
        )
        try:
            result = self.verifier.verify_real(self.obsidian_intent, max_attempts=2, interval=0.01)
        except subprocess.TimeoutExpired:
            self.fail("TimeoutExpired escapou do ActionVerifier")
        self.assertFalse(result.success)

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_timeout_stops_after_first_failure(self, mock_run: MagicMock) -> None:
        """TimeoutExpired na primeira tentativa deve retornar imediatamente (sem retry)."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["tasklist"], timeout=5
        )
        result = self.verifier.verify_real(self.obsidian_intent, max_attempts=3, interval=0.01)
        self.assertFalse(result.success)
        self.assertEqual(mock_run.call_count, 1)

    @patch("therion.actions.verifier.subprocess.run")
    def test_verifier_real_preserves_shell_false(self, mock_run: MagicMock) -> None:
        """shell=False deve ser preservado mesmo com timeout=5."""
        mock_run.return_value = MagicMock(
            stdout="Obsidian.exe   14396 Console   1   97.560 K\n",
            returncode=0,
        )
        self.verifier.verify_real(self.obsidian_intent, max_attempts=1)
        _, kwargs = mock_run.call_args
        self.assertFalse(kwargs.get("shell", True))


if __name__ == "__main__":
    unittest.main()
