"""Testes para o comando conversacional de listagem de aliases."""

import unittest
from unittest.mock import patch

from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator
from therion.config.alias_manager import AliasManager


def _make_orchestrator_with_aliases(aliases: dict[str, str] | None = None) -> Orchestrator:
    """Cria Orchestrator com configuração temporária de aliases."""
    config = {
        "aliases": aliases or {},
        "ui": {"start_minimized": False},
        "allowed_apps": [],
    }
    with patch("therion.config.alias_manager.load_config", return_value=config):
        return Orchestrator(simulate=True)


class TestListAliasesIntent(unittest.TestCase):
    """Testes de reconhecimento de intenção para listagem de aliases."""

    def setUp(self) -> None:
        self.recognizer = IntentRecognizer()

    def test_comando_therion_liste_meus_aliases(self) -> None:
        intent = self.recognizer.parse("Therion, liste meus aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_comando_lista_meus_aliases(self) -> None:
        intent = self.recognizer.parse("lista meus aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_mostre_meus_aliases(self) -> None:
        intent = self.recognizer.parse("mostre meus aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_exiba_aliases(self) -> None:
        intent = self.recognizer.parse("exiba aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_listar_aliases(self) -> None:
        intent = self.recognizer.parse("listar aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_com_apelidos(self) -> None:
        intent = self.recognizer.parse("Therion, liste meus apelidos")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_case_insensitive(self) -> None:
        intent = self.recognizer.parse("THERION, LISTE MEUS ALIASES")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")

    def test_comando_abrir_nao_confundido(self) -> None:
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")


class TestListAliasesCommand(unittest.TestCase):
    """Testes do comando de listagem de aliases via Orchestrator."""

    def test_lista_com_um_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"obsidian": "Obsidian"})
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("Aliases cadastrados:", result.message)
        self.assertIn("- obsidian → Obsidian", result.message)

    def test_lista_com_multiplos_aliases(self) -> None:
        aliases = {"segundo cérebro": "Obsidian", "navegador": "Chrome"}
        orchestrator = _make_orchestrator_with_aliases(aliases)
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("Aliases cadastrados:", result.message)
        self.assertIn("- segundo cérebro → Obsidian", result.message)
        self.assertIn("- navegador → Chrome", result.message)

    def test_lista_vazia(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Nenhum alias cadastrado.")

    def test_operacao_somente_leitura(self) -> None:
        """Verifica que o comando não altera o config."""
        aliases = {"obs": "Obsidian"}
        config = {
            "aliases": aliases.copy(),
            "ui": {"start_minimized": False},
            "allowed_apps": [],
        }
        with patch("therion.config.alias_manager.load_config", return_value=config) as mock_load:
            with patch("therion.config.alias_manager.save_config") as mock_save:
                orchestrator = Orchestrator(simulate=True)
                orchestrator.process_command("Therion, liste meus aliases")
                mock_save.assert_not_called()

    def test_comandos_anteriores_continuam_funcionando(self) -> None:
        """Verifica que comandos de abrir aplicativo ainda funcionam."""
        orchestrator = _make_orchestrator_with_aliases({"obsidian": "Obsidian"})
        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIsNotNone(result.intent)
        self.assertEqual(result.intent.action, "abrir aplicativo")
        self.assertEqual(result.intent.target, "Obsidian")


class TestListAliasesIntegration(unittest.TestCase):
    """Testes de integração: IntentRecognizer -> Orchestrator -> AliasManager."""

    def test_fluxo_completo_com_alias(self) -> None:
        aliases = {"segundo cérebro": "Obsidian"}
        orchestrator = _make_orchestrator_with_aliases(aliases)
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("segundo cérebro", result.message)
        self.assertIn("Obsidian", result.message)

    def test_fluxo_completo_sem_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "Nenhum alias cadastrado.")

    def test_intencao_reconhecida_corretamente(self) -> None:
        recognizer = IntentRecognizer()
        intent = recognizer.parse("Therion, liste meus aliases")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "listar aliases")
        self.assertFalse(intent.requires_confirmation)


if __name__ == "__main__":
    unittest.main()