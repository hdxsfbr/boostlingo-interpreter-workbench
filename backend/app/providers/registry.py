"""Name -> factory registry. A provider swap = one adapter file (decorated
with @register) + one config value (config/app.yaml or CASCADE_* env)."""
from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from app.core.errors import ConfigError

_REGISTRY: dict[tuple[str, str], Callable[..., Any]] = {}

# Adapter modules imported lazily so optional providers need no deps/keys.
_MODULES = {
    ("stt", "openai_live"): "app.providers.stt.openai_live",
    ("mt", "openai"): "app.providers.mt.openai",
    ("tts", "openai"): "app.providers.tts.openai",
    ("stt", "fake"): "app.providers.fakes",
    ("mt", "fake"): "app.providers.fakes",
    ("tts", "fake"): "app.providers.fakes",
}


def register(kind: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(factory: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[(kind, name)] = factory
        return factory

    return deco


def create(kind: str, name: str, **kwargs: Any) -> Any:
    key = (kind, name)
    if key not in _REGISTRY and key in _MODULES:
        importlib.import_module(_MODULES[key])
    if key not in _REGISTRY:
        raise ConfigError(f"unknown {kind} provider '{name}'", stage=kind)
    return _REGISTRY[key](**kwargs)


def available() -> list[tuple[str, str]]:
    return sorted(set(_REGISTRY) | set(_MODULES))
