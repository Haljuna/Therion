"""Testes para o comando conversacional de adicionar alias."""

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


class TestAddAliasIntent(unittest.TestCase):
    """Testes de reconhecimento de intenção para adicionar alias."""

    def setUp(self) -> None:
        self.recognizer = IntentRecognizer()

    def test_comando_therion_adicione_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, adicione um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "adicionar alias")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_comando_adicionar_um_alias(self) -> None:
        intent = self.recognizer.parse("adicionar um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "adicionar alias")

    def test_comando_therion_crie_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, crie um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "adicionar alias")

    def test_comando_case_insensitive(self) -> None:
        intent = self.recognizer.parse("THERION, ADICIONE UM ALIAS")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "adicionar alias")

    def test_comando_abrir_nao_confundido(self) -> None:
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")


class TestAddAliasCommand(unittest.TestCase):
    """Testes do comando de adicionar alias via Orchestrator (fluxo completo)."""

    def test_inicia_fluxo_pergunta_palavra_chave(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        result = orchestrator.process_command("Therion, adicione um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual palavra ou expressão você quer usar como alias", result.message)

    def test_recebe_palavra_chave_pergunta_alvo(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        result = orchestrator.process_command("meu alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Para qual aplicativo ou alvo conhecido", result.message)

    def test_recebe_alvo_valido_pede_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        orchestrator.process_command("meu alias")
        result = orchestrator.process_command("Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Confirmar criação do alias", result.message)
        self.assertIn("'meu alias' → 'Obsidian'", result.message)
        self.assertIn("sim", result.message.lower())
        self.assertIn("não", result.message.lower())

    def test_confirmacao_sim_persiste_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("sim")
            self.assertEqual(result.status, "success")
            self.assertIn("Adicionei o alias com sucesso", result.message)
            mock_save.assert_called_once()
            # Verifica que o alias foi salvo
            self.assertIn("meu alias", orchestrator.alias_manager.list_aliases())
            self.assertEqual(orchestrator.alias_manager.list_aliases()["meu alias"], "Obsidian")

    def test_confirmacao_nao_cancela_sem_escrever(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("não")
            self.assertEqual(result.status, "cancelled")
            self.assertIn("cancelada", result.message)
            mock_save.assert_not_called()
            self.assertNotIn("meu alias", orchestrator.alias_manager.list_aliases())

    def test_alias_existente_nao_sobrescrito(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"existente": "Obsidian"})
        orchestrator.process_command("Therion, adicione um alias")
        result = orchestrator.process_command("existente")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("já existe", result.message)

    def test_chave_vazia_rejeitada(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        result = orchestrator.process_command("   ")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não pode ser vazio", result.message)

    def test_alvo_vazio_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        orchestrator.process_command("meu alias")
        result = orchestrator.process_command("   ")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não pode ser vazio", result.message)

    def test_alvo_nao_autorizado_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        orchestrator.process_command("meu alias")
        result = orchestrator.process_command("Notepad")
        self.assertEqual(result.status, "forbidden")
        self.assertIn("não é um aplicativo autorizado", result.message)

    def test_operacao_nao_persiste_antes_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            # Antes da confirmação, save_config não deve ter sido chamado
            mock_save.assert_not_called()
            self.assertNotIn("meu alias", orchestrator.alias_manager.list_aliases())

    def test_resposta_ambigua_pede_novamente(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Obsidian")
        result = orchestrator.process_command("talvez")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("não reconhecida", result.message)

    def test_comandos_anteriores_continuam_funcionando(self) -> None:
        """Verifica que comandos de abrir aplicativo e listar aliases ainda funcionam."""
        orchestrator = _make_orchestrator_with_aliases({"obs": "Obsidian"})
        
        # Testar abrir aplicativo
        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        
        # Testar listar aliases
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("obs → Obsidian", result.message)


class TestAddAliasIntegration(unittest.TestCase):
    """Testes de integração: IntentRecognizer -> Orchestrator -> AliasManager."""

    def test_fluxo_completo_adiciona_e_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config"):
            # Adiciona
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("segundo cérebro")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("sim")
            self.assertEqual(result.status, "success")
            
            # Lista
            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertEqual(result.status, "success")
            self.assertIn("segundo cérebro", result.message)
            self.assertIn("Obsidian", result.message)

    def test_fluxo_cancelado_nao_afeta_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        orchestrator.process_command("Therion, adicione um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Obsidian")
        orchestrator.process_command("não")
        
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("Nenhum alias cadastrado.", result.message)


if __name__ == "__main__":
    unittest.main()
