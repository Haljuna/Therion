"""Autenticação Google Calendar com token persistido externamente."""

import json
import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from therion.calendar.adapter import CalendarError


SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _get_therion_dir() -> Path:
    """Retorna o diretório %APPDATA%\\Therion\\ (Windows) ou ~/.config/Therion (fallback)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "Therion"
    else:
        base = Path.home() / ".config" / "Therion"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_credentials_path() -> Path:
    """Retorna o caminho do credentials.json."""
    return _get_therion_dir() / "credentials.json"


def _get_token_path() -> Path:
    """Retorna o caminho do token.json."""
    return _get_therion_dir() / "token.json"


def load_credentials() -> Credentials | None:
    """Carrega credenciais do token.json se existir e for válido.
    
    Returns:
        Credentials válidas ou None se token ausente/inválido.
    
    Raises:
        CalendarError: Se token existe mas é inválido e não pode ser feito refresh.
    """
    token_path = _get_token_path()
    
    if not token_path.exists():
        return None
    
    try:
        with token_path.open("r", encoding="utf-8") as f:
            token_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise CalendarError(f"Token inválido ou corrompido: {e}") from e
    
    try:
        creds = Credentials.from_authorized_user_info(token_data, scopes=[SCOPE])
    except Exception as e:
        raise CalendarError(f"Falha ao carregar credenciais do token: {e}") from e
    
    return creds


def ensure_valid_credentials(creds: Credentials | None) -> Credentials:
    """Garante que as credenciais são válidas, fazendo refresh se necessário.
    
    Args:
        creds: Credenciais carregadas (podem ser None, expiradas, ou válidas).
    
    Returns:
        Credentials válidas e atualizadas.
    
    Raises:
        CalendarError: Se credenciais ausentes, inválidas sem refresh_token,
                       ou refresh falhou.
    """
    if creds is None:
        raise CalendarError(
            "Token de acesso ausente. Execute a autenticação inicial "
            "para gerar token.json em %APPDATA%\\Therion\\."
        )
    
    if creds.valid:
        return creds
    
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _persist_token(creds)
            return creds
        except Exception as e:
            raise CalendarError(
                f"Falha ao renovar token de acesso: {e}. "
                "Reautenticação necessária."
            ) from e
    
    raise CalendarError(
        "Token expirado e sem refresh_token disponível. "
        "Reautenticação necessária."
    )


def _persist_token(creds: Credentials) -> None:
    """Persiste token atualizado no token.json."""
    token_path = _get_token_path()
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "universe_domain": creds.universe_domain,
    }
    
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat()
    
    try:
        temp_path = token_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(token_data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, token_path)
    except Exception as e:
        raise CalendarError(f"Falha ao persistir token atualizado: {e}") from e


def get_valid_credentials() -> Credentials:
    """Fluxo completo: carrega token, valida, faz refresh se necessário.
    
    Returns:
        Credentials válidas prontas para uso.
    
    Raises:
        CalendarError: Em qualquer falha controlada (token ausente, inválido,
                       refresh falhou, persistência falhou).
    """
    creds = load_credentials()
    return ensure_valid_credentials(creds)


def run_initial_auth() -> None:
    """Executa o fluxo OAuth inicial e persiste o token resultante.

    Deve ser executado manualmente uma única vez para gerar token.json.
    Não apaga token existente automaticamente.

    Requer credentials.json em %APPDATA%\\Therion\\ (gerado no Google Cloud Console).

    Raises:
        CalendarError: Se credentials.json ausente ou se o fluxo OAuth falhar.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow  # importação local: dep. opcional

    credentials_path = _get_credentials_path()

    if not credentials_path.exists():
        raise CalendarError(
            f"credentials.json não encontrado em: {credentials_path}\n"
            "Faça o download do credentials.json no Google Cloud Console e "
            "coloque-o em %APPDATA%\\Therion\\ antes de executar a autenticação."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path), scopes=[SCOPE]
        )
        creds = flow.run_local_server(port=0)
    except Exception as e:
        raise CalendarError(
            f"Falha durante o fluxo OAuth: {e}\n"
            "Verifique se o credentials.json é válido e tente novamente."
        ) from e

    _persist_token(creds)