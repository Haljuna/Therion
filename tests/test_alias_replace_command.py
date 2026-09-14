# -*- coding: utf-8 -*-
"""Testes para o comando conversacional de substituir alias."""

import unittest
from unittest.mock import patch

from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator
from therion.config.alias_manager import AliasManager


def _make_orchestrator_with_aliases(aliases=None):
    """Cria Orchestrator com configuração temporária de aliases."""
    config = {
        "aliases": aliases or {},
        "ui": {"start_minimized": False},
        "allowed_apps": [],
    }
    with patch("therion.config.alias_manager.load_config", return_value=config):
        return Orchestrator(simulate=True)


class TestReplaceAliasIntent(unittest.TestCase):
    """Testes de reconhecimento de intenção para substituir alias."""

    def setUp(self) -> None:
        self.recognizer = IntentRecognizer()

    def test_comando_therion_substitua_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, substitua um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_comando_therion_troque_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, troque um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")

    def test_comando_substituir_um_alias(self) -> None:
        intent = self.recognizer.parse("substituir um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")

    def test_comando_trocar_um_alias(self) -> None:
        intent = self.recognizer.parse("trocar um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")

    def test_comando_therion_altere_um_alias(self) -> None:
        intent = self.recognizer.parse("Therion, altere um alias")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")

    def test_comando_case_insensitive(self) -> None:
        intent = self.recognizer.parse("THERION, SUBSTITUA UM ALIAS")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "substituir alias")

    def test_comando_abrir_nao_confundido(self) -> None:
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")


class TestReplaceAliasCommand(unittest.TestCase):
    """Testes do comando de substituir alias via Orchestrator (fluxo completo)."""

    def test_inicia_fluxo_pergunta_qual_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        result = orchestrator.process_command("Therion, substitua um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual alias você quer substituir", result.message)

    def test_alias_existente_encontrado_mostra_alvo_atual(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"segundo cérebro": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        result = orchestrator.process_command("segundo cérebro")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Atualmente", result.message)
        self.assertIn("Obsidian", result.message)
        self.assertIn("novo alvo", result.message)

    def test_novo_alvo_autorizado_pede_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("meu alias")
        result = orchestrator.process_command("Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Confirmar substituição", result.message)

    def test_novo_alvo_nao_autorizado_rejeita_sem_persistir(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            result = orchestrator.process_command("Chrome")
            self.assertEqual(result.status, "forbidden")
            mock_save.assert_not_called()
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertEqual(aliases["meu alias"], "Obsidian")

    def test_confirmacao_sim_substitui_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("sim")
            self.assertEqual(result.status, "success")
            mock_save.assert_called_once()
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertEqual(aliases["meu alias"], "Obsidian")

    def test_confirmacao_nao_cancela_sem_persistir(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Notepad"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("não")
            self.assertEqual(result.status, "cancelled")
            self.assertIn("cancelada", result.message)
            mock_save.assert_not_called()
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertEqual(aliases["meu alias"], "Notepad")

    def test_resposta_ambigua_pede_novamente(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Obsidian")
        result = orchestrator.process_command("talvez")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("não reconhecida", result.message)

    def test_alias_inexistente_cancela_sem_alteracao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"existente": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        result = orchestrator.process_command("inexistente")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não encontrado", result.message)
        aliases = orchestrator.alias_manager.list_aliases()
        self.assertIn("existente", aliases)

    def test_alvo_vazio_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            result = orchestrator.process_command("   ")
            self.assertEqual(result.status, "cancelled")
            self.assertIn("não pode ser vazio", result.message)
            mock_save.assert_not_called()

    def test_alias_vazio_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        result = orchestrator.process_command("   ")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("não pode ser vazio", result.message)

    def test_nenhuma_persistencia_antes_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            mock_save.assert_not_called()
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertEqual(aliases["meu alias"], "Obsidian")

    def test_somente_alias_escolhido_alterado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"alias1": "Notepad", "alias2": "Notepad"})
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("alias1")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")
            aliases = orchestrator.alias_manager.list_aliases()
            self.assertEqual(aliases["alias1"], "Obsidian")
            self.assertEqual(aliases["alias2"], "Notepad")

    def test_estado_limpo_apos_sucesso(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("meu alias")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")
            self.assertIsNone(orchestrator._replace_alias_flow_step)
            self.assertIsNone(orchestrator._pending_replace_alias)
            self.assertIsNone(orchestrator._pending_replace_old_target)
            self.assertIsNone(orchestrator._pending_replace_new_target)

    def test_estado_limpo_apos_cancelamento(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Obsidian")
        orchestrator.process_command("não")
        self.assertIsNone(orchestrator._replace_alias_flow_step)
        self.assertIsNone(orchestrator._pending_replace_alias)
        self.assertIsNone(orchestrator._pending_replace_old_target)
        self.assertIsNone(orchestrator._pending_replace_new_target)

    def test_estado_limpo_apos_erro_alvo_nao_autorizado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Chrome")
        self.assertIsNone(orchestrator._replace_alias_flow_step)
        self.assertIsNone(orchestrator._pending_replace_alias)
        self.assertIsNone(orchestrator._pending_replace_old_target)
        self.assertIsNone(orchestrator._pending_replace_new_target)

    def test_estado_limpo_apos_alias_inexistente(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"existente": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("inexistente")
        self.assertIsNone(orchestrator._replace_alias_flow_step)
        self.assertIsNone(orchestrator._pending_replace_alias)
        self.assertIsNone(orchestrator._pending_replace_old_target)
        self.assertIsNone(orchestrator._pending_replace_new_target)

    def test_comandos_anteriores_continuam_funcionando(self) -> None:
        """Verifica que comandos de abrir, listar e adicionar ainda funcionam."""
        orchestrator = _make_orchestrator_with_aliases({"obs": "Obsidian"})

        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")

        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("obs → Obsidian", result.message)

        result = orchestrator.process_command("Therion, adicione um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual palavra", result.message)


class TestReplaceAliasIntegration(unittest.TestCase):
    """Testes de integração: IntentRecognizer -> Orchestrator -> AliasManager."""

    def test_fluxo_completo_adiciona_substitui_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({})
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, adicione um alias")
            orchestrator.process_command("para substituir")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")

            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertIn("para substituir", result.message)

            orchestrator.process_command("Therion, substitua um alias")
            orchestrator.process_command("para substituir")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")

            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertIn("para substituir", result.message)

    def test_fluxo_cancelado_nao_afeta_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"meu alias": "Obsidian"})
        orchestrator.process_command("Therion, substitua um alias")
        orchestrator.process_command("meu alias")
        orchestrator.process_command("Notepad")
        orchestrator.process_command("não")

        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("meu alias", result.message)
        self.assertIn("Obsidian", result.message)


if __name__ == "__main__":
    unittest.main()
