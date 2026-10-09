"""Language pairs from config/languages.yaml (FR-5, DESIGN A14).

The single place that knows language names and which pairs exist. Everything
else (prompts, provider instructions, session defaults, the UI selector, the
Experiments directions) asks this module, so a new pair is a config change.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

CODE = re.compile(r"^[a-z]{2,3}$")


class Language(BaseModel):
    name: str = Field(min_length=1)
    voices: dict[str, str] = Field(default_factory=dict)  # per TTS provider; app.yaml provider voices win


class Pair(BaseModel):
    id: str
    a: str
    b: str
    benchmarked: bool = False
    glossary: dict[str, str] = Field(default_factory=dict)

    @property
    def langs(self) -> list[str]:
        return [self.a, self.b]


class LanguagesConfig(BaseModel):
    languages: dict[str, Language]
    pairs: list[Pair] = Field(min_length=1)
    default_pair: str | None = None

    @field_validator("languages")
    @classmethod
    def _codes(cls, v: dict[str, Language]) -> dict[str, Language]:
        bad = [k for k in v if not CODE.match(k)]
        if bad:
            raise ValueError(f"language codes must be ISO 639 lowercase (bad: {bad})")
        return v

    @model_validator(mode="after")
    def _pairs(self) -> LanguagesConfig:
        ids = [p.id for p in self.pairs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate pair ids: {ids}")
        for p in self.pairs:
            if p.a == p.b:
                raise ValueError(f"pair {p.id}: a and b must differ")
            missing = [c for c in (p.a, p.b) if c not in self.languages]
            if missing:
                raise ValueError(f"pair {p.id}: languages {missing} are not defined under `languages`")
        if self.default_pair is None:
            self.default_pair = self.pairs[0].id
        if self.default_pair not in ids:
            raise ValueError(f"default_pair {self.default_pair!r} is not one of {ids}")
        return self

    # ----- lookups
    def name(self, code: str) -> str:
        lang = self.languages.get(code)
        return lang.name if lang else code

    def pair(self, pair_id: str | None = None) -> Pair:
        pid = pair_id or self.default_pair
        for p in self.pairs:
            if p.id == pid:
                return p
        raise KeyError(f"unknown language pair {pid!r}")

    @property
    def default(self) -> Pair:
        return self.pair(self.default_pair)

    def find(self, a: str, b: str) -> Pair | None:
        """The configured pair for these two languages, in either order."""
        return next((p for p in self.pairs if {p.a, p.b} == {a, b}), None)

    def resolve(self, a: str | None, b: str | None) -> tuple[str, str]:
        """Fill missing codes from the default pair; refuse unconfigured pairs (ValueError)."""
        d = self.default
        a, b = a or d.a, b or d.b
        if not self.find(a, b):
            raise ValueError(f"language pair {a}-{b} is not configured in languages.yaml "
                             f"(configured: {[p.id for p in self.pairs]})")
        return a, b

    def benchmarked(self) -> Pair:
        return next((p for p in self.pairs if p.benchmarked), self.default)

    def public(self) -> dict:
        return {"default_pair": self.default_pair,
                "languages": {k: {"name": v.name} for k, v in self.languages.items()},
                "pairs": [{"id": p.id, "a": p.a, "b": p.b, "benchmarked": p.benchmarked,
                           "label": f"{self.name(p.a)} ↔ {self.name(p.b)}"} for p in self.pairs]}


def load_languages(path: Path) -> LanguagesConfig:
    return LanguagesConfig.model_validate(yaml.safe_load(path.read_text()) or {})


@lru_cache(maxsize=8)
def _cached(path: str, mtime: float) -> LanguagesConfig:
    return load_languages(Path(path))


def languages_config() -> LanguagesConfig:
    from app.core.config import get_settings
    p = get_settings().config_dir / "languages.yaml"
    return _cached(str(p), p.stat().st_mtime)


def lang_name(code: str) -> str:
    return languages_config().name(code)
