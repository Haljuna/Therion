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
from urllib.parse import urlsplit
import shutil
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "agent": {"enabled": False, "history_enabled": False, "protocol": "json", "timeout_seconds": 180,
        "gmail_enabled": False, "browser_enabled": False, "desktop_enabled": False, "documents_enabled": False,
        "learning_enabled": False, "web_enabled": False},
    "ui": {"start_minimized": False, "interface": "constellation", "graphics_quality": "auto", "reduced_motion": False},
    "aliases": {},
    "allowed_apps": [],
    "runtime": {"real_actions_enabled": False},
    "calendar": {"enabled": False, "time_zone": "America/Sao_Paulo"},
    "ai": {
        "enabled": False,
        "model": "qwen3:4b-instruct",
        "timeout_seconds": 90,
        "endpoint": "http://127.0.0.1:11434/api/chat",
        "think": None,
    },
    "voice": {"model_path": None},
    "tts": {"enabled": False, "provider": "kokoro", "voice": "pm_alex", "model_root": "", "python_path": "", "warm_on_start": False,
            "online_allowed": False, "edge_voice": "pt-BR-AntonioNeural", "edge_python_path": "",
            "voicestudio_endpoint": "http://127.0.0.1:3900/v1/audio/speech",
            "voicestudio_voice": "", "voicestudio_python_path": "",
            "streaming_prepare": False},
}

_CONFIG_PATH: Path | None = None


def is_local_ollama_endpoint(value: Any) -> bool:
    """Aceita apenas HTTP no loopback literal, sem credenciais ou redirecionadores."""
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "http" and url.hostname in ("127.0.0.1", "::1")
                and url.port is not None and 0 < url.port <= 65535
                and url.path == "/api/chat" and not url.query and not url.fragment
                and url.username is None and url.password is None)
    except ValueError:
        return False


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
        ui = ui.copy()
        validated["ui"] = ui
    ui = validated['ui']
    if not isinstance(ui.get('interface'),str) or ui['interface'] not in {'classic', 'constellation'}:
        ui['interface'] = 'constellation'
    if not isinstance(ui.get('graphics_quality'),str) or ui['graphics_quality'] not in {'auto', 'high', 'medium', 'low'}:
        ui['graphics_quality'] = 'auto'
    if type(ui.get('reduced_motion')) is not bool:
        ui['reduced_motion'] = False
    # Nota local da conversa (análise de erros); desligada salvo pedido explícito.
    if type(ui.get('conversation_log')) is not bool:
        ui['conversation_log'] = False

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
        if not is_local_ollama_endpoint(ai.get("endpoint")):
            ai["endpoint"] = DEFAULT_CONFIG["ai"]["endpoint"]
        if ai.get("think") is not None and type(ai["think"]) is not bool:
            ai["think"] = None
        ai.setdefault("think", None)
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

    tts = validated.get('tts')
    merged_tts = DEFAULT_CONFIG['tts'].copy()
    if isinstance(tts, dict):
        merged_tts.update(tts)
    if type(merged_tts.get('enabled')) is not bool:
        merged_tts['enabled'] = False
    if type(merged_tts.get('warm_on_start')) is not bool:
        merged_tts['warm_on_start'] = False
    if type(merged_tts.get('online_allowed')) is not bool:merged_tts['online_allowed']=False
    if type(merged_tts.get('streaming_prepare')) is not bool:merged_tts['streaming_prepare']=False
    for field in ('model_root', 'python_path', 'edge_python_path', 'voicestudio_python_path'):
        if not isinstance(merged_tts.get(field), str):
            merged_tts[field] = ''
            merged_tts['enabled'] = False
    from therion.voice.providers import EDGE_VOICES, is_voicestudio_endpoint, is_voicestudio_voice
    provider=merged_tts.get('provider')
    if provider=='kokoro':
        if merged_tts.get('voice') not in ('pm_alex','alex_santa_c'):merged_tts['enabled']=False
    elif provider=='edge':
        if (merged_tts['online_allowed'] is not True or merged_tts.get('edge_voice') not in EDGE_VOICES
                or not merged_tts['edge_python_path'].strip()):merged_tts['enabled']=False
    elif provider=='voicestudio':
        if (not is_voicestudio_endpoint(merged_tts.get('voicestudio_endpoint'))
                or not is_voicestudio_voice(merged_tts.get('voicestudio_voice'))
                or not merged_tts['voicestudio_python_path'].strip()):merged_tts['enabled']=False
    else:
        merged_tts['enabled'] = False
    validated['tts'] = merged_tts
    from therion.agent.settings import validate_settings
    validated['agent'] = validate_settings(validated.get('agent'))
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
