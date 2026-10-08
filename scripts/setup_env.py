#!/usr/bin/env python3
"""Create/refresh the gitignored .env (mode 600) from .env.example, filling
secrets from key files (default ~/.config/agentforge). Prints only which
variables are set or missing - never values."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYDIR = Path(os.environ.get("AGENTFORGE_KEYS", Path.home() / ".config" / "agentforge"))
FROM_FILES = {"OPENAI_API_KEY": "openai_api_key", "ANTHROPIC_API_KEY": "anthropic_api_key"}
REQUIRED = {"OPENAI_API_KEY"}


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> int:
    example = (ROOT / ".env.example").read_text().splitlines()
    current = parse(ROOT / ".env")
    values: dict[str, str] = {}
    for var, fname in FROM_FILES.items():
        if current.get(var):
            values[var] = current[var]
        elif (KEYDIR / fname).is_file():
            values[var] = (KEYDIR / fname).read_text().strip()
    el = KEYDIR / "elevenlabs_api_key"
    values["ELEVENLABS_KEY_PATH"] = current.get("ELEVENLABS_KEY_PATH") or (str(el) if el.is_file() else "/dev/null")

    lines, seen = [], set()
    for line in example:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key:
            seen.add(key)
            val = values.get(key, current.get(key, line.split("=", 1)[1].strip()))
            lines.append(f"{key}={val}")
        else:
            lines.append(line)
    for k, v in current.items():  # keep user additions
        if k not in seen:
            lines.append(f"{k}={v}")

    env = ROOT / ".env"
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(env, 0o600)

    final = parse(env)
    missing = []
    for var in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_KEY_PATH"]:
        ok = bool(final.get(var)) and final.get(var) != "/dev/null"
        print(f"  {var:22s} {'set' if ok else 'MISSING' + (' (required)' if var in REQUIRED else ' (optional)')}")
        if not ok and var in REQUIRED:
            missing.append(var)
    if missing:
        print(f".env written but required keys are missing: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(".env ready (mode 600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
