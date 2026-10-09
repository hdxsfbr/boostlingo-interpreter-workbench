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
| M2 Realtime mode: WebRTC (ephemeral secret) + WS relay fallback, PTT + server VAD, pruning, mode switch | done ([smoke results](docs/benchmarks/m2-realtime-smoke.md): PTT H p50 0.95–1.04 s, both directions) |
| M3 provider swaps (Haiku, ElevenLabs + budget guard, OpenRouter) | planned |
| M4 benchmark harness, soak, final `gpt-realtime` runs | planned |
| M5 error pass, README, AGENTS.md, comparison write-up | planned |

## Run it (hdx-lab)

```bash
make up        # writes .env (chmod 600) from ~/.config/agentforge, builds, starts, waits for /healthz
```

Then on the Mac:

```bash
ssh -N -L 8740:127.0.0.1:8740 hdx-lab
open http://localhost:8740
```

`http://localhost` is a secure context, so microphone access and WebRTC work without certificates. Use **headphones**; the mic is also muted while a translation plays.

Using it: pick **Cascade** or **Realtime**, **Start session**, then hold **Speaker A** (EN→ES, key `F`) or **Speaker B** (ES→EN, key `J`) while talking and release when done. Pressing a speaker button during playback interrupts it. The *Loopback* pipeline echoes your turn back and shows the transport + playout floor. In Realtime, **Auto (VAD)** lets the model detect turns (no buttons). URL options: `?mode=realtime`, `?rt=webrtc|relay|auto` (default `auto`: WebRTC, falling back to the relay), `?turn=vad`.

Other targets: `make test` (backend pytest + frontend Vitest/tsc, no keys or network needed), `make test-docker` (both suites inside Docker with `--network none`), `make logs`, `make down`, `make dev-backend` / `make dev-frontend` (Vite dev server with proxy on :5180).

## Configuration and secrets

- `.env` (gitignored, mode 600) holds `OPENAI_API_KEY` and optional `ANTHROPIC_API_KEY`. `.env.example` lists the variables without values. `scripts/setup_env.py` fills them from key files and prints only "set"/"missing".
- The ElevenLabs key is mounted as a Compose **file secret**, never put in `.env`, and only used when `ELEVENLABS_ENABLED=1` (free tier: tests always mock it).
- Model ids and active providers live in `config/app.yaml` (env overrides `REALTIME_MODEL`, `MT_MODEL`, `CASCADE_STT|MT|TTS`). Language pairs live in `config/languages.yaml`.
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

- `docs/PRD.md` requirements · `docs/DESIGN.md` approved design · `docs/api-research.md` provider research
- `AGENTS.md` how the coding agent was directed
- `sources/assignment.pdf` the authoritative brief
