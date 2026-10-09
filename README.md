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
| Comparison write-up (must-have #8) | done: [`docs/comparison.md`](docs/comparison.md) (blind human ratings pending) |

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

URL options: `?mode=realtime`, `?rt=webrtc|relay|auto` (default `auto`: WebRTC, falling back to the relay), `?turn=vad` (VAD instead of PTT; `vad_ms=` sets the window), `?mt=openrouter`, `?tts=elevenlabs`.

Other targets: `make test` (backend pytest + frontend Vitest/tsc, no keys or network needed), `make test-docker` (both suites inside Docker with `--network none`), `make logs`, `make down`, `make dev-backend` / `make dev-frontend` (Vite dev server with proxy on :5180), `make fixtures` (benchmark audio).

### Benchmarks

```bash
cd backend && uv pip install -e '.[eval]' && playwright install chromium     # or use /usr/bin/google-chrome
python -m eval.harness --mode cascade --profile cascade-openai --record ../data/m5/audio/cascade-openai --out run.jsonl
python -m eval.harness --mode realtime --profile realtime --out rt.jsonl        # app started with REALTIME_MODEL=gpt-realtime
python -m eval.metrics --run cascade-openai=run.jsonl --run realtime=rt.jsonl --judge --roundtrip --out-dir out/
python -m eval.blind --run ... --ids en-s01,... --out out/blind                  # blind-rating kit
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
- `docs/PRD.md` requirements · `docs/DESIGN.md` approved design · `docs/api-research.md` provider research
- `AGENTS.md` how the coding agent was directed
- `sources/assignment.pdf` the authoritative brief
