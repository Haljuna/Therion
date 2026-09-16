"""Testes unitários de autenticação Google Calendar (Bloco B1 - mockados)."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.oauth2.credentials import Credentials

from therion.calendar.adapter import CalendarError
from therion.calendar.auth import (
    SCOPE,
    _get_therion_dir,
    _get_token_path,
    _persist_token,
    ensure_valid_credentials,
    get_valid_credentials,
    load_credentials,
)


class TestGetTherionDir(unittest.TestCase):
    """Valida obtenção do diretório Therion."""

    def test_usa_appdata_no_windows(self) -> None:
        """1. Usa %APPDATA%\\Therion quando disponível."""
        with patch.dict(os.environ, {"APPDATA": r"C:\Users\Test\AppData\Roaming"}):
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                path = _get_therion_dir()
                self.assertEqual(path, Path(r"C:\Users\Test\AppData\Roaming\Therion"))
                mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_fallback_quando_sem_appdata(self) -> None:
        """2. Fallback para ~/.config/Therion quando APPDATA ausente."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.home", return_value=Path("/home/test")):
                path = _get_therion_dir()
                self.assertEqual(path, Path("/home/test/.config/Therion"))


class TestLoadCredentials(unittest.TestCase):
    """Valida carregamento de credenciais do token.json."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="therion_test_")
        self.token_path = Path(self.temp_dir) / "token.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_token_valido_retorna_credentials(self) -> None:
        """3. Token válido retorna Credentials utilizáveis."""
        token_data = {
            "token": "access_token_123",
            "refresh_token": "refresh_token_456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client_id",
            "client_secret": "client_secret",
            "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
            "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        self.token_path.write_text(json.dumps(token_data), encoding="utf-8")

        with patch("therion.calendar.auth._get_token_path", return_value=self.token_path):
            creds = load_credentials()

        self.assertIsNotNone(creds)
        self.assertIsInstance(creds, Credentials)
        self.assertTrue(creds.valid)

    def test_token_ausente_retorna_none(self) -> None:
        """4. Token ausente retorna None (não levanta)."""
        with patch("therion.calendar.auth._get_token_path", return_value=self.token_path):
            creds = load_credentials()
        self.assertIsNone(creds)

    def test_token_json_invalido_levanta_calendar_error(self) -> None:
        """5. JSON inválido no token levanta CalendarError controlado."""
        self.token_path.write_text("{ invalid json }", encoding="utf-8")

        with patch("therion.calendar.auth._get_token_path", return_value=self.token_path):
            with self.assertRaises(CalendarError) as ctx:
                load_credentials()
        self.assertIn("Token inválido ou corrompido", str(ctx.exception))

    def test_token_estrutura_invalida_levanta_calendar_error(self) -> None:
        """6. Estrutura inválida no token levanta CalendarError."""
        self.token_path.write_text(json.dumps({"invalid": "structure"}), encoding="utf-8")

        with patch("therion.calendar.auth._get_token_path", return_value=self.token_path):
            with self.assertRaises(CalendarError) as ctx:
                load_credentials()
        self.assertIn("Falha ao carregar credenciais", str(ctx.exception))


class TestEnsureValidCredentials(unittest.TestCase):
    """Valida garantia de credenciais válidas (refresh se necessário)."""

    def make_creds(
        self,
        valid: bool = True,
        expired: bool = False,
        refresh_token: str | None = "refresh_123",
        scopes: list[str] | None = None,
    ) -> Credentials:
        """Cria Credentials mockadas com estado controlado."""
        creds = MagicMock(spec=Credentials)
        creds.valid = valid
        creds.expired = expired
        creds.refresh_token = refresh_token
        creds.scopes = scopes or [SCOPE]
        return creds

    def test_ja_valido_retorna_mesmo(self) -> None:
        """7. Credenciais já válidas com scope correto são retornadas sem refresh."""
        creds = self.make_creds(valid=True)
        result = ensure_valid_credentials(creds)
        self.assertIs(result, creds)
        creds.refresh.assert_not_called()

    def test_expirado_com_refresh_token_faz_refresh_e_persiste(self) -> None:
        """8. Expirado com refresh_token e scope correto faz refresh e persiste."""
        creds = self.make_creds(valid=False, expired=True, refresh_token="refresh_123")

        with patch("therion.calendar.auth._persist_token") as mock_persist:
            creds.refresh = MagicMock()
            result = ensure_valid_credentials(creds)

        creds.refresh.assert_called_once()
        mock_persist.assert_called_once_with(creds)
        self.assertIs(result, creds)

    def test_expirado_sem_refresh_token_levanta_calendar_error(self) -> None:
        """9. Expirado sem refresh_token levanta CalendarError pedindo reautenticação."""
        creds = self.make_creds(valid=False, expired=True, refresh_token=None)

        with self.assertRaises(CalendarError) as ctx:
            ensure_valid_credentials(creds)
        self.assertIn("sem refresh_token", str(ctx.exception))
        self.assertIn("Reautenticação necessária", str(ctx.exception))

    def test_refresh_falha_levanta_calendar_error(self) -> None:
        """10. Falha no refresh levanta CalendarError pedindo reautenticação."""
        creds = self.make_creds(valid=False, expired=True, refresh_token="refresh_123")
        creds.refresh = MagicMock(side_effect=Exception("network error"))

        with self.assertRaises(CalendarError) as ctx:
            ensure_valid_credentials(creds)
        self.assertIn("Falha ao renovar token", str(ctx.exception))
        self.assertIn("Reautenticação necessária", str(ctx.exception))

    def test_credenciais_none_levanta_calendar_error(self) -> None:
        """11. Credenciais None levanta CalendarError com mensagem clara."""
        with self.assertRaises(CalendarError) as ctx:
            ensure_valid_credentials(None)
        self.assertIn("Token de acesso ausente", str(ctx.exception))
        self.assertIn("autenticação inicial", str(ctx.exception))

    def test_scope_insuficiente_levanta_calendar_error(self) -> None:
        """12. Token com scope insuficiente (readonly) levanta CalendarError antes de qualquer chamada Google."""
        creds = self.make_creds(
            valid=True,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        with self.assertRaises(CalendarError) as ctx:
            ensure_valid_credentials(creds)
        self.assertIn("insuficiente", str(ctx.exception))
        self.assertIn("Reautenticação necessária", str(ctx.exception))
        creds.refresh.assert_not_called()

    def test_scope_correto_aceito(self) -> None:
        """13. Token com calendar.events.owned é aceito."""
        creds = self.make_creds(
            valid=True,
            scopes=["https://www.googleapis.com/auth/calendar.events.owned"],
        )
        result = ensure_valid_credentials(creds)
        self.assertIs(result, creds)

    def test_expirado_com_scope_correto_faz_refresh(self) -> None:
        """14. Token expirado com scope correto faz refresh normalmente."""
        creds = self.make_creds(
            valid=False,
            expired=True,
            refresh_token="refresh_123",
            scopes=["https://www.googleapis.com/auth/calendar.events.owned"],
        )
        with patch("therion.calendar.auth._persist_token"):
            creds.refresh = MagicMock()
            result = ensure_valid_credentials(creds)
        creds.refresh.assert_called_once()
        self.assertIs(result, creds)

    def test_expirado_com_scope_insuficiente_nao_faz_refresh(self) -> None:
        """15. Token expirado com scope insuficiente NÃO tenta refresh — rejeita imediatamente."""
        creds = self.make_creds(
            valid=False,
            expired=True,
            refresh_token="refresh_123",
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        with self.assertRaises(CalendarError) as ctx:
            ensure_valid_credentials(creds)
        self.assertIn("insuficiente", str(ctx.exception))
        creds.refresh.assert_not_called()


class TestPersistToken(unittest.TestCase):
    """Valida persistência de token atualizado."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="therion_test_")
        self.token_path = Path(self.temp_dir) / "token.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persiste_token_atualizado(self) -> None:
        """12. Persiste token com campos corretos incluindo expiry."""
        creds = MagicMock(spec=Credentials)
        creds.token = "new_access_token"
        creds.refresh_token = "refresh_token"
        creds.token_uri = "https://oauth2.googleapis.com/token"
        creds.client_id = "client_id"
        creds.client_secret = "client_secret"
        creds.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds.universe_domain = "googleapis.com"
        creds.expiry = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)

        with patch("therion.calendar.auth._get_token_path", return_value=self.token_path):
            _persist_token(creds)

        self.assertTrue(self.token_path.exists())
        saved = json.loads(self.token_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["token"], "new_access_token")
        self.assertEqual(saved["refresh_token"], "refresh_token")
        self.assertIn("expiry", saved)


class TestGetValidCredentials(unittest.TestCase):
    """Valida fluxo completo get_valid_credentials."""

    def test_scope_events_owned(self) -> None:
        """13. SCOPE é calendar.events.owned (menor privilégio para escrita)."""
        self.assertEqual(SCOPE, "https://www.googleapis.com/auth/calendar.events.owned")

    def test_fluxo_completo_token_valido(self) -> None:
        """14. Fluxo completo com token válido retorna credenciais."""
        creds = MagicMock(spec=Credentials)
        creds.valid = True

        with patch("therion.calendar.auth.load_credentials", return_value=creds):
            with patch("therion.calendar.auth.ensure_valid_credentials", return_value=creds) as mock_ensure:
                result = get_valid_credentials()

        self.assertIs(result, creds)
        mock_ensure.assert_called_once_with(creds)

    def test_propaga_calendar_error_do_load(self) -> None:
        """15. Propaga CalendarError do load_credentials."""
        with patch("therion.calendar.auth.load_credentials", side_effect=CalendarError("token corrupt")):
            with self.assertRaises(CalendarError) as ctx:
                get_valid_credentials()
        self.assertIn("token corrupt", str(ctx.exception))

    def test_propaga_calendar_error_do_ensure(self) -> None:
        """16. Propaga CalendarError do ensure_valid_credentials."""
        creds = MagicMock(spec=Credentials)
        with patch("therion.calendar.auth.load_credentials", return_value=creds):
            with patch("therion.calendar.auth.ensure_valid_credentials", side_effect=CalendarError("refresh failed")):
                with self.assertRaises(CalendarError) as ctx:
                    get_valid_credentials()
        self.assertIn("refresh failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()