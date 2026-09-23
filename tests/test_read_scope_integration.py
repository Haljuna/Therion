"""Testes de integração do ReadScope com o fluxo real do Orchestrator (DEC-033)."""

import os
import tempfile
import unittest

from therion.core.orchestrator import Orchestrator


class TestReadScopeIntegration(unittest.TestCase):
    """Integração do prefixo `raízes:` com leitura e busca via process_command."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        self.ia_dir = os.path.join(self.vault_root, "90 - Sistema da IA")
        self.pessoal_dir = os.path.join(self.vault_root, "01 - Pessoal")
        os.makedirs(self.therion_dir, exist_ok=True)
        os.makedirs(self.ia_dir, exist_ok=True)
        os.makedirs(self.pessoal_dir, exist_ok=True)
        with open(
            os.path.join(self.therion_dir, "NotaTeste.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Nota de Teste\nConteúdo de teste Therion.")
        with open(
            os.path.join(self.ia_dir, "NotasIA.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Notas IA\nConteúdo Aetherion na área da IA.")
        with open(
            os.path.join(self.pessoal_dir, "Diario.md"), "w", encoding="utf-8"
        ) as f:
            f.write("# Diário\nAnotações pessoais.")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _make_orchestrator(self) -> Orchestrator:
        return Orchestrator(simulate=True, vault_root=self.vault_root)

    def test_sem_prefixo_leitura_e_busca_comportamento_atual(self) -> None:
        orch = self._make_orchestrator()
        result_leia = orch.process_command(
            "Therion, leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertEqual(result_leia.status, "success")
        self.assertIn("# Nota de Teste", result_leia.message)
        result_ia = orch.process_command(
            "Therion, leia no Segundo Cérebro 90 - Sistema da IA/NotasIA.md"
        )
        self.assertEqual(result_ia.status, "success")
        self.assertIn("# Notas IA", result_ia.message)
        result_busca = orch.process_command(
            "Therion, procure no Segundo Cérebro Aetherion"
        )
        self.assertEqual(result_busca.status, "success")
        self.assertIn("1 resultado(s)", result_busca.message)
        self.assertNotIn("Raízes rejeitadas", result_leia.message)
        self.assertNotIn("invalid_scope", result_leia.status)

    def test_prefixo_root_valida_restringe_sem_ampliar(self) -> None:
        orch = self._make_orchestrator()
        dentro = orch.process_command(
            "raízes: 10 - Projetos/Therion :: Therion, leia no Segundo Cérebro "
            "10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertEqual(dentro.status, "success")
        self.assertIn("# Nota de Teste", dentro.message)
        fora = orch.process_command(
            "raízes: 10 - Projetos/Therion :: Therion, leia no Segundo Cérebro "
            "90 - Sistema da IA/NotasIA.md"
        )
        self.assertEqual(fora.status, "execution_failed")
        self.assertIn("fora das raízes autorizadas", fora.message)

    def test_prefixo_vazio_explicito_nega_sem_malformar(self) -> None:
        orch = self._make_orchestrator()
        result = orch.process_command(
            "raízes:  :: Therion, leia no Segundo Cérebro "
            "10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertEqual(result.status, "execution_failed")
        self.assertNotEqual(result.status, "invalid_scope")
        self.assertIn("fora das raízes autorizadas", result.message)
        self.assertNotIn("invalid_scope", result.status)
        self.assertNotIn("Raízes rejeitadas:", result.message)

    def test_declaracao_invalida_segmento_dotdot_retorna_invalid_scope(self) -> None:
        orch = self._make_orchestrator()
        result = orch.process_command(
            "raízes: ../fora :: Therion, leia no Segundo Cérebro "
            "10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertEqual(result.status, "invalid_scope")
        self.assertIn("Declaração de raízes inválida", result.message)
        self.assertIn("segmento '..'", result.message)
        self.assertNotIn("# Nota de Teste", result.message)
        self.assertNotIn("Raízes rejeitadas:", result.message)

    def test_root_fora_do_teto_rejeitada_nao_fatal(self) -> None:
        orch = self._make_orchestrator()
        mistura = orch.process_command(
            "raízes: 10 - Projetos/Therion, 01 - Pessoal :: Therion, "
            "leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertNotEqual(mistura.status, "invalid_scope")
        self.assertEqual(mistura.status, "success")
        self.assertIn("# Nota de Teste", mistura.message)
        self.assertIn("Raízes rejeitadas:", mistura.message)
        self.assertIn("fora do teto permitido", mistura.message)
        self.assertIn("01 - Pessoal", mistura.message)
        acesso_rejeitada = orch.process_command(
            "raízes: 10 - Projetos/Therion, 01 - Pessoal :: Therion, "
            "leia no Segundo Cérebro 01 - Pessoal/Diario.md"
        )
        self.assertNotEqual(acesso_rejeitada.status, "invalid_scope")
        self.assertEqual(acesso_rejeitada.status, "execution_failed")
        self.assertIn("fora das raízes autorizadas", acesso_rejeitada.message)
        self.assertNotIn("# Diário", acesso_rejeitada.message)

    def test_scope_e_nota_nao_vazam_para_o_proximo_turno(self) -> None:
        orch = self._make_orchestrator()
        turno1 = orch.process_command(
            "raízes: 10 - Projetos/Therion, 01 - Pessoal :: Therion, "
            "leia no Segundo Cérebro 90 - Sistema da IA/NotasIA.md"
        )
        self.assertEqual(turno1.status, "execution_failed")
        self.assertNotIn("# Notas IA", turno1.message)
        self.assertIn("Raízes rejeitadas:", turno1.message)
        turno2 = orch.process_command(
            "Therion, leia no Segundo Cérebro 90 - Sistema da IA/NotasIA.md"
        )
        self.assertEqual(turno2.status, "success")
        self.assertIn("# Notas IA", turno2.message)
        self.assertNotIn("Raízes rejeitadas:", turno2.message)

    def test_sintaxe_malformada_retorna_invalid_scope(self) -> None:
        orch = self._make_orchestrator()
        result = orch.process_command(
            "raízes: a,,b :: Therion, leia no Segundo Cérebro "
            "10 - Projetos/Therion/NotaTeste.md"
        )
        self.assertEqual(result.status, "invalid_scope")
        self.assertIn("Declaração de raízes inválida", result.message)
        self.assertNotIn("# Nota de Teste", result.message)
        self.assertNotIn("Raízes rejeitadas:", result.message)


if __name__ == "__main__":
    unittest.main()
