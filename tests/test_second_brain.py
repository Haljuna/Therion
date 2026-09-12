"""Testes unitários da camada de leitura seletiva do Segundo Cérebro (V0)."""

import os
import tempfile
import unittest

from therion.context.second_brain import ReadResult, SecondBrainReader
from therion.core.orchestrator import Orchestrator


class TestSecondBrainReader(unittest.TestCase):
    """Garante a segurança, contenção e restrição estrita de leitura do Segundo Cérebro."""

    def setUp(self) -> None:
        # Cria um cofre temporário isolado para testes sem tocar em arquivos de produção
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name

        self.ia_dir = os.path.join(self.vault_root, "90 - Sistema da IA")
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        self.pessoal_dir = os.path.join(self.vault_root, "01 - Pessoal")
        self.outro_projeto_dir = os.path.join(self.vault_root, "10 - Projetos", "OutroProjeto")

        os.makedirs(self.ia_dir, exist_ok=True)
        os.makedirs(self.therion_dir, exist_ok=True)
        os.makedirs(self.pessoal_dir, exist_ok=True)
        os.makedirs(self.outro_projeto_dir, exist_ok=True)

        # Arquivos autorizados
        self.nota_ia = os.path.join(self.ia_dir, "Entrada da IA.md")
        with open(self.nota_ia, "w", encoding="utf-8") as f:
            f.write("# Ponto de Entrada")

        self.nota_therion = os.path.join(self.therion_dir, "Estado Atual.md")
        with open(self.nota_therion, "w", encoding="utf-8") as f:
            f.write("# Estado Atual Therion")

        # Arquivos protegidos fora do escopo
        self.nota_pessoal = os.path.join(self.pessoal_dir, "Diario.md")
        with open(self.nota_pessoal, "w", encoding="utf-8") as f:
            f.write("# Confidencial Pessoal")

        self.nota_outro = os.path.join(self.outro_projeto_dir, "Plano.md")
        with open(self.nota_outro, "w", encoding="utf-8") as f:
            f.write("# Outro Projeto")

        # Arquivo não .md dentro da área permitida
        self.arquivo_texto = os.path.join(self.therion_dir, "notas.txt")
        with open(self.arquivo_texto, "w", encoding="utf-8") as f:
            f.write("Apenas texto")

        self.reader = SecondBrainReader(vault_root=self.vault_root)

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def test_1_read_success_in_therion_dir(self) -> None:
        """1. Leitura bem-sucedida de um .md dentro de 10 - Projetos/Therion."""
        res = self.reader.read_note("10 - Projetos/Therion/Estado Atual.md")
        self.assertTrue(res.success)
        self.assertEqual(res.content, "# Estado Atual Therion")
        self.assertIsNone(res.error)

    def test_2_read_success_in_sistema_ia_dir(self) -> None:
        """2. Leitura bem-sucedida de um .md dentro de 90 - Sistema da IA."""
        res = self.reader.read_note("90 - Sistema da IA/Entrada da IA.md")
        self.assertTrue(res.success)
        self.assertEqual(res.content, "# Ponto de Entrada")

    def test_3_block_outside_allowed_roots(self) -> None:
        """3. Bloqueio estrito de arquivo fora das raízes permitidas (ex.: 01 - Pessoal)."""
        res_pessoal = self.reader.read_note("01 - Pessoal/Diario.md")
        self.assertFalse(res_pessoal.success)
        self.assertIn("fora das raízes autorizadas", res_pessoal.error)
        self.assertIsNone(res_pessoal.content)

        res_outro = self.reader.read_note("10 - Projetos/OutroProjeto/Plano.md")
        self.assertFalse(res_outro.success)
        self.assertIn("fora das raízes autorizadas", res_outro.error)

    def test_4_block_path_traversal(self) -> None:
        """4. Bloqueio de '..' para tentar escapar do escopo autorizado."""
        traversal_path = "10 - Projetos/Therion/../../01 - Pessoal/Diario.md"
        res = self.reader.read_note(traversal_path)
        self.assertFalse(res.success)
        self.assertIn("fora das raízes autorizadas", res.error)

    def test_5_block_non_md_extensions(self) -> None:
        """5. Bloqueio de qualquer extensão diferente de .md."""
        res = self.reader.read_note("10 - Projetos/Therion/notas.txt")
        self.assertFalse(res.success)
        self.assertIn("Tipo de arquivo não permitido", res.error)

        res_exe = self.reader.read_note("10 - Projetos/Therion/app.exe")
        self.assertFalse(res_exe.success)
        self.assertIn("Apenas arquivos .md são autorizados", res_exe.error)

    def test_6_nonexistent_file_error(self) -> None:
        """6. Erro claro para arquivo inexistente dentro da raiz permitida."""
        res = self.reader.read_note("10 - Projetos/Therion/Inexistente.md")
        self.assertFalse(res.success)
        self.assertIn("Arquivo não encontrado", res.error)

    def test_7_read_only_preserves_files(self) -> None:
        """7. Nenhuma escrita em disco: verifica integridade dos arquivos lidos."""
        mtime_before = os.path.getmtime(self.nota_therion)
        res = self.reader.read_note("10 - Projetos/Therion/Estado Atual.md")
        self.assertTrue(res.success)
        mtime_after = os.path.getmtime(self.nota_therion)
        self.assertEqual(mtime_before, mtime_after)

    def test_8_no_recursive_vault_scanning(self) -> None:
        """8. Nenhuma busca recursiva pelo vault (resolve diretamente sem varrer diretórios)."""
        # Garante que caminhos com subpastas inexistentes falhem rápido sem buscas amplas
        res = self.reader.read_note("10 - Projetos/Therion/NaoExiste/Subpasta/Nota.md")
        self.assertFalse(res.success)
        self.assertIn("Arquivo não encontrado", res.error)

    def test_9_working_memory_records_context_query(self) -> None:
        """9. Memória de trabalho registra qual contexto foi consultado."""
        orchestrator = Orchestrator(simulate=True)
        orchestrator.second_brain = self.reader

        orchestrator.memory.start_task("Comando com consulta a contexto")
        read_res = orchestrator.read_context("10 - Projetos/Therion/Estado Atual.md")

        self.assertTrue(read_res.success)
        queries = orchestrator.memory.current_task.context_queries
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["path"], "10 - Projetos/Therion/Estado Atual.md")
        self.assertTrue(queries[0]["success"])
        self.assertIsNone(queries[0]["error"])

    def test_real_vault_paths_can_be_read_if_present(self) -> None:
        """Testa o leitor padrão com o arquivo real de Estado Atual."""
        default_reader = SecondBrainReader()
        res = default_reader.read_note("10 - Projetos/Therion/Estado Atual.md")
        self.assertTrue(res.success)
        self.assertIn("# Therion — Estado Atual", res.content)


if __name__ == "__main__":
    unittest.main()
