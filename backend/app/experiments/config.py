"""Experiment configuration, setups and the pre-run estimate (DESIGN A13).

A setup is one of the M5 profiles, mapped to the *existing* harness flags
(eval/harness.py) and to the cost makeup in eval/metrics.py PROFILES.

Estimate = selected source minutes (voiced speech per utterance, measured in
M5 and stored in the raw rows) x passes x that profile's M5 cost per minute
(priced with config/pricing.yaml). Duration uses the M5 wall-clock / speech
ratio per profile plus a fixed session start-up.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import REPO_ROOT


@dataclass(frozen=True)
class Setup:
    name: str
    label: str
    mode: str
    args: tuple[str, ...]
    models: dict[str, str]
    warning: str = ""
    needs: str = ""  # provider that must be ready: openrouter | elevenlabs
    tags: tuple[str, ...] = field(default_factory=tuple)


SETUPS: dict[str, Setup] = {s.name: s for s in (
    Setup("realtime-mini", "Realtime, gpt-realtime-mini (suggested)", "realtime",
          ("--mode", "realtime", "--rt", "webrtc", "--rt-model", "gpt-realtime-mini"),
          {"realtime": "gpt-realtime-mini", "transcription": "gpt-4o-transcribe"}),
    Setup("realtime", "Realtime, gpt-realtime (full)", "realtime",
          ("--mode", "realtime", "--rt", "webrtc", "--rt-model", "gpt-realtime"),
          {"realtime": "gpt-realtime", "transcription": "gpt-4o-transcribe"},
          warning="gpt-realtime costs about 3.4x more per minute than gpt-realtime-mini (M5: $0.18 vs $0.05). "
                  "Use mini unless you need the final-quality model."),
    Setup("cascade-openai", "Cascade, OpenAI (STT, gpt-5.4-nano, mini-tts)", "cascade",
          ("--mode", "cascade", "--mt", "openai", "--tts", "openai"),
          {"stt": "gpt-live-transcribe", "mt": "gpt-5.4-nano", "tts": "gpt-4o-mini-tts"}),
    Setup("cascade-haiku", "Cascade, Haiku via OpenRouter", "cascade",
          ("--mode", "cascade", "--mt", "openrouter", "--tts", "openai"),
          {"stt": "gpt-live-transcribe", "mt": "anthropic/claude-haiku-5.5", "tts": "gpt-4o-mini-tts"},
          needs="openrouter"),
    Setup("cascade-elevenlabs", "Cascade, ElevenLabs voice", "cascade",
          ("--mode", "cascade", "--mt", "openai", "--tts", "elevenlabs", "--allow-elevenlabs"),
          {"stt": "gpt-live-transcribe", "mt": "gpt-5.4-nano", "tts": "eleven_flash_v2_5"},
          warning="Spends scarce ElevenLabs free-tier credits; the credit guard refuses runs over the caps.",
          needs="elevenlabs"),
)}

STARTUP_S = 12.0  # browser + session start per setup


@lru_cache
def utterances(root: Path = REPO_ROOT) -> dict[str, dict]:
    data = yaml.safe_load((root / "docs" / "benchmarks" / "utterances.yaml").read_text())
    return {u["id"]: {**u, "lang": lang} for lang in ("en", "es") for u in data[lang]}


@lru_cache
def m5_profile_stats(bench_dir: Path) -> dict:
    """Per profile: $/min (results.json) and wall/speech ratio; per id: voiced seconds (raw rows)."""
    res = json.loads((bench_dir / "results" / "m5" / "results.json").read_text())
    out: dict = {"profiles": {}, "speech_s": {}}
    for p in res["profiles"]:
        name = p["profile"]
        ratio = 2.6
        raw = bench_dir / "results" / "m5" / "raw" / f"{name}.jsonl"
        if raw.is_file():
            rows = [json.loads(x) for x in raw.read_text().splitlines() if x.strip()]
            sp = sum(r.get("speech_s") or 0 for r in rows)
            if sp and rows:
                ratio = max(r.get("t_s") or 0 for r in rows) / sp
            for r in rows:
                if r.get("speech_s"):
                    out["speech_s"].setdefault(r["id"], r["speech_s"])
        out["profiles"][name] = {"usd_per_min": p["cost"]["usd_per_min"], "wall_per_speech_s": round(ratio, 2),
                                 "pricing_as_of": p["cost"].get("pricing_as_of")}
    return out


ID_RE = re.compile(r"^(en|es)-[slm]\d{2}$")


class ExperimentConfig(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    setups: list[str] = Field(min_length=1, max_length=len(SETUPS))
    utterances: Literal["full", "short", "custom"] = "short"
    ids: list[str] = Field(default_factory=list, max_length=48)
    directions: Literal["both", "en", "es"] = "both"
    passes: int = Field(default=1, ge=1, le=5)
    allow_elevenlabs: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("name is empty")
        return v

    @field_validator("setups")
    @classmethod
    def _setups(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in SETUPS]
        if unknown:
            raise ValueError(f"unknown setup(s) {unknown}; choose from {sorted(SETUPS)}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate setups")
        return v

    @model_validator(mode="after")
    def _rules(self) -> ExperimentConfig:
        if "cascade-elevenlabs" in self.setups and not self.allow_elevenlabs:
            raise ValueError("cascade-elevenlabs needs allow_elevenlabs=true (scarce free-tier credits)")
        if self.utterances == "custom":
            bad = [i for i in self.ids if not ID_RE.match(i) or i not in utterances()]
            if bad or not self.ids:
                raise ValueError(f"custom subset needs known utterance ids (bad: {bad[:5]})")
        elif self.ids:
            raise ValueError("ids are only used with utterances='custom'")
        if not self.selected():
            raise ValueError("the selection is empty (check directions vs custom ids)")
        return self

    def selected(self) -> list[str]:
        """Utterance ids in utterances.yaml order, filtered by set and direction."""
        langs = {"both": ("en", "es"), "en": ("en",), "es": ("es",)}[self.directions]
        out = []
        for uid, u in utterances().items():
            if u["lang"] not in langs:
                continue
            if self.utterances == "short" and u["size"] != "short":
                continue
            if self.utterances == "custom" and uid not in self.ids:
                continue
            out.append(uid)
        return out


def estimate(cfg: ExperimentConfig, bench_dir: Path) -> dict:
    st = m5_profile_stats(bench_dir)
    ids = cfg.selected()
    utt = utterances()
    speech = sum(st["speech_s"].get(i) or len(utt[i]["text"]) / 14 for i in ids)  # ~14 chars/s if unmeasured
    per = []
    for s in cfg.setups:
        p = st["profiles"].get(s, {})
        mins = speech * cfg.passes / 60
        usd = (p.get("usd_per_min") or 0) * mins
        dur = STARTUP_S + speech * cfg.passes * p.get("wall_per_speech_s", 2.6)
        row = {"setup": s, "utterances": len(ids) * cfg.passes, "source_min": round(mins, 2),
               "usd_per_min": p.get("usd_per_min"), "usd": round(usd, 4), "duration_s": round(dur)}
        if s == "cascade-elevenlabs":
            row["elevenlabs_chars"] = round(sum(len(utt[i]["reference_translation"]) for i in ids) * cfg.passes * 1.25)
        per.append(row)
    return {"turns": len(ids) * cfg.passes * len(cfg.setups), "per_setup": per,
            "usd": round(sum(r["usd"] for r in per), 4), "duration_s": sum(r["duration_s"] for r in per),
            "pricing_as_of": next(iter(st["profiles"].values()), {}).get("pricing_as_of"),
            "basis": "M5 measured $/min (config/pricing.yaml) x selected voiced minutes x passes"}
