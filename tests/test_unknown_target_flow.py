"""Testes para o fluxo de alvo desconhecido no Orchestrator."""

import unittest
from unittest.mock import patch

from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator


def _make_orchestrator_with_aliases(aliases=None):
    config = {
        "aliases": aliases or {},
        "ui": {"start_minimized": False},
        "allowed_apps": [],
    }
    with patch("therion.config.alias_manager.load_config", return_value=config):
        return Orchestrator(simulate=True)


class TestUnknownTargetFlowInitiation(unittest.TestCase):
    """Testes de iniciação do fluxo de alvo desconhecido."""

    def test_alvo_desconhecido_inicia_fluxo(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        result = orchestrator.process_command("Therion, abra o segundo cérebro")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Não reconheci", result.message)

    def test_fluxo_verificado_antes_do_reconhecedor(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        self.assertIsNotNone(orchestrator._unknown_target_flow_step)
        result = orchestrator.process_command("Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Deseja salvar", result.message)

    def test_comando_conhecido_nao_inicia_fluxo(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertIsNone(orchestrator._unknown_target_flow_step)


class TestUnknownTargetFlowCommand(unittest.TestCase):
    """Testes do comando do fluxo de alvo desconhecido."""

    def test_pergunta_o_que_significa(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        result = orchestrator.process_command("Therion, abra o segundo cérebro")
        self.assertIn("O que isso significa?", result.message)

    def test_usuario_informa_alvo_autorizado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        result = orchestrator.process_command("Obsidian")
        self.assertIn("→", result.message)
        self.assertIn("Deseja salvar", result.message)

    def test_associacao_mostrada_antes_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        result = orchestrator.process_command("Obsidian")
        self.assertIn("'Segundo cérebro' → 'Obsidian'", result.message)
        self.assertIn("Deseja salvar essa associação como alias?", result.message)

    def test_sim_salva_alias(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, abra o segundo cérebro")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("sim")
            self.assertEqual(result.status, "success")
            self.assertIn("Salvei o alias", result.message)
            self.assertIn("com sucesso", result.message)
            self.assertIn("segundo cérebro", orchestrator.alias_manager.list_aliases())

    def test_nao_cancela_sem_persistir(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, abra o segundo cérebro")
            orchestrator.process_command("Obsidian")
            result = orchestrator.process_command("não")
            self.assertEqual(result.status, "cancelled")
            self.assertIn("cancelada", result.message)
            mock_save.assert_not_called()
            self.assertNotIn("segundo cérebro", orchestrator.alias_manager.list_aliases())

    def test_resposta_ambigua_pede_novamente(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        orchestrator.process_command("Obsidian")
        result = orchestrator.process_command("talvez")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("não reconhecida", result.message)

    def test_alvo_explicado_nao_autorizado_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, abra o segundo cérebro")
            result = orchestrator.process_command("Chrome")
            self.assertEqual(result.status, "forbidden")
            self.assertIn("não é um aplicativo autorizado", result.message)
            mock_save.assert_not_called()

    def test_alvo_vazio_rejeitado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        result = orchestrator.process_command("   ")
        self.assertEqual(result.status, "cancelled")
        self.assertIn("Resposta vazia", result.message)

    def test_nenhuma_persistencia_antes_confirmacao(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, abra o segundo cérebro")
            orchestrator.process_command("Obsidian")
            mock_save.assert_not_called()
            self.assertNotIn("segundo cérebro", orchestrator.alias_manager.list_aliases())

    def test_estado_limpo_apos_sucesso(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, abra o segundo cérebro")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")
            self.assertIsNone(orchestrator._unknown_target_flow_step)
            self.assertIsNone(orchestrator._pending_unknown_original)
            self.assertIsNone(orchestrator._pending_unknown_explained)

    def test_estado_limpo_apos_cancelamento(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        orchestrator.process_command("Obsidian")
        orchestrator.process_command("não")
        self.assertIsNone(orchestrator._unknown_target_flow_step)
        self.assertIsNone(orchestrator._pending_unknown_original)
        self.assertIsNone(orchestrator._pending_unknown_explained)

    def test_estado_limpo_apos_alvo_nao_autorizado(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        orchestrator.process_command("Chrome")
        self.assertIsNone(orchestrator._unknown_target_flow_step)
        self.assertIsNone(orchestrator._pending_unknown_original)
        self.assertIsNone(orchestrator._pending_unknown_explained)

    def test_estado_limpo_apos_resposta_vazia(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        orchestrator.process_command("Therion, abra o segundo cérebro")
        orchestrator.process_command("   ")
        self.assertIsNone(orchestrator._unknown_target_flow_step)
        self.assertIsNone(orchestrator._pending_unknown_original)
        self.assertIsNone(orchestrator._pending_unknown_explained)

    def test_alias_existente_nao_sobrescrito(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"segundo cérebro": "Obsidian"})
        with patch("therion.config.alias_manager.save_config") as mock_save:
            orchestrator.process_command("Therion, abra o segundo cérebro")
            self.assertIsNone(orchestrator._unknown_target_flow_step)
            mock_save.assert_not_called()


class TestUnknownTargetFlowIntegration(unittest.TestCase):
    """Testes de integração do fluxo de alvo desconhecido."""

    def test_fluxo_completo_adiciona_alias_e_lista(self) -> None:
        orchestrator = _make_orchestrator_with_aliases()
        with patch("therion.config.alias_manager.save_config"):
            orchestrator.process_command("Therion, abra o segundo cérebro")
            orchestrator.process_command("Obsidian")
            orchestrator.process_command("sim")
            result = orchestrator.process_command("Therion, liste meus aliases")
            self.assertIn("segundo cérebro", result.message)
            self.assertIn("Obsidian", result.message)

    def test_comandos_anteriores_continuam_funcionando(self) -> None:
        orchestrator = _make_orchestrator_with_aliases({"obs": "Obsidian"})
        result = orchestrator.process_command("Therion, abra o Obsidian")
        self.assertEqual(result.status, "awaiting_confirmation")
        result = orchestrator.process_command("Therion, liste meus aliases")
        self.assertEqual(result.status, "success")
        self.assertIn("obs → Obsidian", result.message)
        result = orchestrator.process_command("Therion, adicione um alias")
        self.assertEqual(result.status, "awaiting_confirmation")
        self.assertIn("Qual palavra", result.message)


if __name__ == "__main__":
    unittest.main()
