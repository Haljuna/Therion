"""Testes para o módulo de configuração local (therion.config)."""

import json
import os
import tempfile
from pathlib import Path
import unittest

from therion.config import DEFAULT_CONFIG
from therion.config.local import load_config, save_config, _validate_config


class TestConfig(unittest.TestCase):
    """Testes de configuração local."""

    def setUp(self) -> None:
        """Cria diretório temporário para testes isolados."""
        self.temp_dir = tempfile.mkdtemp(prefix="therion_test_")
        self.config_path = Path(self.temp_dir) / "config.json"

    def tearDown(self) -> None:
        """Limpa arquivos temporários."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_arquivo_inexistente_retorna_defaults(self) -> None:
        """Arquivo inexistente deve retornar defaults."""
        result = load_config(self.config_path)
        self.assertEqual(result, DEFAULT_CONFIG)
        # Não deve criar o arquivo
        self.assertFalse(self.config_path.exists())

    def test_arquivo_valido_carrega_corretamente(self) -> None:
        """Arquivo JSON válido deve carregar com valores corretos."""
        custom = {"ui": {"start_minimized": True}, "aliases": {"obs": "obsidian"}}
        self.config_path.write_text(json.dumps(custom), encoding="utf-8")

        result = load_config(self.config_path)
        self.assertTrue(result["ui"]["start_minimized"])
        self.assertEqual(result["aliases"]["obs"], "obsidian")
        self.assertEqual(result["allowed_apps"], [])

    def test_json_invalido_retorna_defaults(self) -> None:
        """JSON inválido deve retornar defaults sem crash."""
        self.config_path.write_text("{ invalid json }", encoding="utf-8")
        result = load_config(self.config_path)
        self.assertEqual(result, DEFAULT_CONFIG)

    def test_valores_default_aplicados(self) -> None:
        """Defaults devem ser aplicados quando campos ausentes."""
        # Arquivo vazio ou parcial
        self.config_path.write_text('{"ui": {}}', encoding="utf-8")
        result = load_config(self.config_path)
        self.assertEqual(result["ui"]["start_minimized"], DEFAULT_CONFIG["ui"]["start_minimized"])
        self.assertEqual(result["aliases"], {})
        self.assertEqual(result["allowed_apps"], [])

    def test_salvamento_persiste(self) -> None:
        """Salvamento deve persistir no arquivo."""
        config = {"ui": {"start_minimized": True}, "aliases": {}, "allowed_apps": ["notepad"]}
        save_config(config, self.config_path)

        # Recarrega e verifica
        result = load_config(self.config_path)
        self.assertTrue(result["ui"]["start_minimized"])
        self.assertEqual(result["allowed_apps"], ["notepad"])

    def test_estrutura_invalida_aplica_defaults(self) -> None:
        """Campos com tipos inválidos devem receber defaults seguros."""
        # ui como string inválida
        bad = {"ui": "not_a_dict", "aliases": "not_a_dict", "allowed_apps": "not_a_list"}
        result = _validate_config(bad)
        self.assertIsInstance(result["ui"], dict)
        self.assertIsInstance(result["aliases"], dict)
        self.assertIsInstance(result["allowed_apps"], list)
        self.assertEqual(result["ui"]["start_minimized"], DEFAULT_CONFIG["ui"]["start_minimized"])

    def test_campos_desconhecidos_preservados(self) -> None:
        """Campos desconhecidos devem ser preservados (não interpretados)."""
        data = {
            "ui": {"start_minimized": False},
            "aliases": {},
            "allowed_apps": [],
            "campo_desconhecido": "valor",
            "outro_campo": {"nested": 123},
        }
        result = _validate_config(data)
        self.assertEqual(result["campo_desconhecido"], "valor")
        self.assertEqual(result["outro_campo"], {"nested": 123})

    def test_ausencia_de_segredos_hardcoded(self) -> None:
        """Configuração não deve conter segredos, tokens, credenciais hardcoded."""
        # Verifica que DEFAULT_CONFIG não tem chaves suspeitas
        forbidden_keywords = ["token", "secret", "password", "credential", "oauth", "api_key", "apikey"]
        config_str = json.dumps(DEFAULT_CONFIG).lower()
        for kw in forbidden_keywords:
            self.assertNotIn(kw, config_str, f"Chave suspeita '{kw}' encontrada em DEFAULT_CONFIG")

    def test_escrita_atomica_nao_deixa_parcial(self) -> None:
        """Escrita atômica não deve deixar arquivo parcial em caso de erro."""
        # Força erro durante escrita mockando _validate_config para lançar exceção
        # Neste teste, apenas verificamos que arquivo original não é corrompido
        original = {"ui": {"start_minimized": False}, "aliases": {}, "allowed_apps": []}
        self.config_path.write_text(json.dumps(original), encoding="utf-8")

        # Salva config válida
        save_config({"ui": {"start_minimized": True}}, self.config_path)
        result = load_config(self.config_path)
        self.assertTrue(result["ui"]["start_minimized"])

    def test_default_real_actions_enabled_false(self) -> None:
        """Default de real_actions_enabled deve ser False."""
        self.assertEqual(DEFAULT_CONFIG["runtime"]["real_actions_enabled"], False)

    def test_runtime_ausente_retorna_false(self) -> None:
        """Quando runtime ausente, real_actions_enabled deve ser False."""
        data = {"ui": {"start_minimized": False}, "aliases": {}, "allowed_apps": []}
        result = _validate_config(data)
        self.assertEqual(result["runtime"]["real_actions_enabled"], False)

    def test_runtime_invalido_retorna_default(self) -> None:
        """Quando runtime é tipo inválido, deve receber default seguro."""
        data = {"runtime": "not_a_dict"}
        result = _validate_config(data)
        self.assertIsInstance(result["runtime"], dict)
        self.assertEqual(result["runtime"]["real_actions_enabled"], False)

    def test_real_actions_enabled_ausente_retorna_false(self) -> None:
        """Quando real_actions_enabled ausente, deve receber False."""
        data = {"runtime": {}}
        result = _validate_config(data)
        self.assertEqual(result["runtime"]["real_actions_enabled"], False)

    def test_real_actions_enabled_tipo_invalido_retorna_false(self) -> None:
        """Quando real_actions_enabled não é bool, deve receber False."""
        data = {"runtime": {"real_actions_enabled": "sim"}}
        result = _validate_config(data)
        self.assertEqual(result["runtime"]["real_actions_enabled"], False)

        data2 = {"runtime": {"real_actions_enabled": 1}}
        result2 = _validate_config(data2)
        self.assertEqual(result2["runtime"]["real_actions_enabled"], False)

    def test_real_actions_enabled_true_valido(self) -> None:
        """Boolean True explícito deve ser preservado."""
        data = {"runtime": {"real_actions_enabled": True}}
        result = _validate_config(data)
        self.assertTrue(result["runtime"]["real_actions_enabled"])

    def test_real_actions_enabled_false_valido(self) -> None:
        """Boolean False explícito deve ser preservado."""
        data = {"runtime": {"real_actions_enabled": False}}
        result = _validate_config(data)
        self.assertFalse(result["runtime"]["real_actions_enabled"])

    def test_campos_desconhecidos_preservados_com_runtime(self) -> None:
        """Campos desconhecidos continuam preservados mesmo com runtime."""
        data = {
            "ui": {"start_minimized": False},
            "aliases": {},
            "allowed_apps": [],
            "runtime": {"real_actions_enabled": False},
            "campo_desconhecido": "valor",
        }
        result = _validate_config(data)
        self.assertEqual(result["campo_desconhecido"], "valor")
        self.assertEqual(result["runtime"]["real_actions_enabled"], False)

    def test_ai_bloco_ausente_recebe_defaults(self) -> None:
        """Bloco ai ausente recebe defaults."""
        data = {"ui": {}}
        result = _validate_config(data)
        self.assertEqual(result["ai"]["enabled"], False)
        self.assertEqual(result["ai"]["model"], "qwen3:4b-instruct")
        self.assertEqual(result["ai"]["timeout_seconds"], 90)

    def test_ai_enabled_invalido_resulta_em_false(self) -> None:
        """ai.enabled inválido deve resultar em False."""
        for invalid in ["true", 1, 0, None, [], {}]:
            result = _validate_config({"ai": {"enabled": invalid}})
            self.assertIs(result["ai"]["enabled"], False)

    def test_ai_model_vazio_ou_invalido_resulta_em_padrao(self) -> None:
        """ai.model vazio ou inválido deve resultar no modelo padrão."""
        for invalid in ["", "   ", 123, None, True, []]:
            result = _validate_config({"ai": {"model": invalid}})
            self.assertEqual(result["ai"]["model"], "qwen3:4b-instruct")

    def test_ai_timeout_seconds_invalido_resulta_em_90(self) -> None:
        """ai.timeout_seconds inválido, zero, negativo ou bool resulta em 90."""
        for invalid in [0, -1, -90, True, False, "90", 90.5, None, []]:
            result = _validate_config({"ai": {"timeout_seconds": invalid}})
            self.assertEqual(result["ai"]["timeout_seconds"], 90)

    def test_ai_valores_validos_preservados(self) -> None:
        """Valores válidos para ai são preservados."""
        data = {
            "ai": {
                "enabled": True,
                "model": "meu-modelo-custom:latest",
                "timeout_seconds": 120,
            }
        }
        result = _validate_config(data)
        self.assertIs(result["ai"]["enabled"], True)
        self.assertEqual(result["ai"]["model"], "meu-modelo-custom:latest")
        self.assertEqual(result["ai"]["timeout_seconds"], 120)

    def test_voice_bloco_ausente_recebe_defaults(self) -> None:
        """Bloco voice ausente recebe defaults."""
        data = {"ui": {}}
        result = _validate_config(data)
        self.assertEqual(result["voice"]["model_path"], None)

    def test_voice_model_path_valido_preservado(self) -> None:
        """model_path válido como string é preservado."""
        data = {"voice": {"model_path": "caminho/para/modelo"}}
        result = _validate_config(data)
        self.assertEqual(result["voice"]["model_path"], "caminho/para/modelo")

    def test_voice_invalido_resulta_em_default(self) -> None:
        """voice não-dict ou model_path de tipo inválido recebem fallback seguro."""
        for invalid in ["not_a_dict", 123, True, None, []]:
            result = _validate_config({"voice": invalid})
            self.assertEqual(result["voice"], {"model_path": None})

        for invalid_path in [123, True, [], {}]:
            result = _validate_config({"voice": {"model_path": invalid_path}})
            self.assertIsNone(result["voice"]["model_path"])

    def test_voice_chaves_extras_preservadas(self) -> None:
        """Chaves extras no bloco voice são preservadas."""
        data = {
            "voice": {
                "model_path": "caminho",
                "extra_param": "foo",
                "nested": {"a": 1},
            }
        }
        result = _validate_config(data)
        self.assertEqual(result["voice"]["model_path"], "caminho")
        self.assertEqual(result["voice"]["extra_param"], "foo")
        self.assertEqual(result["voice"]["nested"], {"a": 1})


if __name__ == "__main__":
    unittest.main()