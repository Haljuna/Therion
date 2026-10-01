"""Configuração local do Therion em JSON.

Armazenamento: %APPDATA%\\Therion\\config.json (Windows)
Estrutura mínima inicial:
{
  "ui": {"start_minimized": false},
  "aliases": {},
  "allowed_apps": []
}

Regras:
- Campos conhecidos validados rigorosamente; inválidos -> default seguro
- Campos desconhecidos preservados (não interpretados)
- Arquivo inexistente -> defaults
- JSON inválido -> defaults + aviso controlado
- Escrita atômica (temp + rename)
- Sem segredos, tokens, credenciais
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "ui": {"start_minimized": False},
    "aliases": {},
    "allowed_apps": [],
    "runtime": {"real_actions_enabled": False},
    "calendar": {"enabled": False, "time_zone": "America/Sao_Paulo"},
    "ai": {
        "enabled": False,
        "model": "qwen3:4b-instruct",
        "timeout_seconds": 90,
    },
    "voice": {"model_path": None},
}

_CONFIG_PATH: Path | None = None


def _get_config_path() -> Path:
    """Retorna o caminho padrão do arquivo de configuração."""
    global _CONFIG_PATH
    if _CONFIG_PATH is not None:
        return _CONFIG_PATH
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "Therion"
    else:
        base = Path.home() / "AppData" / "Roaming" / "Therion"
    base.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH = base / "config.json"
    return _CONFIG_PATH


def _validate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Valida campos conhecidos; aplica defaults se inválidos; preserva desconhecidos."""
    validated = DEFAULT_CONFIG.copy()
    validated.update(data)

    # ui.start_minimized -> bool
    ui = validated.get("ui")
    if not isinstance(ui, dict):
        validated["ui"] = DEFAULT_CONFIG["ui"].copy()
    else:
        sm = ui.get("start_minimized")
        if not isinstance(sm, bool):
            ui["start_minimized"] = DEFAULT_CONFIG["ui"]["start_minimized"]
        validated["ui"] = ui

    # aliases -> dict
    aliases = validated.get("aliases")
    if not isinstance(aliases, dict):
        validated["aliases"] = DEFAULT_CONFIG["aliases"].copy()
    else:
        validated["aliases"] = aliases

    # allowed_apps -> list
    allowed = validated.get("allowed_apps")
    if not isinstance(allowed, list):
        validated["allowed_apps"] = DEFAULT_CONFIG["allowed_apps"].copy()
    else:
        validated["allowed_apps"] = allowed

    # runtime.real_actions_enabled -> bool
    runtime = validated.get("runtime")
    if not isinstance(runtime, dict):
        validated["runtime"] = DEFAULT_CONFIG["runtime"].copy()
    else:
        rae = runtime.get("real_actions_enabled")
        if not isinstance(rae, bool):
            runtime["real_actions_enabled"] = DEFAULT_CONFIG["runtime"]["real_actions_enabled"]
        validated["runtime"] = runtime

    # calendar.enabled -> bool, calendar.time_zone -> str
    calendar = validated.get("calendar")
    if not isinstance(calendar, dict):
        validated["calendar"] = DEFAULT_CONFIG["calendar"].copy()
    else:
        cal_enabled = calendar.get("enabled")
        if not isinstance(cal_enabled, bool):
            calendar["enabled"] = DEFAULT_CONFIG["calendar"]["enabled"]
        cal_tz = calendar.get("time_zone")
        if not isinstance(cal_tz, str):
            calendar["time_zone"] = DEFAULT_CONFIG["calendar"]["time_zone"]
        validated["calendar"] = calendar

    # ai.enabled -> bool, ai.model -> str não vazia, ai.timeout_seconds -> int estrito > 0
    ai = validated.get("ai")
    if not isinstance(ai, dict):
        validated["ai"] = DEFAULT_CONFIG["ai"].copy()
    else:
        ai_enabled = ai.get("enabled")
        if not isinstance(ai_enabled, bool):
            ai["enabled"] = DEFAULT_CONFIG["ai"]["enabled"]
        ai_model = ai.get("model")
        if not isinstance(ai_model, str) or not ai_model.strip():
            ai["model"] = DEFAULT_CONFIG["ai"]["model"]
        ai_timeout = ai.get("timeout_seconds")
        if type(ai_timeout) is not int or ai_timeout <= 0:
            ai["timeout_seconds"] = DEFAULT_CONFIG["ai"]["timeout_seconds"]
        validated["ai"] = ai

    # voice -> dict com model_path (str | None); preserva chaves extras
    voice = validated.get("voice")
    if not isinstance(voice, dict):
        validated["voice"] = DEFAULT_CONFIG["voice"].copy()
    else:
        voice_merged = DEFAULT_CONFIG["voice"].copy()
        voice_merged.update(voice)
        model_path = voice_merged.get("model_path")
        if model_path is not None and not isinstance(model_path, str):
            voice_merged["model_path"] = None
        validated["voice"] = voice_merged

    return validated


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Carrega configuração do arquivo; fallback para defaults se ausente/inválido."""
    config_path = Path(path) if path else _get_config_path()

    if not config_path.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Arquivo corrompido/ilegível -> defaults seguros
        return DEFAULT_CONFIG.copy()

    if not isinstance(data, dict):
        return DEFAULT_CONFIG.copy()

    return _validate_config(data)


def save_config(config: dict[str, Any], path: Path | str | None = None) -> None:
    """Salva configuração com escrita atômica (temp + rename)."""
    config_path = Path(path) if path else _get_config_path()
    validated = _validate_config(config)

    # Escrita atômica: escreve em temp e depois renomeia
    temp_fd, temp_path = tempfile.mkstemp(
        dir=config_path.parent, prefix=".config.", suffix=".tmp"
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(validated, f, ensure_ascii=False, indent=2)
        # rename atômico no mesmo filesystem
        os.replace(temp_path, config_path)
    except Exception:
        # Limpa temp se algo falhou
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise