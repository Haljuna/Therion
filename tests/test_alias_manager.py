"""Testes unitários do AliasManager (therion.config.alias_manager)."""

import unittest
from unittest.mock import patch

from therion.config.alias_manager import AliasManager, AliasResult


def _make_manager(aliases: dict[str, str] | None = None) -> AliasManager:
    """Cria AliasManager com configuração temporária (sem tocar %APPDATA%)."""
    config = {"aliases": aliases or {}}
    with patch("therion.config.alias_manager.load_config", return_value=config):
        return AliasManager()


class TestResolve(unittest.TestCase):
    """Testes de resolve()."""

    def setUp(self) -> None:
        self.mgr = _make_manager({"obs": "Obsidian", "vs": "VS Code"})

    def test_alias_valido_resolve_corretamente(self) -> None:
        self.assertEqual(self.mgr.resolve("obs"), "Obsidian")

    def test_case_insensitive(self) -> None:
        self.assertEqual(self.mgr.resolve("OBS"), "Obsidian")
        self.assertEqual(self.mgr.resolve("Obs"), "Obsidian")

    def test_alias_inexistente_retorna_original(self) -> None:
        self.assertEqual(self.mgr.resolve("nao_existe"), "nao_existe")

    def test_espacos_extremidades_normalizados(self) -> None:
        self.assertEqual(self.mgr.resolve("  obs  "), "Obsidian")

    def test_retorna_capitalizado_se_lower(self) -> None:
        mgr = _make_manager({"x": "terminal"})
        self.assertEqual(mgr.resolve("x"), "Terminal")

    def test_nao_string_retorna_original(self) -> None:
        self.assertEqual(self.mgr.resolve(123), 123)
        self.assertIsNone(self.mgr.resolve(None))


class TestListAliases(unittest.TestCase):
    """Testes de list_aliases()."""

    def setUp(self) -> None:
        self.mgr = _make_manager({"a": "Alpha", "b": "Beta"})

    def test_retorna_aliases_atuais(self) -> None:
        result = self.mgr.list_aliases()
        self.assertEqual(result, {"a": "Alpha", "b": "Beta"})

    def test_copia_nao_altera_estado_interno(self) -> None:
        result = self.mgr.list_aliases()
        result["novo"] = "Novo"
        self.assertNotIn("novo", self.mgr.list_aliases())


class TestAddAlias(unittest.TestCase):
    """Testes de add_alias()."""

    def setUp(self) -> None:
        self.mgr = _make_manager({"existing": "Value"})

    @patch("therion.config.alias_manager.save_config")
    def test_adiciona_alias_valido(self, mock_save) -> None:
        result = self.mgr.add_alias("new_alias", "Target")
        self.assertTrue(result.success)
        self.assertEqual(self.mgr.list_aliases()["new_alias"], "Target")
        mock_save.assert_called_once()

    @patch("therion.config.alias_manager.save_config")
    def test_duplicata_nao_sobrescreve(self, mock_save) -> None:
        result = self.mgr.add_alias("existing", "Other")
        self.assertFalse(result.success)
        self.assertIn("já existe", result.message)
        self.assertEqual(self.mgr.list_aliases()["existing"], "Value")

    @patch("therion.config.alias_manager.save_config")
    def test_chave_vazia_rejeitada(self, mock_save) -> None:
        result = self.mgr.add_alias("", "Target")
        self.assertFalse(result.success)
        self.assertIn("vazia", result.message)

    @patch("therion.config.alias_manager.save_config")
    def test_alvo_vazio_rejeitado(self, mock_save) -> None:
        result = self.mgr.add_alias("key", "")
        self.assertFalse(result.success)
        self.assertIn("vazio", result.message)

    @patch("therion.config.alias_manager.save_config")
    def test_chave_so_espacos_rejeitada(self, mock_save) -> None:
        result = self.mgr.add_alias("   ", "Target")
        self.assertFalse(result.success)

    @patch("therion.config.alias_manager.save_config")
    def test_alvo_so_espacos_rejeitado(self, mock_save) -> None:
        result = self.mgr.add_alias("key", "   ")
        self.assertFalse(result.success)

    @patch("therion.config.alias_manager.save_config")
    def test_tipos_invalidos_nao_causam_crash(self, mock_save) -> None:
        for key, target in [(123, "x"), ("x", 456), (None, "x"), ("x", None), (123, 456)]:
            result = self.mgr.add_alias(key, target)  # type: ignore[arg-type]
            self.assertFalse(result.success)
            self.assertIsInstance(result, AliasResult)


class TestRemoveAlias(unittest.TestCase):
    """Testes de remove_alias()."""

    def setUp(self) -> None:
        self.mgr = _make_manager({"to_remove": "Value", "keep": "Other"})

    @patch("therion.config.alias_manager.save_config")
    def test_sem_confirm_bloqueado(self, mock_save) -> None:
        result = self.mgr.remove_alias("to_remove", confirm=False)
        self.assertFalse(result.success)
        self.assertIn("confirm=True", result.message)
        self.assertIn("to_remove", self.mgr.list_aliases())

    @patch("therion.config.alias_manager.save_config")
    def test_com_confirm_remove(self, mock_save) -> None:
        result = self.mgr.remove_alias("to_remove", confirm=True)
        self.assertTrue(result.success)
        self.assertNotIn("to_remove", self.mgr.list_aliases())
        mock_save.assert_called_once()

    @patch("therion.config.alias_manager.save_config")
    def test_alias_inexistente_retorna_resultado_controlado(self, mock_save) -> None:
        result = self.mgr.remove_alias("nao_existe", confirm=True)
        self.assertFalse(result.success)
        self.assertIn("não encontrado", result.message)

    @patch("therion.config.alias_manager.save_config")
    def test_chave_vazia_rejeitada(self, mock_save) -> None:
        result = self.mgr.remove_alias("", confirm=True)
        self.assertFalse(result.success)

    @patch("therion.config.alias_manager.save_config")
    def test_tipo_invalido_nao_causa_crash(self, mock_save) -> None:
        result = self.mgr.remove_alias(123, confirm=True)  # type: ignore[arg-type]
        self.assertFalse(result.success)
        self.assertIsInstance(result, AliasResult)


class TestReplaceAlias(unittest.TestCase):
    """Testes de replace_alias()."""

    def setUp(self) -> None:
        self.mgr = _make_manager({"target": "OldValue"})

    @patch("therion.config.alias_manager.save_config")
    def test_sem_confirm_bloqueado(self, mock_save) -> None:
        result = self.mgr.replace_alias("target", "NewValue", confirm=False)
        self.assertFalse(result.success)
        self.assertIn("confirm=True", result.message)
        self.assertEqual(self.mgr.list_aliases()["target"], "OldValue")

    @patch("therion.config.alias_manager.save_config")
    def test_com_confirm_substitui(self, mock_save) -> None:
        result = self.mgr.replace_alias("target", "NewValue", confirm=True)
        self.assertTrue(result.success)
        self.assertEqual(self.mgr.list_aliases()["target"], "NewValue")
        mock_save.assert_called_once()

    @patch("therion.config.alias_manager.save_config")
    def test_alias_inexistente_retorna_resultado_controlado(self, mock_save) -> None:
        result = self.mgr.replace_alias("nao_existe", "Value", confirm=True)
        self.assertFalse(result.success)
        self.assertIn("não encontrado", result.message)

    @patch("therion.config.alias_manager.save_config")
    def test_chave_vazia_rejeitada(self, mock_save) -> None:
        result = self.mgr.replace_alias("", "Value", confirm=True)
        self.assertFalse(result.success)

    @patch("therion.config.alias_manager.save_config")
    def test_alvo_vazio_rejeitado(self, mock_save) -> None:
        result = self.mgr.replace_alias("target", "", confirm=True)
        self.assertFalse(result.success)

    @patch("therion.config.alias_manager.save_config")
    def test_tipos_invalidos_nao_causam_crash(self, mock_save) -> None:
        for key, target in [(123, "x"), ("x", 456), (None, "x"), ("x", None)]:
            result = self.mgr.replace_alias(key, target, confirm=True)  # type: ignore[arg-type]
            self.assertFalse(result.success)
            self.assertIsInstance(result, AliasResult)


if __name__ == "__main__":
    unittest.main()
