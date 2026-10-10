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
    elevenlabs_api_key: SecretStr | None = None  # hosted (Railway variable); the file secret wins when both are set
    elevenlabs_enabled: bool = False

    # A20 Langfuse tracing (off by default; None = config/app.yaml observability.langfuse)
    langfuse_enabled: bool | None = None
    langfuse_host: str | None = None
    langfuse_send_text: bool | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_public_key_file: Path | None = None
    langfuse_secret_key_file: Path | None = None
    git_commit: str = "unknown"

    config_dir: Path = REPO_ROOT / "config"
    data_dir: Path = REPO_ROOT / "data"
    static_dir: Path | None = None  # built SPA; served when present
    # A12 Review tab: blind set (blind/) and M5 results (results/m5/results.json)
    bench_dir: Path = REPO_ROOT / "docs" / "benchmarks"

    # Optional env overrides of config/app.yaml
    cascade_stt: str | None = None
    cascade_mt: str | None = None
    cascade_tts: str | None = None
    realtime_model: str | None = None
    mt_model: str | None = None
    # M4 latency-tuning overrides (A/B runs without editing app.yaml)
    stt_delay: str | None = None
    cascade_speculative: bool | None = None
    cascade_merge_fragments: bool | None = None
    # A11: opt-in session recording (None = config/app.yaml recording.enabled)
    recording_enabled: bool | None = None
    chunk_first_clause_min: int | None = None
    chunk_first_word_min: int | None = None

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
        if self.stt_delay:
            cfg["providers"]["openai_live"]["delay"] = None if self.stt_delay == "none" else self.stt_delay
        if self.cascade_speculative is not None:
            cfg["cascade"]["speculative_mt"] = self.cascade_speculative
        if self.cascade_merge_fragments is not None:
            cfg["cascade"]["merge_fragments"] = self.cascade_merge_fragments
        chunker = cfg["cascade"].setdefault("chunker", {})
        if self.chunk_first_clause_min is not None:
            chunker["first_clause_min"] = self.chunk_first_clause_min
        if self.chunk_first_word_min is not None:
            chunker["first_word_min"] = self.chunk_first_word_min or None
        return cfg

    def haiku_enabled(self) -> bool:
        if self.anthropic_enabled is not None:
            return self.anthropic_enabled
        return bool(self.app_config()["providers"].get("anthropic", {}).get("enabled", False))

    def swap_options(self) -> dict[str, list[dict]]:
        """Cascade providers selectable per session (FR-9), with readiness and why not."""
        st = self.provider_status()
        key = bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

        def opt(name: str, ready: bool, reason: str = "") -> dict:
            return {"name": name, "ready": ready, "reason": "" if ready else reason}
        cfg = self.app_config()["providers"]
        return {
            "mt": [opt("openai", st["openai"], "OPENAI_API_KEY missing") | {"model": cfg["openai"]["model"]},
                   opt("anthropic", st["anthropic"], "Anthropic key missing" if not key else
                       "disabled: validity check failed (see AGENTS.md)") | {"model": cfg["anthropic"]["model"]},
                   opt("openrouter", st["openrouter"], "OPENROUTER_API_KEY not set")
                   | {"model": cfg.get("openrouter", {}).get("model", "")}],
            "tts": [opt("openai", st["openai"], "OPENAI_API_KEY missing") | {"model": cfg["openai_tts"]["model"]},
                    opt("elevenlabs", st["elevenlabs"], "disabled to save free-tier credits (ELEVENLABS_ENABLED=0)")
                    | {"model": cfg["elevenlabs"]["model"]}],
        }

    def languages(self) -> dict[str, Any]:
        return yaml.safe_load((self.config_dir / "languages.yaml").read_text())

    def provider_status(self) -> dict[str, bool]:
        """Which providers are configured (never reveals values)."""
        return {
            "openai": bool(self.openai_api_key and self.openai_api_key.get_secret_value()),
            "anthropic": bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value())
            and self.haiku_enabled(),
            "openrouter": bool(self.openrouter_api_key and self.openrouter_api_key.get_secret_value()),
            "elevenlabs": bool(self.elevenlabs_enabled and self.elevenlabs_key()),
        }

    def elevenlabs_key(self) -> str:
        f = self.elevenlabs_api_key_file
        try:
            key = Path(f).read_text().strip() if f else ""
        except OSError:
            key = ""
        return key or (self.elevenlabs_api_key.get_secret_value() if self.elevenlabs_api_key else "")

    def langfuse_config(self):
        from app.observability.client import LangfuseConfig

        def secret(v: SecretStr | None, f: Path | None) -> str:
            try:
                key = Path(f).read_text().strip() if f else ""
            except OSError:
                key = ""
            return key or (v.get_secret_value() if v else "")
        c = (self.app_config().get("observability") or {}).get("langfuse") or {}
        pick = lambda env, k, d: env if env is not None else c.get(k, d)
        return LangfuseConfig(
            enabled=bool(pick(self.langfuse_enabled, "enabled", False)),
            host=str(pick(self.langfuse_host, "host", "https://us.cloud.langfuse.com")),
            public_key=secret(self.langfuse_public_key, self.langfuse_public_key_file),
            secret_key=secret(self.langfuse_secret_key, self.langfuse_secret_key_file),
            # hosted (Railway sets PORT / RAILWAY_*): transcripts off unless LANGFUSE_SEND_TEXT says otherwise
            send_text=bool(self.langfuse_send_text if self.langfuse_send_text is not None
                           else (False if hosted() else c.get("send_text", True))),
            retention_days=int(c.get("retention_days", 0) or 0),
            flush_interval_s=float(c.get("flush_interval_s", 2.0)), max_batch=int(c.get("max_batch", 50)),
            max_queue=int(c.get("max_queue", 2000)), timeout_s=float(c.get("timeout_s", 3.0)),
            release=self.git_commit, project_id=str(c.get("project_id", "")))


def hosted() -> bool:
    import os
    # PORT is set by the platform (our compose file does not set it); RAILWAY_HOME alone is just the CLI
    return "PORT" in os.environ or any(k in os.environ for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
