# QA evidence pack: gap fixes (ab2c87e)

Tested on hdx-lab, main at `a32179ae70da0558e8e624c363941cb853a85db2` (includes ab2c87e), on 2026-10-10 at 14:16–14:18 PT.
The Docker app was rebuilt from that commit (`docker compose up -d --build`) before testing.

## What's here
| File | What it shows |
|---|---|
| live-tests.txt | Raw, unedited output of the opt-in live provider tests |
| healthz.json | Response of `GET http://localhost:8740/healthz` from the rebuilt app |
| pair-dropdown-closed.png | Interpreter tab, Language pair dropdown closed (default English ↔ Spanish) |
| pair-dropdown-open.png | Same dropdown showing both options: en-es and en-fr |
| pair-dropdown-en-fr-selected.png | After selecting en-fr; speaker labels switch to EN/FR |
| realtime-model.txt | Realtime session-mint requests and responses (secrets redacted): default gives gpt-realtime, ?rt_model=gpt-realtime-mini gives gpt-realtime-mini |
| pair-dropdown-locked-live.png | Realtime session live (status "ready · realtime", Stop session shown); Language pair dropdown is disabled |
| shot_live.py | Script for the two items above |

## Commands run
```
git checkout main && git pull --ff-only
docker compose up -d --build
cd backend && set -a && source ../.env && set +a
ELEVENLABS_API_KEY_FILE=~/.config/agentforge/elevenlabs_api_key LIVE_TESTS=1 .venv/bin/pytest -m live tests/live -v -rs
curl -s localhost:8740/healthz
python /tmp/shot.py   # headless Chromium via Playwright, viewport 1400x900
```

## Results: 6 passed, 0 failed, 0 skipped (11.6 s)
| Test | Result |
|---|---|
| test_openai_stt_live | PASS |
| test_openai_mt_live (gpt-5.4-nano) | PASS |
| test_openai_tts_live (gpt-4o-mini-tts) | PASS |
| test_realtime_session_mint_live | PASS |
| test_openrouter_mt_live (claude-haiku-5.5) | PASS |
| test_elevenlabs_tts_live_through_credit_guard | PASS (5-character text through the ElevenLabsBudget guard) |

One harmless warning: a Starlette deprecation notice about httpx in the test client.

/healthz returned `{"status": "ok"}` (HTTP 200).

## Screenshot note
Headless Chromium can't capture a native `<select>`'s open popup, so for pair-dropdown-open.png a small overlay listing the select's real options (text and value read from the DOM) was drawn under the control. The closed and en-fr-selected shots are unmodified.

## Approximate cost
Under $0.05 total: a few seconds of OpenAI transcription, one short nano translation, one short TTS clip, one Realtime session mint (no audio), one short Haiku call via OpenRouter, and about 5 ElevenLabs characters.

## Addendum (2026-10-10, 14:20–14:23 PT, same SHA, requested by QA Lead)
- **Default Realtime model:** starting a Realtime session from the UI with default settings sends no model, and the server's mint response says `"model":"gpt-realtime"` (from `config/app.yaml` → `realtime.model: gpt-realtime`). With `?rt_model=gpt-realtime-mini` the UI sends `"model":"gpt-realtime-mini"` and the response confirms it. The server access log only shows `POST /api/realtime/session 200`; it doesn't log the model, so the mint response is the proof.
- **Pair locked during a live session:** in both sessions `pair-select` reported `disabled = true` while running. The screenshot was taken once the status read "ready · realtime". The browser used a fake mic, nobody spoke, and each session was stopped within about 2 s.
- **Cost:** about 4 Realtime client-secret mints (2 runs × 2 sessions; the first screenshot attempt caught the "connecting" state and was redone) plus a few seconds of connected sessions with no speech. Effectively under \$0.01.
