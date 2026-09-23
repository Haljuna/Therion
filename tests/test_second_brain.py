"""Testes unitários da camada de leitura seletiva do Segundo Cérebro (V0)."""

import os
import tempfile
import unittest

from therion.context.second_brain import ReadResult, SearchTrace, SecondBrainReader
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
        self.assertEqual(res.matched_root, self.therion_dir)

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
        self.assertIsNone(res_pessoal.matched_root)

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
        self.assertIsNone(res.matched_root)

    def test_read_error_has_no_matched_root(self) -> None:
        """Uma falha ao abrir a nota não registra uma root como usada."""
        unreadable = os.path.join(self.therion_dir, "Invalido.md")
        with open(unreadable, "wb") as f:
            f.write(b"\x80\x81")

        res = self.reader.read_note(unreadable)

        self.assertFalse(res.success)
        self.assertIsNone(res.matched_root)

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


class TestConsultContextIntent(unittest.TestCase):
    """Testes de reconhecimento de intenção para consulta ao Segundo Cérebro."""

    def setUp(self) -> None:
        from therion.core.intent import IntentRecognizer
        self.recognizer = IntentRecognizer()

    def test_consult_pattern_recognized(self) -> None:
        """Reconhece 'Therion, leia no Segundo Cérebro [caminho]'."""
        intent = self.recognizer.parse("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/Estado Atual.md")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "consultar segundo cérebro")
        self.assertEqual(intent.target, "10 - Projetos/Therion/Estado Atual.md")
        self.assertFalse(intent.requires_confirmation)

    def test_consult_variations(self) -> None:
        """Reconhece variações: ler, consulte, consultar, 2º cérebro."""
        cases = [
            ("ler no Segundo Cérebro 10 - Projetos/Therion/Estado Atual.md", "10 - Projetos/Therion/Estado Atual.md"),
            ("Therion, consulte no Segundo Cérebro 90 - Sistema da IA/Entrada da IA.md", "90 - Sistema da IA/Entrada da IA.md"),
            ("Therion, consultar no segundo cérebro Arquitetura.md", "Arquitetura.md"),
            ("Therion, leia no 2º cérebro 10 - Projetos/Therion/Estado Atual.md", "10 - Projetos/Therion/Estado Atual.md"),
        ]
        for cmd, expected_target in cases:
            with self.subTest(cmd=cmd):
                intent = self.recognizer.parse(cmd)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.action, "consultar segundo cérebro")
                self.assertEqual(intent.target, expected_target)

    def test_consult_case_insensitive(self) -> None:
        """Case insensitive funciona."""
        intent = self.recognizer.parse("THERION, Leia No Segundo Cérebro Estado Atual.md")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "consultar segundo cérebro")

    def test_consult_no_therion_prefix(self) -> None:
        """Comando sem 'Therion,' também é reconhecido."""
        intent = self.recognizer.parse("leia no Segundo Cérebro 10 - Projetos/Therion/Estado Atual.md")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "consultar segundo cérebro")

    def test_open_app_not_confused_with_consult(self) -> None:
        """Comando de abrir aplicativo não é confundido com consulta."""
        intent = self.recognizer.parse("Therion, abra o Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")


class TestConsultContextOrchestrator(unittest.TestCase):
    """Testes de integração: consulta ao Segundo Cérebro via Orchestrator."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        os.makedirs(self.therion_dir, exist_ok=True)
        self.nota_teste = os.path.join(self.therion_dir, "NotaTeste.md")
        with open(self.nota_teste, "w", encoding="utf-8") as f:
            f.write("# Nota de Teste\nConteúdo de teste.")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _make_orchestrator(self) -> "Orchestrator":
        return Orchestrator(simulate=True, vault_root=self.vault_root)

    def test_consult_valid_path_returns_content(self) -> None:
        """Leitura válida retorna conteúdo da nota."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md")
        self.assertEqual(result.status, "success")
        self.assertIn("# Nota de Teste", result.message)
        self.assertIn("Conteúdo de teste.", result.message)

    def test_consult_nonexistent_file_returns_error(self) -> None:
        """Arquivo inexistente retorna erro controlado."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/Inexistente.md")
        self.assertEqual(result.status, "execution_failed")
        self.assertIn("Arquivo não encontrado", result.message)

    def test_consult_outside_scope_returns_permission_error(self) -> None:
        """Caminho fora das raízes retorna erro de permissão."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 01 - Pessoal/Diario.md")
        self.assertEqual(result.status, "execution_failed")
        self.assertIn("fora das raízes autorizadas", result.message)

    def test_consult_non_md_returns_extension_error(self) -> None:
        """Extensão inválida retorna erro de tipo."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/notas.txt")
        self.assertEqual(result.status, "execution_failed")
        self.assertIn("Tipo de arquivo não permitido", result.message)

    def test_consult_records_in_working_memory(self) -> None:
        """Query é registrada na memória de trabalho."""
        orch = self._make_orchestrator()
        orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md")
        queries = orch.memory.current_task.context_queries
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["path"], "10 - Projetos/Therion/NotaTeste.md")
        self.assertTrue(queries[0]["success"])

    def test_consult_handler_called_directly_no_alias_or_plan(self) -> None:
        """Handler de consulta é chamado diretamente: sem resolução de alias, sem plano, sem execução."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md")
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.plan)
        self.assertIn("# Nota de Teste", result.message)


class TestSearchNotes(unittest.TestCase):
    """Testes unitarios do metodo search_notes() do SecondBrainReader."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        self.ia_dir = os.path.join(self.vault_root, "90 - Sistema da IA")
        os.makedirs(self.therion_dir, exist_ok=True)
        os.makedirs(self.ia_dir, exist_ok=True)

        self.nota_aetherion = os.path.join(self.therion_dir, "Aetherion.md")
        with open(self.nota_aetherion, "w", encoding="utf-8") as f:
            f.write("# Aetherion\nModulo Aetherion para processamento de dados.")

        self.nota_config = os.path.join(self.therion_dir, "ConfigAetherion.md")
        with open(self.nota_config, "w", encoding="utf-8") as f:
            f.write("# Config\nArquivo de configuracao geral.")

        self.nota_outra = os.path.join(self.therion_dir, "Arquitetura.md")
        with open(self.nota_outra, "w", encoding="utf-8") as f:
            f.write("# Arquitetura\nEstrutura do sistema.")

        self.nota_txt = os.path.join(self.therion_dir, "notas.txt")
        with open(self.nota_txt, "w", encoding="utf-8") as f:
            f.write("Aetherion em texto plano")

        self.nota_ia = os.path.join(self.ia_dir, "Constituicao.md")
        with open(self.nota_ia, "w", encoding="utf-8") as f:
            f.write("# Constituicao\nReferencia ao Aetherion como componente base.")

        self.reader = SecondBrainReader(vault_root=self.vault_root)

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def test_search_by_content(self) -> None:
        """Busca por termo encontrado no conteudo do arquivo."""
        results = self.reader.search_notes("Aetherion")
        paths = [r.path for r in results]
        self.assertIn("10 - Projetos/Therion/Aetherion.md", paths)

    def test_search_by_filename(self) -> None:
        """Busca por termo encontrado no nome do arquivo."""
        results = self.reader.search_notes("ConfigAetherion")
        paths = [r.path for r in results]
        self.assertIn("10 - Projetos/Therion/ConfigAetherion.md", paths)
        config_result = [r for r in results if "ConfigAetherion" in r.path][0]
        self.assertIn("nome do arquivo", config_result.snippet)

    def test_search_case_insensitive(self) -> None:
        """Busca case-insensitive."""
        results = self.reader.search_notes("aetherion")
        self.assertTrue(len(results) > 0)

    def test_search_max_results_limit(self) -> None:
        """Limita a max_results resultados."""
        for i in range(10):
            path = os.path.join(self.therion_dir, f"Extra{i}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Extra\nConteudo Aetherion {i}")
        results = self.reader.search_notes("Aetherion", max_results=5)
        self.assertLessEqual(len(results), 5)

    def test_trace_records_all_roots_when_search_has_no_results(self) -> None:
        """Busca sem resultado registra todas as varreduras iniciadas."""
        trace = SearchTrace()

        results = self.reader.search_notes("InexistenteXYZ", trace=trace)

        self.assertEqual(results, [])
        self.assertEqual(trace.used_roots, self.reader.allowed_roots)

    def test_trace_stops_before_root_blocked_by_max_results(self) -> None:
        """Limite atingido na primeira root não registra a segunda."""
        trace = SearchTrace()

        results = self.reader.search_notes("Aetherion", max_results=1, trace=trace)

        self.assertEqual(len(results), 1)
        self.assertEqual(trace.used_roots, [self.reader.allowed_roots[0]])

    def test_search_without_trace_keeps_list_return(self) -> None:
        """Chamada legada continua retornando a lista de SearchResult."""
        results = self.reader.search_notes("Aetherion")

        self.assertIsInstance(results, list)
        self.assertTrue(results)
        self.assertEqual(results[0].__class__.__name__, "SearchResult")

    def test_search_no_results(self) -> None:
        """Nenhum resultado retorna lista vazia."""
        results = self.reader.search_notes("InexistenteXYZ")
        self.assertEqual(len(results), 0)

    def test_search_empty_term(self) -> None:
        """Termo vazio retorna lista vazia sem iniciar varredura."""
        results = self.reader.search_notes("")
        self.assertEqual(len(results), 0)
        results = self.reader.search_notes("   ")
        self.assertEqual(len(results), 0)

    def test_search_skips_non_md(self) -> None:
        """Arquivos .txt sao ignorados na busca."""
        results = self.reader.search_notes("Aetherion")
        paths = [r.path for r in results]
        self.assertNotIn("10 - Projetos/Therion/notas.txt", paths)

    def test_search_read_error_skips_file(self) -> None:
        """Erro de leitura ignora arquivo e continua busca."""
        bad_file = os.path.join(self.therion_dir, "Bad.md")
        with open(bad_file, "wb") as f:
            f.write(b"\x80\x81\x82 Aetherion")
        results = self.reader.search_notes("Aetherion")
        self.assertTrue(len(results) > 0)

    def test_search_crosses_allowed_roots(self) -> None:
        """Busca encontra resultados em multiplas raizes autorizadas."""
        results = self.reader.search_notes("Aetherion")
        paths = [r.path for r in results]
        self.assertTrue(any("Therion" in p for p in paths))
        self.assertTrue(any("Sistema da IA" in p for p in paths))


class TestSearchIntent(unittest.TestCase):
    """Testes de reconhecimento de intencao para busca no Segundo Cerebro."""

    def setUp(self) -> None:
        from therion.core.intent import IntentRecognizer
        self.recognizer = IntentRecognizer()

    def test_search_pattern_recognized(self) -> None:
        """Reconhece 'Therion, procure no Segundo Cerebro Aetherion'."""
        intent = self.recognizer.parse("Therion, procure no Segundo Cérebro Aetherion")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "buscar segundo cérebro")
        self.assertEqual(intent.target, "Aetherion")
        self.assertFalse(intent.requires_confirmation)

    def test_search_variations(self) -> None:
        """Reconhece variacoes: procure, busque, pesquise."""
        cases = [
            "Therion, procure no Segundo Cérebro Aetherion",
            "Therion, busque no Segundo Cérebro Aetherion",
            "Therion, pesquise no Segundo Cérebro Aetherion",
            "procure no segundo cérebro Aetherion",
            "busque no 2º cérebro Aetherion",
        ]
        for cmd in cases:
            with self.subTest(cmd=cmd):
                intent = self.recognizer.parse(cmd)
                self.assertIsNotNone(intent)
                self.assertEqual(intent.action, "buscar segundo cérebro")

    def test_search_no_therion_prefix(self) -> None:
        """Comando sem 'Therion,' tambem e reconhecido."""
        intent = self.recognizer.parse("busque no Segundo Cérebro Aetherion")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "buscar segundo cérebro")

    def test_search_not_confused_with_consult(self) -> None:
        """Nao conflita com 'leia no Segundo Cerebro' (consultar)."""
        intent = self.recognizer.parse("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/Estado Atual.md")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "consultar segundo cérebro")


class TestSearchOrchestrator(unittest.TestCase):
    """Testes de integracao: busca no Segundo Cerebro via Orchestrator."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        os.makedirs(self.therion_dir, exist_ok=True)
        self.nota_teste = os.path.join(self.therion_dir, "NotaTeste.md")
        with open(self.nota_teste, "w", encoding="utf-8") as f:
            f.write("# Nota de Teste\nConteudo com Aetherion para busca.")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _make_orchestrator(self) -> "Orchestrator":
        return Orchestrator(simulate=True, vault_root=self.vault_root)

    def test_search_returns_results(self) -> None:
        """Busca valida retorna resultados formatados."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, procure no Segundo Cérebro Aetherion")
        self.assertEqual(result.status, "success")
        self.assertIn("Aetherion", result.message)
        self.assertIn("1 resultado(s)", result.message)

    def test_search_no_results_message(self) -> None:
        """Sem resultados retorna mensagem controlada."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, procure no Segundo Cérebro InexistenteXYZ")
        self.assertEqual(result.status, "success")
        self.assertIn("Nenhum resultado encontrado", result.message)

    def test_search_records_in_memory(self) -> None:
        """Busca e registrada na memoria de trabalho."""
        orch = self._make_orchestrator()
        orch.process_command("Therion, procure no Segundo Cérebro Aetherion")
        self.assertIsNotNone(orch.memory.current_task)

    def test_search_only_md_included(self) -> None:
        """Somente .md aparece nos resultados."""
        txt_file = os.path.join(self.therion_dir, "plano.txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("Aetherion em texto plano")
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, procure no Segundo Cérebro Aetherion")
        self.assertNotIn("plano.txt", result.message)

    def test_search_handler_direct_no_alias(self) -> None:
        """Handler de busca e chamado diretamente: sem alias, sem plano, sem execucao."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, procure no Segundo Cérebro Aetherion")
        self.assertEqual(result.status, "success")
        self.assertIsNone(result.plan)

    def test_consult_still_works(self) -> None:
        """Consulta por caminho continua funcionando."""
        orch = self._make_orchestrator()
        result = orch.process_command("Therion, leia no Segundo Cérebro 10 - Projetos/Therion/NotaTeste.md")
        self.assertEqual(result.status, "success")
        self.assertIn("# Nota de Teste", result.message)


class TestSnippetPresentation(unittest.TestCase):
    """Testes de apresentacao dos snippets da busca textual."""

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.vault_root = self.test_dir.name
        self.therion_dir = os.path.join(self.vault_root, "10 - Projetos", "Therion")
        os.makedirs(self.therion_dir, exist_ok=True)
        self.reader = SecondBrainReader(vault_root=self.vault_root)

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _write_note(self, name: str, content: str) -> None:
        path = os.path.join(self.therion_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_snippet_no_mid_word_start(self) -> None:
        """Nao comeca no meio de palavra quando ha espaco proximo."""
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ Aetherion ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        # O snippet deve comecar em um limite de palavra
        clean = snippet.lstrip("...")
        self.assertTrue(clean[0].isalnum() or clean[0] == " ")

    def test_snippet_no_mid_word_end(self) -> None:
        """Nao termina no meio de palavra quando ha espaco proximo."""
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ Aetherion ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        clean = snippet.rstrip("...")
        self.assertTrue(clean[-1].isalnum() or clean[-1] == " ")

    def test_snippet_ellipsis_start(self) -> None:
        """Adiciona '...' no inicio quando ha corte anterior."""
        prefix = "A" * 150
        text = f"{prefix} Aetherion suficiente"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertTrue(snippet.startswith("..."))

    def test_snippet_ellipsis_end(self) -> None:
        """Adiciona '...' no fim quando ha corte posterior."""
        suffix = "B" * 150
        text = f"Inicio suficiente Aetherion {suffix}"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertTrue(snippet.endswith("..."))

    def test_snippet_newlines_normalized(self) -> None:
        """Quebras de linha sao normalizadas para espacos."""
        text = "Linha um\nLinha dois\nAetherion\nLinha tres"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertNotIn("\n", snippet)

    def test_snippet_spaces_compacted(self) -> None:
        """Multiplos espacos sao compactados."""
        text = "um  dois   tres    Aetherion     cinco"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertNotIn("  ", snippet)

    def test_snippet_preserves_term(self) -> None:
        """Termo encontrado permanece no snippet."""
        text = "Contexto antes Aetherion contexto depois"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertIn("Aetherion", snippet)

    def test_snippet_short_content_no_ellipsis(self) -> None:
        """Conteudo curto nao recebe '...' desnecessario."""
        text = "Aetherion curto"
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        self.assertFalse(snippet.startswith("..."))
        self.assertFalse(snippet.endswith("..."))

    def test_snippet_name_match_unchanged(self) -> None:
        """Match somente no nome continua retornando a indicacao existente."""
        self._write_note("Aetherion.md", "Conteudo sem o termo aqui")
        results = self.reader.search_notes("Aetherion")
        # Encontra o resultado por nome (se o conteudo nao tem o termo)
        name_results = [r for r in results if "nome do arquivo" in r.snippet]
        # Pode ter match no conteudo tambem, entao verificamos se ha algum com indicacao
        # Se o conteudo nao tem "Aetherion", deve ter a indicacao
        content = "Conteudo sem o termo aqui"
        if "aetherion" not in content.lower():
            self.assertTrue(len(name_results) > 0)

    def test_snippet_content_priority_over_name(self) -> None:
        """Se termo esta no nome E no conteudo, retorna snippet do conteudo."""
        self._write_note("Aetherion.md", "Texto com Aetherion relevante aqui")
        results = self.reader.search_notes("Aetherion")
        # Deve retornar snippet do conteudo, nao a indicacao de nome
        content_snippets = [r for r in results if "nome do arquivo" not in r.snippet]
        self.assertTrue(len(content_snippets) > 0)
        self.assertIn("Aetherion", content_snippets[0].snippet)

    def test_snippet_max_length_controlled(self) -> None:
        """Limite de tamanho permanece controlado."""
        text = "A" * 300 + " Aetherion " + "B" * 300
        self._write_note("test.md", text)
        results = self.reader.search_notes("Aetherion")
        snippet = results[0].snippet
        # Remover "..." para medir o conteudo real
        clean = snippet.strip(".")
        self.assertLessEqual(len(clean), 220)


if __name__ == "__main__":
    unittest.main()
