"""Testes unitários do sistema de logs e auditoria técnica da V0."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from therion.core.orchestrator import Orchestrator
from therion.logging.audit import AuditLogger
from therion.memory.working_memory import TaskContext


class TestAuditLogger(unittest.TestCase):
    """Testa a geração, sanitização e resiliência dos logs de auditoria técnica."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = self.temp_dir.name
        self.logger = AuditLogger(log_dir=self.log_dir, log_file="test_audit.jsonl")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _read_logged_records(self, log_path: str = "") -> list:
        path = log_path or self.logger.log_path
        if not os.path.exists(path):
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def test_1_valid_record_creation(self) -> None:
        """1. Criação de registro de auditoria válido em arquivo .jsonl."""
        task = TaskContext(command="Therion, abra o Obsidian", task_status="concluido")
        success = self.logger.log_task(task)
        self.assertTrue(success)
        records = self._read_logged_records()
        self.assertEqual(len(records), 1)

    def test_2_and_3_timestamp_and_task_id_present(self) -> None:
        """2 e 3. Data/hora e identificador de tarefa presentes e válidos."""
        task = TaskContext(task_id="task-1234", command="Comando de teste")
        self.logger.log_task(task)
        records = self._read_logged_records()
        self.assertEqual(records[0]["task_id"], "task-1234")
        self.assertIn("T", records[0]["timestamp"])  # ISO 8601 format

    def test_4_command_intent_target_recorded(self) -> None:
        """4. Comando, intenção e alvo registrados com precisão."""
        task = TaskContext(
            command="Therion, abra o Obsidian",
            intent="abrir aplicativo",
            target="Obsidian",
            plan_steps=["1. Abrir", "2. Verificar"],
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["command"], "Therion, abra o Obsidian")
        self.assertEqual(record["intent"], "abrir aplicativo")
        self.assertEqual(record["target"], "Obsidian")
        self.assertEqual(record["plan"], ["1. Abrir", "2. Verificar"])

    def test_5_confirmation_recorded(self) -> None:
        """5. Status de confirmação registrado."""
        task = TaskContext(confirmation_status="confirmado")
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["confirmation_status"], "confirmado")

    def test_6_execution_and_verification_recorded(self) -> None:
        """6. Resultados de execução e verificação registrados."""
        task = TaskContext(
            execution_result="[Simulação] Aberto com sucesso.",
            verification_result="[Simulação] Processo ativo.",
            task_status="concluido",
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["execution_result"], "[Simulação] Aberto com sucesso.")
        self.assertEqual(record["verification_result"], "[Simulação] Processo ativo.")
        self.assertEqual(record["task_status"], "concluido")

    def test_7_error_recorded_when_present(self) -> None:
        """7. Erro registrado quando existir."""
        task = TaskContext(error="Falha de permissão no Windows", task_status="falhou")
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["error"], "Falha de permissão no Windows")
        self.assertEqual(record["task_status"], "falhou")

    def test_8_cancellation_recorded_correctly(self) -> None:
        """8. Cancelamento registrado corretamente."""
        orchestrator = Orchestrator(simulate=True, log_dir=self.log_dir)
        res = orchestrator.process_command("Therion, abra o Obsidian")
        orchestrator.confirm_and_execute(res.plan, confirmed=False)

        orch_log = os.path.join(self.log_dir, "audit.jsonl")
        records = self._read_logged_records(orch_log)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["confirmation_status"], "cancelado")
        self.assertEqual(records[0]["task_status"], "cancelado")

    def test_9_and_10_context_queries_path_only_no_full_content(self) -> None:
        """9 e 10. Consultas registradas apenas por caminho/status, sem conteúdo completo."""
        task = TaskContext(
            command="Consulta com contexto",
            context_queries=[
                {
                    "path": "10 - Projetos/Therion/Estado Atual.md",
                    "success": True,
                    "content": "CONTEUDO_SECRETO_QUE_NAO_DEVE_APARECER",
                }
            ],
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(len(record["context_queries"]), 1)
        query_entry = record["context_queries"][0]
        self.assertEqual(query_entry["path"], "10 - Projetos/Therion/Estado Atual.md")
        self.assertTrue(query_entry["success"])
        # Garante que chave de conteúdo não existe no registro
        self.assertNotIn("content", query_entry)
        self.assertNotIn("CONTEUDO_SECRETO", json.dumps(record))

    def test_11_secrets_sanitized_in_logs(self) -> None:
        """11. Segredos conhecidos e chaves são mascarados nos logs."""
        task = TaskContext(
            command="abrir com token: secret_token_12345",
            error="Erro com password = super_secret_pass",
        )
        self.logger.log_task(task)
        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            raw_log = f.read()
        self.assertNotIn("secret_token_12345", raw_log)
        self.assertNotIn("super_secret_pass", raw_log)
        self.assertIn("[REDACTED]", raw_log)

    def test_12_logging_failure_does_not_break_main_flow(self) -> None:
        """12. Falha de escrita do log não quebra o fluxo principal."""
        orchestrator = Orchestrator(simulate=True, log_dir=self.log_dir)

        # Simula erro de I/O na escrita do log
        with patch.object(orchestrator.audit_logger, "log_task", side_effect=Exception("Disk full")):
            res = orchestrator.process_command("Therion, abra o Obsidian")
            final_res = orchestrator.confirm_and_execute(res.plan, confirmed=True)

            # O fluxo principal foi concluído com sucesso apesar da falha no log
            self.assertEqual(final_res.status, "executed_simulated")

    def test_13_multiple_tasks_distinct_records(self) -> None:
        """13. Múltiplas tarefas geram registros distintos e sequenciais."""
        orchestrator = Orchestrator(simulate=True, log_dir=self.log_dir)

        # Tarefa 1
        res1 = orchestrator.process_command("Therion, abra o Obsidian")
        orchestrator.confirm_and_execute(res1.plan, confirmed=True)

        # Tarefa 2 (comando inválido)
        orchestrator.process_command("Therion, comando inexistente")

        orch_log = os.path.join(self.log_dir, "audit.jsonl")
        records = self._read_logged_records(orch_log)
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]["task_id"], records[1]["task_id"])
        self.assertEqual(records[0]["task_status"], "concluido")
        self.assertEqual(records[1]["task_status"], "falhou")

    def test_14_temporary_directories_do_not_pollute_real_logs(self) -> None:
        """14. Testes usam diretório temporário isolado."""
        self.assertTrue(self.log_dir.startswith(tempfile.gettempdir()))

    def test_15_absolute_path_backslash_redacted(self) -> None:
        """15. Caminho absoluto Windows com barra invertida é redigido em command."""
        task = TaskContext(
            command="Therion, leia no Segundo Cérebro C:\\Users\\fulano\\nota.md"
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertNotIn("C:\\Users", record["command"])
        self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", record["command"])

    def test_16_absolute_path_forward_slash_redacted(self) -> None:
        """16. Caminho absoluto Windows com barra normal é redigido."""
        task = TaskContext(
            command="Therion, leia C:/Users/fulano/nota.md",
            error="Falha ao ler C:/Users/fulano/outro.md",
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertNotIn("C:/Users", record["command"])
        self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", record["command"])
        self.assertNotIn("C:/Users", record["error"])
        self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", record["error"])

    def test_17_unc_path_redacted(self) -> None:
        """17. Caminho UNC (\\\\servidor\\...) é redigido."""
        task = TaskContext(
            command="Therion, leia \\\\servidor\\compartilhada\\nota.md"
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertNotIn("servidor", record["command"])
        self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", record["command"])

    def test_18_path_redacted_in_all_four_fields(self) -> None:
        """18. Redação de path cobre command, error, target e context_queries.path."""
        task = TaskContext(
            command="leia D:\\Docs\\a.md",
            error="negado: E:\\Privado\\b.md",
            target="F:/Pessoal/c.md",
            context_queries=[
                {
                    "path": "\\\\srv\\dados\\d.md",
                    "success": False,
                    "error": "Acesso negado: G:\\Restrito\\e.md",
                }
            ],
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertNotIn("D:\\Docs", record["command"])
        self.assertNotIn("E:\\Privado", record["error"])
        self.assertNotIn("F:/Pessoal", record["target"])
        self.assertNotIn("srv", record["context_queries"][0]["path"])
        self.assertNotIn("G:\\Restrito", record["context_queries"][0]["error"])
        for field in ("command", "error", "target"):
            self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", record[field])
        self.assertIn(
            "[CAMINHO ABSOLUTO REDIGIDO]", record["context_queries"][0]["path"]
        )

    def test_19_relative_paths_preserved(self) -> None:
        """19. Paths relativos permanecem intactos em command, target e queries."""
        rel = "10 - Projetos/Therion/Estado Atual.md"
        task = TaskContext(
            command=f"Therion, leia no Segundo Cérebro {rel}",
            target=rel,
            context_queries=[{"path": rel, "success": True, "error": None}],
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["command"], f"Therion, leia no Segundo Cérebro {rel}")
        self.assertEqual(record["target"], rel)
        self.assertEqual(record["context_queries"][0]["path"], rel)

    def test_20_secrets_still_redacted_with_paths(self) -> None:
        """20. Regressão: segredos continuam redigidos mesmo com paths no mesmo campo."""
        task = TaskContext(
            command="abrir C:\\Users\\a\\b.md com token: secret_token_12345",
            error="password = super_secret_pass em C:\\Temp\\x.md",
        )
        self.logger.log_task(task)
        with open(self.logger.log_path, "r", encoding="utf-8") as f:
            raw_log = f.read()
        self.assertNotIn("secret_token_12345", raw_log)
        self.assertNotIn("super_secret_pass", raw_log)
        self.assertIn("[REDACTED]", raw_log)
        self.assertIn("[CAMINHO ABSOLUTO REDIGIDO]", raw_log)

    def test_21_quoted_paths_with_spaces_preserve_sentence(self) -> None:
        """Caminhos citados são redigidos sem apagar o restante da frase."""
        task = TaskContext(
            command='Leia "C:\\Minha Pasta\\nota.md" durante a revisão',
            error="Falha em 'D:/Outra Pasta/arquivo.md' durante leitura",
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(
            record["command"],
            'Leia "[CAMINHO ABSOLUTO REDIGIDO]" durante a revisão',
        )
        self.assertEqual(
            record["error"],
            "Falha em '[CAMINHO ABSOLUTO REDIGIDO]' durante leitura",
        )

    def test_22_unquoted_paths_with_spaces_over_redact(self) -> None:
        """O limite ambíguo de path sem aspas é o fim do campo/linha."""
        task = TaskContext(
            command="Leia C:\\Minha Pasta\\nota.md durante a revisão",
            error="Falha em \\\\servidor\\Minha Pasta\\nota.md durante leitura\nPróxima linha preservada",
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        marker = "[CAMINHO ABSOLUTO REDIGIDO]"
        self.assertEqual(record["command"], f"Leia {marker}")
        self.assertEqual(record["error"], f"Falha em {marker}\nPróxima linha preservada")

    def test_23_target_and_query_paths_with_mixed_text(self) -> None:
        """Valor absoluto inteiro e path embutido usam o mesmo marcador."""
        task = TaskContext(
            target="C:\\Minha Pasta\\nota.md",
            context_queries=[
                {
                    "path": "Arquivo em D:/Outra Pasta/nota.md durante leitura",
                    "success": False,
                }
            ],
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        marker = "[CAMINHO ABSOLUTO REDIGIDO]"
        self.assertEqual(record["target"], marker)
        self.assertEqual(record["context_queries"][0]["path"], f"Arquivo em {marker}")

    def test_24_quoted_path_does_not_cross_line_and_secret_stays_redacted(self) -> None:
        """Aspas não atravessam linha; segredos continuam mascarados."""
        task = TaskContext(
            command='Leia "C:\\Pasta com Espaços\\nota.md" e token: valor123',
            error='Falha em "C:\\Pasta com Espaços\\nota.md\nlinha seguinte',
        )
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(
            record["command"],
            'Leia "[CAMINHO ABSOLUTO REDIGIDO]" e token: [REDACTED]',
        )
        self.assertEqual(
            record["error"],
            'Falha em "[CAMINHO ABSOLUTO REDIGIDO]\nlinha seguinte',
        )

    def test_25_target_with_mixed_text_redacts_absolute_path(self) -> None:
        """Target misto preserva o prefixo sem expor o caminho absoluto."""
        task = TaskContext(target="erro em C:\\Users\\Nome\\Minha Pasta\\a.md")
        self.logger.log_task(task)
        record = self._read_logged_records()[0]
        self.assertEqual(record["target"], "erro em [CAMINHO ABSOLUTO REDIGIDO]")
        self.assertNotIn("C:\\Users", record["target"])
        self.assertNotIn("Minha Pasta", record["target"])

    def test_26_read_scope_roots_without_declaration_are_null(self) -> None:
        """As quatro chaves existem e mantêm None como JSON null."""
        self.assertTrue(self.logger.log_task(TaskContext()))
        record = self._read_logged_records()[0]
        for field in (
            "declared_roots",
            "accepted_roots",
            "effective_roots",
            "used_roots",
        ):
            self.assertIn(field, record)
            self.assertIsNone(record[field])

    def test_27_empty_and_invalid_read_scope_roots(self) -> None:
        """Scope vazio e scope inv�lido preservam a distin��o []/null."""
        self.assertTrue(
            self.logger.log_task(
                TaskContext(
                    declared_roots=[], accepted_roots=[], effective_roots=[], used_roots=[]
                )
            )
        )
        self.assertTrue(self.logger.log_task(TaskContext(used_roots=[])))
        empty, invalid = self._read_logged_records()
        for field in (
            "declared_roots",
            "accepted_roots",
            "effective_roots",
            "used_roots",
        ):
            self.assertEqual(empty[field], [])
        for field in ("declared_roots", "accepted_roots", "effective_roots"):
            self.assertIsNone(invalid[field])
        self.assertEqual(invalid["used_roots"], [])

    def test_28_read_scope_roots_keep_order_and_original_lists(self) -> None:
        """Roots relativas preservam grafia e ordem; o log n�o altera TaskContext."""
        declared = ["10 - Projetos/Therion", "90 - Sistema da IA"]
        accepted = ["90 - sistema da ia", "10 - projetos/therion"]
        task = TaskContext(
            declared_roots=declared,
            accepted_roots=accepted,
            effective_roots=list(accepted),
            used_roots=list(reversed(accepted)),
        )
        self.assertTrue(self.logger.log_task(task))
        record = self._read_logged_records()[0]
        self.assertEqual(record["declared_roots"], declared)
        self.assertEqual(record["accepted_roots"], accepted)
        self.assertEqual(record["effective_roots"], accepted)
        self.assertEqual(record["used_roots"], list(reversed(accepted)))
        self.assertEqual(task.declared_roots, declared)
        self.assertEqual(task.accepted_roots, accepted)
        self.assertEqual(task.effective_roots, accepted)
        self.assertEqual(task.used_roots, list(reversed(accepted)))

    def test_29_read_scope_roots_redact_absolute_paths_and_secrets(self) -> None:
        """Sanitiza cada item sem expor path absoluto nem segredo inesperado."""
        absolute = "C:\\Users\\Nome\\Minha Pasta\\a.md"
        unc = "\\\\servidor\\share\\nota.md"
        task = TaskContext(
            declared_roots=["10 - Projetos/Therion", absolute, "token=valor123"],
            accepted_roots=[unc],
            effective_roots=["10 - projetos/therion"],
            used_roots=[absolute],
        )
        self.assertTrue(self.logger.log_task(task))
        record = self._read_logged_records()[0]
        marker = "[CAMINHO ABSOLUTO REDIGIDO]"
        self.assertEqual(
            record["declared_roots"],
            ["10 - Projetos/Therion", marker, "token: [REDACTED]"],
        )
        self.assertEqual(record["accepted_roots"], [marker])
        self.assertEqual(record["effective_roots"], ["10 - projetos/therion"])
        self.assertEqual(record["used_roots"], [marker])
        self.assertEqual(task.declared_roots[1], absolute)
        self.assertEqual(task.accepted_roots[0], unc)


class TestAuditDefaultLocation(unittest.TestCase):
    """O log padrão fica no estado local, fora do repositório."""

    def test_default_dir_follows_localappdata(self) -> None:
        with tempfile.TemporaryDirectory() as local:
            with patch.dict(os.environ, {"LOCALAPPDATA": local}):
                logger = AuditLogger()
            self.assertEqual(logger.log_dir, os.path.join(os.path.abspath(local), "Therion", "logs"))


if __name__ == "__main__":
    unittest.main()
