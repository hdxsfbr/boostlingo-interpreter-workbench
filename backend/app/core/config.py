"""Runtime configuration.

Secrets come from the environment (a gitignored, chmod-600 `.env` loaded by
Docker Compose); everything else comes from `config/*.yaml` with a few env
overrides. Secrets are `SecretStr` so they never render in reprs or logs.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # Sent as `anthropic-workspace-id` (key is not workspace-scoped). Kept secret-like.
    anthropic_workspace_id: SecretStr | None = None
    # cascade-haiku gate; None = config/app.yaml providers.anthropic.enabled
    anthropic_enabled: bool | None = None
    # Optional; not auto-filled by scripts/setup_env.py (needs Andre's OK to use).
    openrouter_api_key: SecretStr | None = None
    # ElevenLabs is scarce (free tier). Key is read from a file, never from .env (DESIGN §2).
    elevenlabs_api_key_file: Path | None = None
    elevenlabs_enabled: bool = False

    config_dir: Path = REPO_ROOT / "config"
    data_dir: Path = REPO_ROOT / "data"
    static_dir: Path | None = None  # built SPA; served when present

    # Optional env overrides of config/app.yaml
    cascade_stt: str | None = None
    cascade_mt: str | None = None
    cascade_tts: str | None = None
    realtime_model: str | None = None
    mt_model: str | None = None

    def app_config(self) -> dict[str, Any]:
        cfg = yaml.safe_load((self.config_dir / "app.yaml").read_text())
        if self.cascade_stt:
            cfg["cascade"]["stt"] = self.cascade_stt
        if self.cascade_mt:
            cfg["cascade"]["mt"] = self.cascade_mt
        if self.cascade_tts:
            cfg["cascade"]["tts"] = self.cascade_tts
        if self.realtime_model:
            cfg["realtime"]["model"] = self.realtime_model
        if self.mt_model:
            cfg["providers"][cfg["cascade"]["mt"]]["model"] = self.mt_model
        return cfg

    def haiku_enabled(self) -> bool:
        if self.anthropic_enabled is not None:
            return self.anthropic_enabled
        return bool(self.app_config()["providers"].get("anthropic", {}).get("enabled", False))

    def languages(self) -> dict[str, Any]:
        return yaml.safe_load((self.config_dir / "languages.yaml").read_text())

    def provider_status(self) -> dict[str, bool]:
        """Which providers are configured (never reveals values)."""
        el_file = self.elevenlabs_api_key_file
        return {
            "openai": bool(self.openai_api_key and self.openai_api_key.get_secret_value()),
            "anthropic": bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())
            and self.haiku_enabled(),
            "openrouter": bool(self.openrouter_api_key and self.openrouter_api_key.get_secret_value()),
            "elevenlabs": bool(self.elevenlabs_enabled and el_file and Path(el_file).is_file()),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
