# AGENTS.md: how the coding agent was directed

This repo is built by an agentic coding assistant (Grok Bot executor agents) directed by Andre Batista, with a coordinating "Butler" agent relaying Andre's decisions. This file records the conventions, the task breakdown, the constraints the agent works under, and what it got wrong and how that was corrected. It is updated at every milestone.

## Roles and flow

1. **Planning (before code):** an agent synthesised `docs/PRD.md` from the brief, a research agent produced `docs/api-research.md` (current model names, endpoints, prices, with sources), and a design agent wrote `docs/DESIGN.md`. Andre reviewed and approved DESIGN v0.2, including decisions D1–D10.
2. **Build kickoff:** Butler relayed the approved defaults; the build agent then works milestone by milestone (M0 → M5 in DESIGN §10), stops at the requested milestone and reports what works, how it was verified, commit hashes, deviations and blockers.
3. **Review:** Andre/Butler review each milestone report before the next run starts.

## Standing instructions given to the agent

- **Stack (fixed by Andre):** Python/FastAPI backend, TypeScript (React + Vite) frontend, Docker Compose on `hdx-lab`, one setup command (`make up`), local only, opened from the Mac via SSH port-forward to `localhost`.
- **Where to work:** directly on `hdx-lab` in `~/code/boostlingo-interpreter-workbench`; no clones elsewhere. Never `pkill -f` broadly (the lab runs other agents and services); only kill PIDs the agent started.
- **Realtime:** browser WebRTC straight to OpenAI with a FastAPI-minted ephemeral secret; a WS relay is only the fallback. `gpt-realtime-mini` for all development; `gpt-realtime` only for final benchmark runs.
- **Turn-taking:** push-to-talk with Speaker A/B buttons; headphones; mic gated during playback.
- **Secrets (strict):** keys live in `~/.config/agentforge/`; they are loaded into a gitignored chmod-600 `.env` (ElevenLabs as a file secret). Never print, echo, log or commit key values; validity checks print status codes only.
- **ElevenLabs is free tier (10k credits/month):** never called in loops, tests or CI; always mocked; real use only for the final benchmark subset and the demo, behind a budget guard.
- **Anthropic:** key unverified, so the Haiku variant is optional and skippable.
- **Git is graded:** small scoped commits with meaningful messages, pushed regularly; no dump commits.
- **Tests:** cascade pipeline and provider boundaries with mocked providers; error paths for rate limits, timeouts, empty results, denied mic.
- **Targets:** Realtime < 1.5 s, Cascade < 3 s (aim 2 s), measured in the browser from speech end to first audio; stable 5-minute session.
- **Scope control:** stop after the milestone(s) requested in each run; the final comparison doc is written by Butler from the benchmark output, not by the build agent.

## Conventions

- Model ids live only in `config/app.yaml` (plus env overrides), never in code.
- One event contract: `backend/app/core/events.py` ⇄ `frontend/src/session/protocol.ts`, both validated against `contract/fixtures/*.json`.
- Provider adapters normalise audio to PCM16 mono 24 kHz and errors to a small taxonomy (`RateLimited`, `ProviderTimeout`, `AuthError`, `EmptyResult`, …) so the orchestrator handles them uniformly.
- Tests never touch the network; live smoke tests are opt-in (`-m live`) and skipped without keys.
- Commit messages: `type(scope): summary` + a body explaining why.

## Milestone log

### M0 (skeleton, audio I/O, contract, loopback)
- Plan followed DESIGN §10 M0. Built the FastAPI skeleton, contract + fixtures, WS gateway with a pluggable `TurnPipeline` (loopback first), capture/playback/output-tap AudioWorklets on a single render clock, `InterpreterSession`, the UI shell, Compose + `make up`.
- Verification: pytest + Vitest; `make up` health check; a headless-Chrome harness (`backend/eval/browser_smoke.py`) that uses a WAV as the fake mic and drives the real SPA. Loopback floor ≈ 36 ms after the PTT release lag.
- **Agent mistakes caught and fixed:**
  - The first loopback measurement (~1.5 s) included the silence between PTT press and speech, because the echo replayed the whole buffer. Fixed by trimming pre-speech silence; the floor is now tens of ms.
  - The UI marked a turn "done" when the server finished, before the browser had played it, so the harness read no latency. "Done" now requires server completion and playback end.
  - An early attempt targeted Andre's Mac over SSH while `hdx-lab`'s agent connection was down; Andre redirected the work to run on the lab itself.

### M1 (cascade pipeline)
- Order: tests first for the pure pieces (chunker, retry policy, error mapping), then provider Protocols + registry + scripted fakes, then the orchestrator with 16 fake-provider tests (ordering, pipelining, marks, watchdogs, retries, empty results, cancellation/no leaked tasks), then the three OpenAI adapters, each with contract tests against **recorded** responses (a real `gpt-live-transcribe` two-segment event stream and a real Responses SSE stream, captured once and committed to `contract/fixtures/openai/`; the events carry no credentials).
- Before writing the STT adapter the agent probed the undocumented transcription WebSocket (`wss://api.openai.com/v1/realtime?intent=transcription`) with a 1-shot script outside the repo, printing only event types, to confirm the protocol instead of guessing.
- MT model chosen by measurement (`docs/benchmarks/mt-ttft.md`): `gpt-5.4-nano`.
- Verification: 83 backend tests + 14 frontend tests (also offline in Docker with `--network none`), live browser runs in both directions (`docs/benchmarks/m1-cascade-smoke.md`), `curl` of the secret-minting endpoint (status + `ek_` prefix only).
- Realtime was progressed in parallel as allowed by DESIGN §10: secret minting + interpreter session config (M2's backend half). Only `gpt-realtime-mini` was used.
- **Agent mistakes caught and fixed:**
  - Turn 1 in the first live browser run timed out at STT: the session warm-up and the first turn both opened the transcription socket and the later one replaced the event queue. Fixed with a lock + a regression test.
  - A test monkeypatched `asyncio.sleep` globally to speed up retries, which also short-circuited the watchdogs and made the turn time out. Replaced with a zero `Retry-After`.
  - A config-error test passed on the lab only because the lab shell happened to export `OPENAI_API_KEY`; the offline Docker run exposed it. Tests now pin their environment.
  - The smoke harness released PTT at in-sentence pauses of the looping fake-mic file, producing fragment turns ("Could morning." → "¿Buenas, ¿eh?"). It now presses only during silence and requires a minimum speech duration.

### M2 (Realtime mode)
- Direction: "browser WebRTC path with the ephemeral token, WS relay fallback, mic gating during playback, speech-end → first-audio instrumentation, browser smoke in both directions vs < 1.5 s; `gpt-realtime-mini` only; no Anthropic or ElevenLabs calls."
- Order: recorded a real two-turn `gpt-realtime-mini` WS session first (one probe script, key read from file and never printed) and wrote the `oaiEvents` normaliser + history pruner against it; then the WebRTC transport with fake `RTCPeerConnection`/data channel tests (SDP exchange with the `ek_` secret, PTT command sequence, VAD gating, pruning, `close()` releasing peer/channel/track/remote audio); then the backend relay with a fake upstream; then the frontend relay transport; then wiring into `InterpreterSession` (WebRTC / relay / auto-fallback, server-VAD turns, remote-playback gating, a `diag()` leak probe).
- The harness grew `--mode/--rt/--turn-mode`, `--switches` (leak check), `--barge-in`, `--block-webrtc` (fallback) and a gating probe; WebRTC worked in headless Chrome with the fake-mic file on the first try, so the relay is a tested fallback, not the measured path.
- Verification: 87 backend tests, 29 frontend tests, `tsc`, live browser runs (`docs/benchmarks/m2-realtime-smoke.md`, raw logs in `docs/benchmarks/raw/m2/`). The recorded WebRTC data-channel events became a second normaliser fixture.
- **Agent mistakes / findings caught and fixed:**
  - The first ES run released PTT at a 350 ms in-sentence pause (300 ms release policy), and the model *answered* the fragment ("I'm sorry you're feeling that way…") in 2/5 turns. Two fixes: per-turn direction instructions on `response.create` (PTT knows the direction), and a 450 ms harness release policy for both modes. The M1 ES cascade numbers had the same truncation; both cascade directions were re-run under the new policy (in the M2 doc).
  - Barge-in used `lastCommittedTurn`, which is cleared once audio starts, so a press during playback cancelled nothing. It now cancels the playing turn; the relay also drops late audio frames of a cancelled turn.
  - The first barge-in probe measured the session's own flag (16 ms) rather than the end of audio; it now waits for the interrupted turn's `audio.ended`.

