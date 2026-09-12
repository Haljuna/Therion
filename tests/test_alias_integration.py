"""Testes de integracao: IntentRecognizer -> AliasManager -> PermissionManager."""

import unittest
from unittest.mock import patch

from therion.core.intent import IntentRecognizer, Intent
from therion.config.alias_manager import AliasManager
from therion.governance.permissions import PermissionManager


def _make_alias_manager(aliases):
    config = {"aliases": aliases}
    with patch("therion.config.alias_manager.load_config", return_value=config):
        return AliasManager()


class TestParsing(unittest.TestCase):

    def setUp(self):
        self.recognizer = IntentRecognizer()

    def test_comando_completo_parseia_corretamente(self):
        intent = self.recognizer.parse("Therion, abra o segundo cerebro")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Segundo cerebro")

    def test_comando_sem_prefixo_therion(self):
        intent = self.recognizer.parse("abra o segundo cerebro")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.target, "Segundo cerebro")

    def test_comando_abrir_sem_o(self):
        intent = self.recognizer.parse("Therion, abrir segundo cerebro")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.target, "Segundo cerebro")

    def test_comando_obsidian_parseia_corretamente(self):
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Obsidian")


class TestResolution(unittest.TestCase):

    def setUp(self):
        self.alias_manager = _make_alias_manager({"segundo cerebro": "Obsidian"})

    def test_alias_resolvido_para_obsidian(self):
        resolved = self.alias_manager.resolve("segundo cerebro")
        self.assertEqual(resolved, "Obsidian")

    def test_alias_case_insensitive_resolvido(self):
        resolved = self.alias_manager.resolve("SEGUNDO CEREBRO")
        self.assertEqual(resolved, "Obsidian")

    def test_alias_com_espacos_resolvido(self):
        resolved = self.alias_manager.resolve("  segundo cerebro  ")
        self.assertEqual(resolved, "Obsidian")

    def test_alvo_direto_sem_alias_retorna_si_mesmo(self):
        resolved = self.alias_manager.resolve("Obsidian")
        self.assertEqual(resolved, "Obsidian")


class TestPermission(unittest.TestCase):

    def setUp(self):
        self.permissions = PermissionManager()

    def test_obsidian_resolvido_passa_permissao(self):
        intent = Intent(
            action="abrir aplicativo",
            target="Obsidian",
            raw_command="Therion, abra o segundo cerebro",
        )
        self.assertTrue(self.permissions.is_allowed(intent))

    def test_alvo_nao_autorizado_bloqueado(self):
        intent = Intent(
            action="abrir aplicativo",
            target="Notepad",
            raw_command="Therion, abra o Notepad",
        )
        self.assertFalse(self.permissions.is_allowed(intent))

    def test_alvo_ficticio_bloqueado(self):
        intent = Intent(
            action="abrir aplicativo",
            target="Calculadora",
            raw_command="Therion, abra a Calculadora",
        )
        self.assertFalse(self.permissions.is_allowed(intent))


class TestResolutionThenPermission(unittest.TestCase):

    def setUp(self):
        self.alias_manager = _make_alias_manager({"segundo cerebro": "Obsidian"})
        self.permissions = PermissionManager()
        self.recognizer = IntentRecognizer()

    def test_fluxo_completo_alias_para_permitido(self):
        intent = self.recognizer.parse("Therion, abra o segundo cerebro")
        self.assertIsNotNone(intent)

        resolved_target = self.alias_manager.resolve(intent.target)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
        )
        self.assertTrue(self.permissions.is_allowed(resolved_intent))
        self.assertEqual(resolved_target, "Obsidian")

    def test_fluxo_completo_alias_para_nao_permitido(self):
        alias_manager = _make_alias_manager({"bloco de notas": "Notepad"})
        intent = self.recognizer.parse("Therion, abra o bloco de notas")
        self.assertIsNotNone(intent)

        resolved_target = alias_manager.resolve(intent.target)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
        )
        self.assertFalse(self.permissions.is_allowed(resolved_intent))
        self.assertEqual(resolved_target, "Notepad")


class TestCommandWithoutAlias(unittest.TestCase):

    def setUp(self):
        self.alias_manager = _make_alias_manager({})
        self.permissions = PermissionManager()
        self.recognizer = IntentRecognizer()

    def test_obsidian_direto_passa(self):
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)

        resolved_target = self.alias_manager.resolve(intent.target)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
        )
        self.assertTrue(self.permissions.is_allowed(resolved_intent))
        self.assertEqual(resolved_target, "Obsidian")

    def test_alvo_nao_listado_bloqueado(self):
        intent = self.recognizer.parse("Therion, abra o Chrome")
        self.assertIsNotNone(intent)

        resolved_target = self.alias_manager.resolve(intent.target)
        resolved_intent = Intent(
            action=intent.action,
            target=resolved_target,
            raw_command=intent.raw_command,
        )
        self.assertFalse(self.permissions.is_allowed(resolved_intent))


class TestOrchestratorIntegration(unittest.TestCase):

    def setUp(self):
        self.alias_config = {"segundo cerebro": "Obsidian"}

    @patch("therion.config.alias_manager.save_config")
    @patch("therion.config.alias_manager.load_config")
    def test_orchestrator_resolve_alias_ate_permissao(
        self, mock_load_config, mock_save
    ):
        from therion.core.orchestrator import Orchestrator

        mock_load_config.return_value = {
            "aliases": self.alias_config,
            "ui": {"start_minimized": False},
            "allowed_apps": [],
        }
        orchestrator = Orchestrator(simulate=True)

        result = orchestrator.process_command("Therion, abra o segundo cerebro")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.target, "Segundo cerebro")
        self.assertIsNotNone(result.plan)

    @patch("therion.config.alias_manager.save_config")
    @patch("therion.config.alias_manager.load_config")
    def test_orchestrator_bloqueia_alvo_nao_autorizado(
        self, mock_load_config, mock_save
    ):
        from therion.core.orchestrator import Orchestrator

        mock_load_config.return_value = {
            "aliases": {"notepad": "Notepad"},
            "ui": {"start_minimized": False},
            "allowed_apps": [],
        }
        orchestrator = Orchestrator(simulate=True)

        result = orchestrator.process_command("Therion, abra o notepad")
        self.assertEqual(result.status, "forbidden")

    @patch("therion.config.alias_manager.save_config")
    @patch("therion.config.alias_manager.load_config")
    def test_orchestrator_obsidian_direto_funciona(
        self, mock_load_config, mock_save
    ):
        from therion.core.orchestrator import Orchestrator

        mock_load_config.return_value = {
            "aliases": {},
            "ui": {"start_minimized": False},
            "allowed_apps": [],
        }
        orchestrator = Orchestrator(simulate=True)

        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.target, "Obsidian")

    @patch("therion.config.alias_manager.save_config")
    @patch("therion.config.alias_manager.load_config")
    def test_orchestrator_executa_simulado_com_alias(
        self, mock_load_config, mock_save
    ):
        from therion.core.orchestrator import Orchestrator

        mock_load_config.return_value = {
            "aliases": {"segundo cerebro": "Obsidian"},
            "ui": {"start_minimized": False},
            "allowed_apps": [],
        }
        orchestrator = Orchestrator(simulate=True)

        result = orchestrator.process_command("Therion, abra o segundo cerebro")
        self.assertEqual(result.status, "awaiting_confirmation")

        exec_result = orchestrator.confirm_and_execute(result.plan, confirmed=True)
        self.assertEqual(exec_result.status, "executed_simulated")


if __name__ == "__main__":
    unittest.main()
