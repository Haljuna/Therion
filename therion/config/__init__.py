"""Módulo de configuração local do Therion."""

from .local import load_config, save_config, DEFAULT_CONFIG
from .alias_manager import AliasManager, AliasResult

__all__ = ["load_config", "save_config", "DEFAULT_CONFIG", "AliasManager", "AliasResult"]