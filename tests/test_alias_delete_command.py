"""Testes para o comando conversacional de excluir alias."""

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


class TestDeleteAliasIntent(unittest.TestCase):
    """Testes de reconhecimento de intenção para excluir alias."""

    def setUp(self) -> None:
        self.recognizer = IntentRecognizer()

    def test_comando_therion_exclua_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, exclua um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "excluir alias")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_comando_therion_remova_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, remova um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "excluir alias")

    def test_comando_excluir_um_alias(self) -> None:
        intent = self.recognizer.parse("excluir um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "excluir alias")

    def test_comando_remover_um_alias(self) -> None:
        intent = self.recognizer.parse("remover um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "excluir alias")

    def test_comando_case_insensitive(self) -> None:
        intent = self.recognizer.parse("THERION, EXCLUA UM ALIAS")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "excluir alias")

    def test_comando_abrir_nao_confundido(self) -> None:
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")


class TestDeleteAliasCommand(unittest.TestCase):
    """Testes do comando de excluir alias via Orchestrator (fluxo completo)."""

    def test_inicia_fluxo_pergunta_qual_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        result = orchestrator.process_command("Therion, exclua um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual alias você quer excluir", result.message)

    def test_alias_existente_encontrado_mostra_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"segundo cérebro": "Obsidian"})
        orchestrator.process_command("Therion, exclua um alias")
        result = orchestrator.process_command("segundo cérebro")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Encontrei", result.message)
        self.assertIn("segundo cérebro", result.message)
        self.assertIn("Obsidian", result.message)
        self.assertIn("Deseja realmente excluir", result.message)

    def test_confirmacao_sim_remove_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, exclua um alias")
            orchestrator.process_command("meu alias")
            result = orchestrator.process_command("sim")
            self.assertEqual(result.status, "success")
            self.assertIn("removido com sucesso", result.message)
            mock_save.assert_called_once()
            self.assertNotIn("meu alias", orchestrator.alias_manager.list_aliases())

    def test_confirmacao_nao_cancela_sem_escrever(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, exclua um alias")
            orchestrator.process_command("meu alias")
            result = orchestrator.process_command("não")
            self.assertEqual(result.status, "cancelled")
            self.assertIn("cancelada", result.message)
            mock_save.assert_not_called()
            self.assertIn("meu alias", orchestrator.alias_manager.list_aliases())

    def test_resposta_ambigua_pede_novamente(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, exclua um alias")
        orchestrator.process_command("meu alias")
        result = orchestrator.process_command("talvez")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("não reconhecida", result.message)

    def test_alias_inexistente_nao_remove_nada(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"existente": "Obsidian"})
        orchestrator.process_command("Therion, exclua um alias")
        result = orchestrator.process_command("inexistente")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não encontrado", result.message)
        self.assertIn("existente", orchestrator.alias_manager.list_aliases())

    def test_chave_vazia_rejeitada(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, exclua um alias")
        result = orchestrator.process_command("   ")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não pode ser vazio", result.message)

    def test_operacao_nao_persiste_antes_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, exclua um alias")
            orchestrator.process_command("meu alias")
            # Antes da confirmação, save_config não deve ter sido chamado
            mock_save.assert_not_called()
            self.assertIn("meu alias", orchestrator.alias_manager.list_aliases())

    def test_somente_alias_escolhido_removido(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"alias1": "Obsidian", "alias2": "Obsidian"})
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, exclua um alias")
            orchestrator.process_command("alias1")
            orchestrator.process_command("sim")
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertNotIn("alias1", aliases)
            self.assertIn("alias2", aliases)

    def test_comandos_anteriores_continuam_funcionando(self) -> None:
        """Verifica que comandos de abrir, listar e adicionar ainda funcionam."""
        orchestrator = _make_orchestrator_with_aliases({"obs": "Obsidian"})
        
        # Testar abrir aplicativo
        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        
        # Testar listar aliases
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("obs → Obsidian", result.message)

        # Testar adicionar alias
        result = orchestrator.process_command("Therion, adicione um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual palavra", result.message)


class TestDeleteAliasIntegration(unittest.TestCase):
    """Testes de integração: IntentRecognizer -> Orchestrator -> AliasManager."""

    def test_fluxo_completo_adiciona_exclui_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config"):
            # Adiciona
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("para excluir")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")
            
            # Verifica que foi adicionado
            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertIn("para excluir", result.message)
            
            # Exclui
            orchestrator.process_command("Therion, exclua um alias")
            orchestrator.process_command("para excluir")
            orchestrator.process_command("sim")
            
            # Verifica que foi removido
            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertEqual(result.message, "Nenhum alias cadastrado.")

    def test_fluxo_cancelado_nao_afeta_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, exclua um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("não")
        
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("meu alias", result.message)


if __name__ == "__main__":
    unittest.main()