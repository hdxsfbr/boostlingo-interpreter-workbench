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
- **Anthropic:** the direct key was dropped after M4 (no further calls); Haiku runs only via OpenRouter, for benchmarks and the demo, never in tests or loops.
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

### Decisions recorded after M2 (Andre, CTO)
- **Per-turn direction instructions stay ON for Realtime PTT** (DESIGN amendment A1). Evidence: 2 of 5 ES→EN turns were answered instead of translated without them; 20/20 correct afterwards.
- **Benchmarks use a fixed 450 ms PTT release for every variant**, and every number is also reported with the release gap subtracted (DESIGN amendment A2). The harness already emits `release_lag_ms` and `H_minus_lag_ms` per turn.

### M3 (provider swaps)
- Direction: "Load the Anthropic workspace id the secret-safe way; send `anthropic-workspace-id` from the Haiku adapter; ONE validity check reporting only the status code (200 enables cascade-haiku, otherwise optional). Then M3 per DESIGN under the same constraints; optionally clean the lint warnings."
- Before writing the Haiku adapter, the agent checked the current docs (not memory): the `anthropic-workspace-id` header is required for multi-workspace keys, and Haiku 5.5 accepts `thinking: disabled` only at effort ≤ high and rejects `temperature`/`top_p`/`top_k` and assistant prefill. The one check used the production request shape, built by the adapter itself. **Result: HTTP 400.** Offline format checks only, printing booleans: the workspace id has the `wrkspc_` prefix and the key has the `sk-ant-api` prefix. No second call was made, so cascade-haiku stays behind an enable gate. The Haiku contract test uses a clearly labelled synthetic fixture, because no real stream could be recorded.
- ElevenLabs: adapter written against the documented stream-input protocol and tested only with a scripted fake socket. The credit guard (enable flag, session cap, persistent month ledger) refuses *before* the call, and the pipeline refuses `tts=elevenlabs` at session start unless `ELEVENLABS_ENABLED=1`. Zero ElevenLabs calls were made.
- OpenRouter: the adapter (OpenAI-compatible chat stream, `provider.sort: latency`) is contract-tested. The key file exists on the lab but wasn't loaded, because its use wasn't authorised.
- FR-9 (per-session provider selector) was added because every swap needed a way to be exercised in the real browser. Verified live: refusals for ElevenLabs / Haiku / OpenRouter show one clear banner each; a session-level swap to the fake translator ran a full turn.
- Files touched per swap are recorded in `docs/provider-swaps.md`. The orchestrator and the UI were untouched by every swap.
- Lint: ruff is now clean. That meant narrowing blind `except`s to the real exception types and moving the turn-sink write off the event loop.
- **Agent mistakes caught and fixed:**
  - A regex rewrite of `dict(...)` → literals mangled `ws_pipeline.py`. Caught on inspection before any test or commit; the file was reverted and edited by hand.
  - A new config test would have depended on the host environment again (the M1 lesson), so the OpenRouter key is now pinned to `None` in the test.
  - Commit order: the guard commit's test referenced pipeline wiring from the next commit, so one intermediate commit has a failing test (HEAD is green).


### M4 (harness, latency tuning, VAD sweep, soak)
- Direction: "Priority is cascade latency tuning toward the 2 s aim with OpenAI providers: lower STT delay, speculative/early MT on partial transcripts if sound, a shorter first TTS chunk, and anything else measured to help. Plus the VAD silence-window sweep and the stable 5-minute soak. Keep using gpt-realtime-mini for dev. Do NOT do the final gpt-realtime or ElevenLabs benchmark runs yet." Also: ONE more Anthropic call printing only the status and the error type/message.
- Anthropic: the one extra call returned `400 invalid_request_error`: "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits." Andre then dropped the direct key (DESIGN A3). `setup_env.py` no longer loads it, the adapter stays in code but disabled, and no further Anthropic calls were made.
- OpenRouter (approved mid-M4): the key was loaded by `setup_env.py` into the mode-600 `.env` (never printed). Before the one check, the agent read the public model list (no key) and found that the configured id `anthropic/claude-haiku-5-5` is not OpenRouter's canonical id. A sed fix failed silently, so the check went out with `-5-5`. It returned **HTTP 200, served `anthropic/claude-haiku-5.5`**. The config now uses the canonical id. Then 6 dev turns through the real SPA, and nothing else.
- Order of work:
  1. Harness first, so every later change could be measured the same way: the `?source=file` file source, a 48-utterance fixture set (`make fixtures`), and the Playwright harness with JSONL rows, H−gap, a tail estimate, VAD and soak modes.
  2. A full baseline.
  3. A transcription-socket probe (timestamps only) showed that partials stream *before* commit. That is what made speculation sound.
  4. Each tuning change was A/B'd in its own container (`interpreter-workbench:m4*` with env overrides) on the same 24-utterance subset.
  5. Final full runs, VAD sweeps, and soaks in both modes.
- Speculative MT was built test-first with a streaming fake STT (partial before commit): hit, miss, late-partial restart, speculative error not failing the turn, pause hint. Speculative output is held until adopted, so a miss is invisible.
- Decided by data, not by intuition:
  - TTS warm-up, the pause hint and STT `minimal` alone didn't help.
  - Speculation (−0.5 s tail) and the 20-char first chunk (−0.1 s) did.
  - `minimal` + speculation was ~0.2 s faster, but STT WER rose 2–3×, so the default stays `low`. This was found only because the agent spot-read soak transcripts and then computed WER for every run.
- Results: `docs/benchmarks/m4-tuning.md`. Cascade tail p50 went 2080 → 1578 ms (short utterances 1962 → 1375 ms, including the 450 ms release). Realtime-mini PTT stayed at 976 ms. Both 5-minute soaks had 0 errors, 0 reconnects, flat RSS and no drift.
- **Agent mistakes / findings caught and fixed:**
  - The first harness release rule (release at the first 450 ms of silence) cut multi-sentence fixtures, whose TTS voices pause 0.5–0.9 s between sentences. It also counted trailing file silence in the release gap. Now it releases 450 ms after the utterance's last voiced frame (DESIGN A5).
  - The first VAD sweep was invalid: pure digital silence from the file source stalled WebRTC, so server VAD never ended turns. The agent diagnosed it with a turn-state trace, added a noise floor, and re-ran.
  - The sweep then exposed two real client/server bugs (turns stuck in "playing"; cascade VAD turns cancelling each other's translation). The first queueing fix introduced a third (two turns reading one STT socket → STT timeouts). It was caught in the next sweep and fixed with a regression test.
  - A chained shell command ran the realtime soak from the wrong directory (module not found), and one commit went in with 3 lint errors (fixed in the next commit). Both were noticed from logs and re-run or fixed.
  - The agent killed only processes and containers it had started, by PID or name.

### M5 (hedge, fragment fix, final benchmarks, docs)
- Direction: "Build the hedged first-output request with tests and measure whether it removes the 3/96 timeouts; fix fragment translations if cheap; then M5 per DESIGN including the FINAL runs: gpt-realtime (mini as a row), cascade-openai full set, cascade-haiku via OpenRouter, cascade-elevenlabs on a credit-guarded subset with a by-ear proxy check; WER + chrF; blind-rating materials; machine-readable results + summary for Butler (not the comparison doc); README/runbook and AGENTS.md." Decisions carried in: STT delay `low`, VAD 400 ms realtime / 500 ms cascade, PTT recommended for long turns.
- **Hedge (DESIGN A7):** written test-first (`test_hedge.py`, 10 tests: no hedge on a fast primary, the backup wins and the loser is cancelled, the primary wins after a hedge, both slow → timeout, the backup errors → falls back, sole error propagates, TTS backup without duplicate audio, chars counted once). `ReplayableChunks` became multi-consumer so a TTS backup can replay chunks. Measured: **0/192 first-output timeouts** in the two cascade A/B arms (M4: 3/96); 7 hedges fired, 3 won by the backup.
- **Fragment fix (DESIGN A8), decided by data:**
  - First attempt: a browser rule (pause commit only after ≥ 1 s of speech). A smoke run showed short-turn H going from ~0.5–1.4 s to ~2.1–2.4 s, because the early pause commit is what lets speculative MT start before the release. The agent stopped the half-finished benchmark chain (its own PIDs only), kept the rule as an off-by-default A/B switch, and moved the fix server-side.
  - Second attempt, server-side: a short unpunctuated non-final segment is merged into the next one.
  - A/B on 2×48 per arm: chrF EN→ES 69.8 → 72.9 and ES→EN 76.6 → 78.4; short-turn H p50 1571 → 1791 ms; medium and long turns unchanged. Kept on by default. Andre can revisit (env `CASCADE_MERGE_FRAGMENTS=false`).
- **Final runs** were serial, one container per profile, with output audio recorded in the browser (post-tap webm). The guard pre-check ran before any ElevenLabs call (estimate 1,111 chars ≤ cap 1,400, session cap 1,500). The subscription counter was read before (0) and after; it shows 445 chars used, while the local ledger, which is conservative, charged 883.
- **Metrics** (`eval/metrics.py`):
  - jiwer with Whisper normalisers; sacrebleu chrF/BLEU.
  - a batched LLM judge for "answered instead of translated";
  - a gpt-4o-transcribe round trip of the recorded output audio (the ElevenLabs by-ear proxy);
  - cost/min from turn usage × the dated `config/pricing.yaml`;
  - blind kit from `eval/blind.py`;
  - `eval/error_pass.py` (all 4 browser checks pass).
- **Agent mistakes / findings caught and fixed:**
  - `ruff format` was run on the whole backend, which reformatted 52 files. It was caught before committing; the unrelated files were restored and the hedge edits re-applied in the project's style.
  - The judge's first call returned 400 (the Responses `json_object` format requires the word "json" in the input). The round-trip WER counted ’ vs ' as an error. Both were fixed and the metrics recomputed from cache, with no new live calls.
  - The run was interrupted twice (the user's session reset). Each time the agent first checked the ElevenLabs counter/ledger and container health before continuing, to avoid double-spending credits. Work was committed in small pieces so nothing was lost.
- **Known limitations:**
  - One reference per utterance, so chrF penalises valid paraphrases.
  - Synthetic TTS fixtures (es-l04 is badly recognised by every STT).
  - The ElevenLabs row is 12 utterances only.
  - Hedge counts from marks collapse repeated hedges within one turn.
  - With speculation, ElevenLabs is charged for chunks of cancelled speculative runs (ledger 883 vs 403–445 billed).
- **After M5 (Andre):**
  - Speculative MT/TTS is off by default when ElevenLabs is the TTS, so cancelled speculative chunks don't spend demo credits (DESIGN A9; `cascade.speculative_with_elevenlabs` opts back in; covered by unit tests with mocked providers).
  - Recorded decisions (DESIGN A10): nano stays the cascade default for the latency target, Haiku via OpenRouter is the quality option, and fragment merging stays on.
- **Session recording (DESIGN A11, Andre, time-boxed ~1.5 h):**
  - Opt-in audit recording, off by default (config flag plus a per-session UI toggle with a consent notice and a "● Recording" indicator). With the flag off, the server refuses: cascade `recording_refused`, uploads 403.
  - Cascade is captured server-side as WAV (inbound PCM and TTS PCM). Realtime is captured in the browser with MediaRecorder (mic track and output tap) and uploaded per turn to a validated endpoint (id regex, turn, side, content type, size, path-traversal checks, atomic write).
  - Files go to `data/recordings/<sid>/turn-<n>-{source,target}.<ext>`, with an audit line per file in the session JSONL and the paths in the turn records. Retention defaults to 30 days, swept at startup and every 6 h; `DELETE /api/recordings/<sid>` removes a session.
  - Tests: 8 backend tests (off by default, files when on, nothing without the toggle, server refusal, upload 403/validation/traversal, retention, delete) and 7 Vitest tests (per-turn MediaRecorder lifecycle, barge-in, flush on close, toggle disabled/consent, turn-record paths). All mocked.
  - One live smoke per mode with `RECORDING_ENABLED=1` and `eval.harness --session-record` (2 short utterances each; cascade default, and gpt-realtime-mini over WebRTC). All 8 files appeared, decoded, had plausible durations and were non-silent (ffprobe/volumedetect).
  - Agent mistake caught: the first backend commit went in with two ruff findings in the new test, because `ruff … | tail` hid the exit code. Fixed in the next commit.
- **Recording latency A/B (Butler):** default cascade, PTT 450 ms, 12 scored utterances (10 short) plus 2 unscored warm-ups, arms alternated off/on/off/on (n=24 per arm). Short H p50 was 1785 (off) vs 1781 ms (on), short tail p50 1733 vs 1720 ms: no measurable cost, so no fix was needed. Results are in `docs/benchmarks/results/recording-ab/`.
- **Review tab (DESIGN A12, Andre via Butler, time-boxed 2–3 h):**
  - What it is: an in-app human rating flow that reuses Butler's `rate.py` UX (one clip at a time, 1–5 adequacy/fluency/naturalness, notes, Back / Save & next, progress, resume, keys 1–5 / Tab / Space / Enter, visible save errors).
  - Storage: SQLite `data/review.sqlite3` (atomic transactions, CHECK constraints, raters by name).
  - Two sources: the blind M5 set (shipped in the image via `BENCH_DIR`) and recorded sessions.
  - Results: per-variant mean/median/sd/range by direction, next to M5 H and chrF, with CSV export.
  - Blindness is enforced server-side: no variant in any payload before Reveal or completion; results return 403.
  - Andre's 48 ratings are preloaded as `andre`. A test asserts the in-app statistics equal `eval/blind_results.py` output (its `results.csv`, plus its own `load()`/`stats()`).
  - Tests: 15 pytest, 6 Vitest. Headless check `eval/review_check.py`: preload complete, Results == results.md cell for cell, keyboard round trip, resume, a failed save, scratch-rater cleanup.
  - `docs/comparison.md`: one added line only, conclusions untouched.
  - Agent finding: the first headless run showed Back stored an empty rating for an untouched clip (as `rate.py` also did). Fixed so unchanged drafts aren't written.
- **Experiments tab (DESIGN A13, Andre via Butler, time-boxed 3–4 h):**
  - What it is: an in-product runner for the M5 harness. Create (setups, utterance set, directions, passes), get an estimate, confirm above $1, run, watch live SSE progress, cancel. Then history, detail (M5 columns + latency chart), compare, and CSV/JSON export.
  - Reuse: the job runs `python -m eval.harness` per setup inside the container (the image now has Playwright + headless Chromium + metrics deps) and summarises with `eval.metrics`. New harness flags: `--rt-model` (with `?rt_model=` in the SPA) and `--pipeline` (loopback, free).
  - Storage: `data/experiments.sqlite3`. The M5 baseline is imported read-only. The git commit is stamped at build (`make up` passes `GIT_COMMIT`).
  - Guardrails: 428 confirm above `experiments.confirm_above_usd`, ElevenLabs only with `allow_elevenlabs` (plus the harness credit guard), a gpt-realtime warning, 409 for a second run (refused, not queued), and Cancel kills the harness process tree (`cleanup.orphans` recorded).
  - Tests: 20 pytest (fake harness child; no browser, no provider) and 3 Vitest. Headless check `eval/experiments_check.py` (runs in the container): 17 checks pass, including baseline == results.json per profile.
  - Live smoke (the only paid run): realtime-mini + cascade-openai on 6 short utterances (en/es s01–s03), 12/12 done, 0 failures, 87 s. Actual **$0.0228**. The estimate at run time (flat M5 $/min) was $0.0169 (−26%). Fixed: the estimate now sums M5's measured per-utterance cost, which gives $0.0229 for the same config.
  - Smoke latency vs M5 on the same 6 ids: realtime-mini H p50 1059 vs 1237 ms; cascade-openai 2261 vs 1690 ms. n=6 with Chromium inside the app container, not investigated. Compare in-app experiments with each other.
  - Live cancel check (free, cancelled before the first utterance): status cancelled, 0 orphans, no harness/Chromium process left in the container.
  - Cut for time: queueing, "create review set from experiment", in-app judge/round trip, and per-experiment server config.
