# AI Interpreter Workbench: Realtime API vs Cascade Pipeline

A Gauntlet partner project for **Boostlingo**. A browser workbench that interprets a live English ↔ Spanish conversation through two architectures and measures them the same way:
- **Realtime mode:** OpenAI Realtime API (`gpt-realtime`; `gpt-realtime-mini` in dev), voice-to-voice over browser WebRTC with an ephemeral secret minted by the backend.
- **Cascade mode:** a streaming STT → Translation → TTS pipeline in FastAPI with swappable providers (`gpt-live-transcribe` → small OpenAI LLM → `gpt-4o-mini-tts`; Haiku / ElevenLabs as swaps).

Latency is measured **in the browser, on one clock**, from the last voiced microphone frame to the first audible output sample, identically in both modes.

## Status (due Sun 2026-10-11)

| Milestone | State |
|---|---|
| M0 skeleton, audio I/O, contract, cascade WS loopback | done |
| M1 cascade pipeline with OpenAI adapters, waterfall, stats, export | done |
| M2 Realtime mode: WebRTC (ephemeral secret) + WS relay fallback, PTT + server VAD, pruning, mode switch | done |
| M3 provider swaps: Haiku (via OpenRouter), ElevenLabs TTS + credit guard, per-session selector | done ([swaps](docs/provider-swaps.md)) |
| M4 harness, fixtures, cascade tuning (speculative MT), VAD sweep, 5-min soak | done ([M4 results](docs/benchmarks/m4-tuning.md)) |
| M5 hedged first output, fragment merge, error-state pass, final benchmark matrix, README, AGENTS.md | done ([summary](docs/benchmarks/results/m5/summary.md), [results.json](docs/benchmarks/results/m5/results.json)) |
| Comparison write-up (must-have #8) | done: [`docs/comparison.md`](docs/comparison.md) (2-page write-up) + [`docs/comparison-details.md`](docs/comparison-details.md) (method, full numbers); blind human ratings done (1 rater): [`docs/benchmarks/blind/results.md`](docs/benchmarks/blind/results.md) |

## Run it (runbook)

**On hdx-lab** (Docker + Compose v2, Python 3 on the host), from the repo root:

```bash
make up        # one setup command: writes .env (chmod 600) from ~/.config/agentforge, builds, starts, waits for /healthz
```

`make up` prints only "set"/"missing" for each key. The app listens on `127.0.0.1:8740` only.

**On the Mac**, open an SSH port-forward and the app:

```bash
ssh -N -L 8740:127.0.0.1:8740 hdx-lab     # keep this running
open http://localhost:8740
```

`http://localhost` is a secure context, so microphone access and WebRTC work without certificates. Use **headphones**; the mic is also muted while a translation plays.

**ElevenLabs for the demo (optional, uses free-tier credits):**

```bash
ELEVENLABS_ENABLED=1 ELEVENLABS_KEY_PATH=~/.config/agentforge/elevenlabs_api_key make up
```

The key is mounted as a file secret, never put in `.env`. The guard refuses past 1,500 chars per session and 8,000 per month, based on the ledger in `data/elevenlabs_ledger.json`. Plain `make up` turns it off again.

**Final-quality Realtime model for the demo:** `REALTIME_MODEL=gpt-realtime make up`. The default is `gpt-realtime-mini`.

### Demo steps (about 5 minutes)

1. Open `http://localhost:8740`. Pick **Cascade** and press **Start session**. If the mic is blocked, a banner explains the fix and offers a Retry button.
2. Hold **Speaker A** (EN→ES, key `F`), say "Do you have any allergies?", release. Watch the source transcript stream, the translation, then the audio. The waterfall shows STT final → MT first token → TTS first byte → first audible sample, and **H** (speech end → first audio).
3. Hold **Speaker B** (ES→EN, key `J`), say "Me duele mucho la cabeza desde ayer." Then try a long multi-sentence turn: the first sentence plays while you are still finishing (pipelining).
4. Switch to **Realtime** mid-session. The history stays and a switch marker appears. Repeat both directions and compare H in the stats panel (p50/p90 per mode).
5. Optional: change the translator to **OpenRouter (Haiku)** or the TTS to **ElevenLabs** in the provider selector. If a provider is disabled you get one clear banner.
6. Press a speaker button while a translation plays to barge in. **Export JSON / CSV** downloads the session's turns and latencies.
7. Open the **Review** tab, enter a name and rate a few blind clips with the keyboard, or open Results as `andre` (see "Review tab" below).

URL options: `?mode=realtime`, `?rt=webrtc|relay|auto` (default `auto`: WebRTC, falling back to the relay), `?turn=vad` (VAD instead of PTT; `vad_ms=` sets the window), `?mt=openrouter`, `?tts=elevenlabs`.

Other targets: `make test` (backend pytest + frontend Vitest/tsc, no keys or network needed), `make test-docker` (both suites inside Docker with `--network none`), `make logs`, `make down`, `make dev-backend` / `make dev-frontend` (Vite dev server with proxy on :5180), `make fixtures` (benchmark audio).

### Benchmarks

```bash
cd backend && uv pip install -e '.[eval]' && playwright install chromium     # or use /usr/bin/google-chrome
python -m eval.harness --mode cascade --profile cascade-openai --record ../data/m5/audio/cascade-openai --out run.jsonl
python -m eval.harness --mode realtime --profile realtime --out rt.jsonl        # app started with REALTIME_MODEL=gpt-realtime
python -m eval.metrics --run cascade-openai=run.jsonl --run realtime=rt.jsonl --judge --roundtrip --out-dir out/
python -m eval.blind --run ... --ids en-s01,... --out out/blind                  # blind-rating kit
python -m eval.blind_results                                                      # analyse the filled rating sheet
python -m eval.error_pass                                                         # error-state pass (no provider calls)
```

Final M5 results: [`docs/benchmarks/results/m5/summary.md`](docs/benchmarks/results/m5/summary.md) (matrix), `results.json` + per-utterance CSVs next to it, raw runs in `raw/`, blind-rating kit in [`docs/benchmarks/blind/`](docs/benchmarks/blind/README.md).

The harness drives the real SPA in headless Chrome and plays each fixture as the microphone (`?source=file`). It releases PTT 450 ms after the last voiced frame and also reports every number minus that gap. `--tts elevenlabs` refuses to run without `--allow-elevenlabs`, and it aborts before any call if the estimated characters exceed the cap or the remaining allowance.

## Error states (DESIGN §6)

| Case | What the user sees | Verified by |
|---|---|---|
| Mic denied / missing / timeout | blocking banner with the fix + Retry | `eval/error_pass.py` (browser) |
| Insecure context | banner pointing to `localhost` | `eval/error_pass.py` |
| Rate limit (429) | retry before first byte with backoff, then a stage-labelled failed turn; session continues | `tests/unit/test_retry_errors.py`, `test_cascade_session.py` |
| Timeout / slow provider | hedged backup request at 1.5 s; failed turn at 3 s (STT/MT/TTS) or 20 s (turn) | `test_hedge.py`, `test_cascade_session.py` |
| Empty transcript / translation / silent turn | turn skipped, no MT/TTS | `test_cascade_session.py`, `eval/error_pass.py` |
| Provider disconnect | failed turn, reconnect for the next turn | `test_cascade_ws_*`, `test_realtime_relay.py` |
| ElevenLabs disabled / over budget | one banner "switch TTS to OpenAI"; refused before any call | `test_budget.py`, `eval/error_pass.py` |

Results of the last browser pass: [`docs/benchmarks/results/m5/error_pass.txt`](docs/benchmarks/results/m5/error_pass.txt).

## Session recording (opt-in, for audit; DESIGN A11)

- **Off by default.** Enable it on the server with `recording.enabled: true` in `config/app.yaml` or `RECORDING_ENABLED=1` in `.env`, then `make up`. Then tick **Record session** before starting a session. The UI shows a consent notice and a red "● Recording" indicator while the session runs. With the server flag off, the toggle is disabled and the server refuses recordings: the cascade gets a `recording_refused` banner and Realtime uploads get 403.
- **What is saved:** both sides of every turn, in both modes, at `data/recordings/<session_id>/turn-<n>-{source,target}.<ext>`, next to `data/sessions/<session_id>.jsonl`. The turn records reference the paths, and each saved file adds an audit line.
  - Cascade: WAV (24 kHz mono), captured on the server: inbound mic PCM and the TTS output.
  - Realtime (WebRTC or relay): webm/opus recorded in the browser (mic track, and the output the listener hears), uploaded per turn to `POST /api/recordings/<sid>/turns/<n>/{source|target}`.
- **Retention:** `recording.retention_days` (default 30), swept at startup and every 6 h. Delete one session's audio now with `curl -X DELETE http://127.0.0.1:8740/api/recordings/<session_id>`.
- **Turn boundaries in Realtime are approximate.** Source runs from turn start to the end of speech (+200 ms). Target runs from turn start to the end of playback (+500 ms tail), so it begins with the listener's silence while the speaker talks. A barge-in cuts the old turn's target short. In VAD mode the turn starts when OpenAI's VAD fires, so the first ~100–300 ms of speech can be missing from the source file.
- **Local demo only.** `data/recordings/` is gitignored and never leaves the machine. **Production would need encryption at rest, access control on the recording endpoints (today anyone who can reach the port can upload or delete), access logging, and a per-participant consent record.**

## Review tab: human quality ratings (DESIGN A12)

Open the **Review** tab (or `http://localhost:8740/?tab=review`) and enter your name. There is no login; ratings are stored under that name in `data/review.sqlite3`.

- **Blind benchmark set** (`M5 blind benchmark`, 48 clips):
  - Press **Start/Resume**. Each clip shows the direction, what the speaker said and the reference translation. It autoplays.
  - Score **Accuracy**, **Fluency** and **Voice** from 1 to 5, add optional notes, then **Save & next**.
  - Keys: `1`–`5` score the highlighted row and move down, `Tab` cycles rows, `Space` plays or pauses, `Enter` saves and moves on.
  - You resume at the first clip you haven't fully scored. If a save fails, a red message says so and your scores stay on screen.
  - The setup names stay hidden from the page and the API until you finish every clip or press **Reveal variants** in Results. Ratings saved after a reveal are flagged.
- **Recorded sessions:** sessions recorded with "Record session" on (see above) are listed under *Recorded sessions*. **Create review set** turns each turn's translated audio into a clip, shown with its source and target text.
- **Results:** per setup, the mean / median (sd, range) for each scale, overall and per direction, next to that setup's M5 latency (H p50/p90) and chrF. You can show your ratings or pool all raters, and **Export results CSV** / **Export my ratings CSV**.
- **Preloaded:** Andre's 48 completed blind ratings are loaded as rater `andre`. That set opens complete, and its Results match [`docs/benchmarks/blind/results.md`](docs/benchmarks/blind/results.md).
- **Remove a rater's data:** `curl -X DELETE "http://127.0.0.1:8740/api/review/sets/<set_id>/ratings?rater=<name>"`.
- **Headless check** (no provider calls): `cd backend && python -m eval.review_check --url http://127.0.0.1:8740`.

## Experiments tab: run benchmarks from the app (DESIGN A13)

Open the **Experiments** tab (or `http://localhost:8740/?tab=experiments`). It runs the same headless-Chrome harness as the M5 benchmarks, inside the container against the app itself, and keeps every run.

1. **New experiment:** give it a name, then tick one or more setups. The defaults are `realtime-mini` + `cascade-openai`.
   - Ticking `realtime` (full) shows a costs-more warning.
   - `cascade-elevenlabs` needs an extra "I accept spending ElevenLabs credits" tick and only works when ElevenLabs is enabled. `cascade-haiku` needs `OPENROUTER_API_KEY`.
   - Choose the utterances (full 48, short 16, or a custom subset by id), the directions and the number of passes.
2. **Check the estimate:** a table shows turns, voiced minutes, cost and time per setup, based on the measured M5 cost of the same utterances priced with `config/pricing.yaml`. Above `experiments.confirm_above_usd` ($1) you must click **Run anyway**.
3. **Run:** a live panel shows the setup, the utterance being played, done/total, the running H p50, failures and the cost so far. **Cancel** stops the browser and its provider sessions and keeps the partial results. Only one experiment runs at a time.
4. **Results:** click an experiment in **History** to see the M5 summary columns (latency p50/p90 with and without the 450 ms release gap, tail, chrF, source WER, $/min, failures), a per-turn latency chart, the code version and model ids. You can download CSV or JSON. Tick two experiments and press **Compare** for a side-by-side view with deltas. **M5 baseline** (read-only) holds the final M5 numbers.
- API: `POST /api/experiments/estimate` and `POST /api/experiments` take `{"name", "setups", "utterances": "full|short|custom", "ids", "directions": "both|en|es", "passes", "allow_elevenlabs", "confirm"}`.
- Headless check (no provider calls): `docker exec -e HOME=/tmp -w /app/backend boostlingo-interpreter-workbench-app-1 python -m eval.experiments_check --chrome "" --exp <id>`.
- Small samples are noisy. The first 6-utterance smoke read cascade H p50 at 2261 ms because of a slow spell at the TTS provider; reruns, in the app or from the CLI on the host or in the container, gave 1622–1781 ms, matching M5's 1690 ([`docs/benchmarks/results/inapp-slowdown/`](docs/benchmarks/results/inapp-slowdown/summary.md)). Use at least 12 turns per setup (more utterances or passes) before reading differences.

## Configuration and secrets

- `.env` (gitignored, mode 600) holds `OPENAI_API_KEY` and `OPENROUTER_API_KEY` (Haiku runs via OpenRouter). The direct Anthropic adapter is disabled and its key is no longer loaded. `.env.example` lists the variables without values. `scripts/setup_env.py` fills them from key files and prints only "set"/"missing".
- The ElevenLabs key is mounted as a Compose **file secret**, never put in `.env`, and only used when `ELEVENLABS_ENABLED=1` (free tier: tests always mock it). Even then, `core/budget.py` refuses before the call past 1,500 chars/session or 8,000 chars/month (ledger in `data/elevenlabs_ledger.json`).
- Model ids and active providers live in `config/app.yaml` (env overrides `REALTIME_MODEL`, `MT_MODEL`, `CASCADE_STT|MT|TTS`). Providers can also be swapped per session from the UI; see [`docs/provider-swaps.md`](docs/provider-swaps.md). Language pairs live in `config/languages.yaml`.
- Keys never reach the browser: Realtime uses short-lived client secrets; the cascade runs server-side.

## Architecture (short; full design in [`docs/DESIGN.md`](docs/DESIGN.md))

```
Browser (React + TS)                              hdx-lab (Docker, FastAPI)
 mic -> capture worklet (24 kHz PCM16 + VAD) ──┐
 InterpreterSession (one event contract) ──────┤
   CascadeTransport  ── WS /ws/cascade ────────┼──> CascadeSession: STT -> MT -> chunker -> TTS (streams)
   RealtimeTransport ── WebRTC ── OpenAI       │    POST /api/realtime/session (mint ephemeral secret)
   RealtimeRelay     ── WS /ws/realtime ───────┼──> relay to OpenAI Realtime WS (fallback, key server-side)
 playback worklet / remote track -> output tap │    POST /api/turns -> data/sessions/*.jsonl
 UI: transcripts, waterfall, p50/p90, export   │
```

- **Realtime:** OpenAI events from either transport go through one normaliser (`frontend/src/session/normalizers/oaiEvents.ts`). PTT sends `commit` + `response.create` with per-turn direction instructions; VAD uses `server_vad`. Older conversation items are deleted after each response. The uplink is a cloned mic track that is disabled while the model speaks.
- **Mode-agnostic UI:** the UI only consumes `SessionEvent`s from `InterpreterSession`; transports are swappable (`frontend/src/session/`).
- **Provider abstraction:** `STTProvider`, `Translator`, `TTSProvider` Protocols (`backend/app/providers/base.py`); the orchestrator imports only those. A swap is one adapter file + one config value + its contract test.
- **Streaming end to end:** STT partials stream to the UI; translation starts on segment finals and streams tokens; a sentence/clause chunker feeds TTS per chunk; audio is forwarded as it arrives.

### Why Python rather than .NET

The brief prefers .NET/C# but accepts Python. We chose Python/FastAPI because the provider SDKs and examples for streaming audio (OpenAI Realtime/transcription, ElevenLabs WebSockets) and the evaluation tooling (`jiwer`, `sacrebleu`, COMET) are Python-first, which matters for a 3–4 day build whose value is in measurement. The async pipeline (`asyncio` tasks + bounded queues) maps one-to-one onto the C# `Channel<T>` design if Boostlingo wanted to port it.

## Key files

- [`docs/comparison.md`](docs/comparison.md) Realtime vs Cascade write-up (latency, quality, cost, controllability, recommendation)
- [`docs/comparison-details.md`](docs/comparison-details.md) technical companion: method, full metrics, engineering findings, cost breakdown
- [`docs/KEY_METRICS.md`](docs/KEY_METRICS.md) the brief's five metrics: definition, how measured, target, results, status
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) components, data flow, latency measurement points, error handling, config, security posture (with diagrams)
- [`docs/SCALING.md`](docs/SCALING.md) what breaks and what changes at 10 to 100,000 users, with cost formulas
- `docs/PRD.md` requirements · `docs/DESIGN.md` approved design · `docs/api-research.md` provider research
- `AGENTS.md` how the coding agent was directed
- `sources/assignment.pdf` the authoritative brief
