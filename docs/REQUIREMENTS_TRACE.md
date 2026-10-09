# Requirements trace

This page maps every requirement in the three sources to its status and the evidence for it:
- **Brief:** [`sources/assignment.pdf`](../sources/assignment.pdf), the authoritative brief (IDs `B-…` are ours, assigned in the PDF's order).
- **Portal:** [`sources/portal-project.md`](../sources/portal-project.md), the Gauntlet portal capture, including the submission form (IDs `P-…`).
- **PRD:** [`PRD.md`](PRD.md), our planning document, using its own IDs (FR-, NFR-, CQ-, PROC-, DEL-).

Checked against the code at commit `fd48fa1` plus the docs fixes of 9 Oct 2026.

**Status labels.**
- **Met:** done, with evidence.
- **Partial:** part of it is done; the gap is stated.
- **Not met:** not done.
- **N/A:** optional, or not something a repo can show.

**Terms.** *PTT* (push-to-talk) means holding a Speaker button while talking. *H* is the headline latency: from the end of speech to the first translated sound the listener hears, measured in the browser. *p50 / p90*: half / nine in ten of the turns were faster. *SPA* (single-page application) is a web app that runs in one browser page. *Transport* is the connection that carries a mode's audio and events. Test files are under `backend/tests/` and `frontend/src/` unless a path says otherwise.

## Summary

| Source | Met | Partial | Not met | N/A | Total |
|---|---|---|---|---|---|
| Brief | 34 | 3 | 0 | 2 | 39 |
| Portal | 5 | 0 | 0 | 6 | 11 |
| PRD | 47 | 3 | 2 | 2 | 54 |
| **All** | **86** | **6** | **2** | **10** | **104** |

**Gaps** (all Partial and Not met rows, and what closing each would take) are listed at the end.

## 1. Brief: functional must-haves

| ID | Requirement (quoted) | Status | Evidence |
|---|---|---|---|
| B-FR1 | "Browser-based SPA with microphone capture and audio playback" | Met | `frontend/src/audio/engine.ts`, `capture.worklet.ts`, `playback.worklet.ts`; mic denial handled (`benchmarks/results/m5/error_pass.txt` "mic_denied: PASS") |
| B-FR2 | "Realtime mode using OpenAI Realtime API (gpt-realtime) - voice in, voice out" | Met | `session/transports/realtimeWebrtc.ts`, `backend/app/api/realtime_session.py`; benchmarked with `gpt-realtime` in [`m5/summary.md`](benchmarks/results/m5/summary.md). Note: the config default for development is `gpt-realtime-mini`; `REALTIME_MODEL=gpt-realtime make up` or `?rt_model=gpt-realtime` selects the required model |
| B-FR3 | "Cascade mode using a composed STT → Translation → TTS pipeline with streaming" | Met | `backend/app/cascade/session.py`; `tests/unit/test_cascade_session.py::test_chunks_pipeline_into_tts_before_translation_finishes`, `::test_segments_pipeline_but_audio_stays_in_segment_order` |
| B-FR4 | "UI toggle to switch between modes mid-session or pre-session" | Met | Pre-session: mode buttons and `?mode=`. Mid-session: `InterpreterSession.setMode` tears down and reconnects with the mic live. Leak check: 6 switches, 1 open transport ([`m2-realtime-smoke.md`](benchmarks/m2-realtime-smoke.md)). **Live check on 9 Oct 2026:** one session, one PTT turn each in cascade → realtime → cascade; all three turns done, timeline `turn, switch, turn, switch, turn`, 1 open transport, no errors. Switch marker: `store/reducer.test.ts` |
| B-FR5 | "Language pair selection (minimum: English ↔ Spanish)" | Partial | English ↔ Spanish works in both directions (Speaker A = EN→ES, Speaker B = ES→EN; M5 covers both). There is **no pair selector**: the pair is fixed in `frontend/src/App.tsx` (`PAIR = { a: "en", b: "es" }`), and only one pair exists |
| B-FR6 | "Live transcripts showing both source and target text as they're produced" | Met | `ui/TranscriptPane.tsx` (partials in grey italics, then final text); `transcript.partial` events in `core/events.py`; `store/reducer.test.ts` (partial → final) |
| B-FR7 | "Per-stage latency display visible to the user" | Met | `ui/LatencyWaterfall.tsx` (STT final → MT first token → TTS first byte → first audible sample; Realtime event times), `ui/MetricsSummary.tsx` (p50/p90 per mode) |
| B-FR8 | "Comparison write-up (1–2 pages) covering latency, quality, cost, controllability, and a recommendation" | Met | [`comparison.md`](comparison.md), 2 pages at 11pt with 0.75in margins (re-checked 9 Oct); depth in [`comparison-details.md`](comparison-details.md) |

## 2. Brief: other technical requirements

| ID | Requirement (quoted) | Status | Evidence |
|---|---|---|---|
| B-OR1 | "Provider abstractions in cascade mode so STT/translation/TTS providers can be swapped without rewriting the app" | Met | `backend/app/providers/base.py` (`STTProvider`, `Translator`, `TTSProvider`); 6 adapters; [`provider-swaps.md`](provider-swaps.md) (3 swaps, orchestrator and UI untouched) |
| B-OR2 | "Streaming throughout the cascade pipeline (no full-utterance blocking)" | Met | Streaming STT partials, MT on segment finals and early drafts (A4), sentence chunker → TTS per chunk (`cascade/chunker.py`); tests as in B-FR3. Playback waits for the end of speech by design (D8), but processing doesn't |
| B-OR3 | "AGENTS.md or CLAUDE.md documenting how the candidate directed their coding agent" | Met | [`AGENTS.md`](../AGENTS.md) |
| B-OR4 | "Git history reflecting iterative development" | Met | 160+ commits since 8 Oct 2026, scoped by milestone (`git log`) |
| B-OR5 | "Per-stage latency instrumentation visible in the UI" | Met | As B-FR7; server marks in `cascade/session.py`, browser marks in `audio/outputTap.worklet.ts` |
| B-TECH1 | Language choice: ".NET / C# … preferred … Python is acceptable. Candidate should explain their choice." | Met | README "Why Python rather than .NET"; DESIGN D10 |
| B-TECH2 | "OpenAI Realtime API (model: gpt-realtime) required for Realtime mode" | Met | As B-FR2 |
| B-TECH3 | Cascade providers are the candidate's choice | Met | OpenAI STT/MT/TTS, Claude Haiku (via OpenRouter), ElevenLabs; `config/app.yaml` |
| B-TECH4 | "Agentic coding assistant required … tab-completion only is not sufficient" | Met | [`AGENTS.md`](../AGENTS.md) "Roles and flow" |
| B-TECH5 | "Git required" | Met | GitLab repo `labs.gauntletai.com/andrebatista/boostlingo-interpreter-workbench` |
| B-TECH6 | Cloud optional; "Local-only with clear setup instructions is fine" | N/A | Local-only by choice; setup is `make up` (README "Run it") |
| B-TIME | "3–4 days for the build (~15–20 hours total effort)" | N/A | Built 8–9 Oct 2026 (git dates); effort hours were not tracked |

## 3. Brief: code quality

| ID | Requirement (quoted) | Status | Evidence |
|---|---|---|---|
| B-CQ1 | "Clean separation between mode-specific transport and mode-agnostic UI" | Met | `session/InterpreterSession.ts` + `session/protocol.ts`; transports in `session/transports/`; the UI consumes only `SessionEvent`s ([ARCHITECTURE §2](ARCHITECTURE.md)) |
| B-CQ2 | "Provider abstractions (interfaces or equivalent) … swapping a provider should be a contained change" | Met | As B-OR1 |
| B-CQ3 | "Targeted tests on the cascade pipeline and provider boundaries … critical paths must be tested" | Met | 184 backend + 49 frontend tests pass (`make test`, 9 Oct). Pipeline: `tests/unit/test_cascade_session.py`, `test_chunker.py`, `test_hedge.py`; providers: `tests/contract/test_*.py`; frontend: `oaiEvents.test.ts`, `reducer.test.ts`, transport tests |
| B-CQ4a | Error handling: "rate limits" | Met | `core/retry.py` (backoff, `Retry-After`); `tests/unit/test_retry_errors.py`, `test_cascade_session.py::test_rate_limit_is_retried_and_reported_then_succeeds`; Realtime 429 → `rate_limited` banner (`normalizers/oaiEvents.ts`, `realtimeWebrtc.ts`) |
| B-CQ4b | Error handling: "timeouts" | Met | Watchdogs in `config/app.yaml` `timeouts_s`; `test_cascade_session.py::test_stt_final_watchdog_times_out`, `::test_mt_first_token_timeout`, `::test_tts_first_byte_timeout`; backup request `test_hedge.py` |
| B-CQ4c | Error handling: "empty results" | Met | `test_cascade_session.py::test_empty_transcript_skips_turn_without_mt_or_tts`, `::test_empty_translation_skips_turn`; `error_pass.txt` "silent_turn: PASS" |
| B-CQ4d | Error handling: "mic permission denied" | Met | `ui/ErrorBanner.tsx` with Retry; `error_pass.txt` "mic_denied: PASS … recovered to ready" |
| B-CQ5 | "README with setup, run, and architecture overview" | Met | [`README.md`](../README.md) ("Run it", "Architecture"), plus [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| B-CQ6 | "AGENTS.md/CLAUDE.md describing agent usage" | Met | [`AGENTS.md`](../AGENTS.md) |
| B-CQ7 | "Commits scoped to logical units of work with meaningful messages - no single 'initial commit' dumps" | Met | The first commits add `.gitignore`, the brief, the PRD, the README, research and DESIGN separately, then code in feature commits. There is no "initial commit"; the largest commit is the frontend scaffold (`a366f8f`) |

## 4. Brief: performance and impact metrics

| ID | Requirement (quoted) | Status | Evidence |
|---|---|---|---|
| B-PERF1 | "Realtime mode: under 1.5s end-to-end perceived latency" | Met | `gpt-realtime` H p50 1002 / p90 1355 ms; mini 1013 / 1367 ms ([`m5/summary.md`](benchmarks/results/m5/summary.md)) |
| B-PERF2a | "Cascade mode: under 3s end-to-end" | Met | cascade-openai p90 2030 ms; short sentences p90 2247 ms; Haiku short p90 2844 ms |
| B-PERF2b | "target under 2s with full streaming" | Partial | Met at p50 (short sentences 1791 ms) but not at p90 (short 2247 ms) |
| B-PERF3 | "Stability: sustain a 5-minute back-and-forth conversation without disconnection, audio drift, or memory leaks" | Met | 5-minute soak in both modes: 0 failures/reconnects, flat backend memory, drift ≤ 42 ms ([`m4-tuning.md`](benchmarks/m4-tuning.md) "5-minute soak"). Run with `gpt-realtime-mini` and the default cascade |
| B-KM1 | Impact metric: "End-to-end latency (ms)" | Met | [`KEY_METRICS.md`](KEY_METRICS.md) §1 |
| B-KM2 | Impact metric: "cost per minute" | Met | [`KEY_METRICS.md`](KEY_METRICS.md) §2 ($0.179 Realtime, $0.052 mini, $0.048–0.059 cascade) |
| B-KM3 | Impact metric: "interpretation quality (subjective + WER)" | Met | WER and chrF in M5; blind ratings with 1 rater ([`blind/results.md`](benchmarks/blind/results.md)); in-app ratings via the Review tab (A12) |
| B-KM4 | Impact metric: "provider flexibility" | Met | [`provider-swaps.md`](provider-swaps.md); KEY_METRICS §4 |
| B-KM5 | Impact metric: "time-to-onboard a new language pair" | Partial | Steps listed in KEY_METRICS §5; **not demonstrated or timed** (no third pair) |

## 5. Portal

The portal repeats the brief's functional list in short form (mic SPA, both modes, mode switching, EN↔ES, transcripts, latency display); those rows are covered by B-FR1 to B-FR7 and are not repeated here. Rows below are portal-only or the submission form.

| ID | Requirement (quoted) | Status | Evidence |
|---|---|---|---|
| P-CQ1 | "Comprehensive documentation" | Met | README, AGENTS.md, PRD, DESIGN (A1–A13), ARCHITECTURE, KEY_METRICS, SCALING, comparison + details, provider-swaps, api-research, benchmark write-ups in `docs/benchmarks/`, this trace |
| P-CQ2 | "Meaningful git commits" | Met | As B-CQ7 |
| P-KM1 | Impact metric "Interpretation quality (WER)" | Met | As B-KM3 |
| P-OR1 | "Git history documentation" | Met | As B-OR4; AGENTS.md records each milestone |
| P-SUB1 | Submission: Hiring Partner (required, prefilled "Boostlingo") | N/A | Prefilled by the portal |
| P-SUB2 | Submission: Project Name (required, prefilled) | N/A | Prefilled by the portal |
| P-SUB3 | Submission: GitLab Repository (required) | Met | `https://labs.gauntletai.com/andrebatista/boostlingo-interpreter-workbench`. Andre submits the form himself |
| P-SUB4 | Submission: Deployed Link (optional) | N/A | Not deployed (local-only is allowed) |
| P-SUB5 | Submission: Project Access credentials (optional) | N/A | Only needed for a deployed app with a login |
| P-SUB6 | Submission: Demo Video URL (optional) | N/A | Not recorded yet; optional (see Recommendations) |
| P-SUB7 | Submission: Additional Notes (optional) | N/A | Optional; the README status table and this trace can be pasted |

## 6. PRD

| ID | Requirement (short) | Status | Evidence |
|---|---|---|---|
| FR-1.1 | Mic permission; denial message and retry | Met | As B-CQ4d |
| FR-1.2 | Continuous capture during a session | Met | `audio/capture.worklet.ts`; 5-minute soak |
| FR-1.3 | Playback queue: no overlap, interruption handled | Met | `audio/playback.worklet.ts`; barge-in stops audio in 52 ms (WebRTC) / 13 ms (relay) ([`m2-realtime-smoke.md`](benchmarks/m2-realtime-smoke.md)) |
| FR-2 | Realtime voice in / voice out with `gpt-realtime` | Met | As B-FR2 |
| FR-2.1 | Backend mints short-lived secrets; the key never reaches the browser | Met | `api/realtime_session.py`; `tests/unit/test_realtime_session.py::test_mints_secret_without_leaking_key` |
| FR-2.2 | Interpreter instructions (translate only); PTT default, VAD option (amended D2/D10) | Met | `session/realtimePrompt.ts`, `realtime/session_config.py`; "answered instead of translating" 0 of 96 (M5 judge) |
| FR-2.3 | Transcripts from Realtime transcription and output-transcript events | Met | `normalizers/oaiEvents.ts`; `oaiEvents.test.ts` |
| FR-2 (transport) | WebRTC direct, WebSocket relay fallback | Met | `realtimeWebrtc.ts`, `realtimeRelay.ts`, `api/realtime_relay.py`; fallback check in `m2-realtime-smoke.md` |
| FR-3 | Cascade streaming end to end | Met | As B-OR2 |
| FR-3.1 | Streaming STT with partials, finals and endpointing | Met | `providers/stt/openai_live.py`; `tests/contract/test_openai_live_stt.py` |
| FR-3.2 | MT starts on stable/final segments and streams tokens | Met | `providers/mt/*.py`; `test_cascade_session.py::test_speculation_hit_starts_mt_before_the_stt_final` |
| FR-3.3 | TTS streams from the first chunk; audio played as it arrives | Met | `cascade/chunker.py`, `test_chunker.py`, `test_cascade_session.py::test_chunks_pipeline_into_tts_before_translation_finishes` |
| FR-3.4 | Stages joined by backpressure-aware queues | Met | `cascade/session.py` (asyncio TaskGroup + bounded queues); `::test_cancel_tears_down_all_tasks` |
| FR-4 | Mode toggle pre/mid-session; clean teardown; history kept with a marker | Met | As B-FR4 |
| FR-5 | EN ↔ ES at minimum, bidirectional | Met | Speaker A/B buttons (D2), both directions benchmarked |
| FR-5 (selector) | "explicit source-language selector with a swap button" | Partial | Superseded by D2's Speaker A/B buttons, which choose the direction per turn. No pair selector (see B-FR5) |
| FR-5 (config) | "The pair list is config-driven, so new pairs are configuration, not code" | Not met | `config/languages.yaml` exists, but the UI pair and language-name maps are in code (KEY_METRICS §5) |
| FR-6 | Live transcripts, interim styled differently, then final | Met | As B-FR6 |
| FR-7 | Per-turn waterfall per mode | Met | As B-FR7 |
| FR-7 (stats) | Rolling median and p90; JSON/CSV export | Met | `store/metrics.ts`, `ui/MetricsSummary.tsx` (Export JSON / CSV) |
| FR-8 | Comparison write-up | Met | As B-FR8 |
| FR-9 | Should-have: provider selector per cascade stage | Met | Translator / Voice selectors (`ui/Controls.tsx`), `?mt=` / `?tts=`; STT has one adapter so no selector |
| FR-10 | Should-have: session recording of metrics, no audio by default | Met | Turn records in `data/sessions/*.jsonl`; audio recording is opt-in and off by default (A11) |
| FR-11 | Should-have: a third language pair | Not met | Not built (optional) |
| NFR-1 | Latency targets | Partial | As B-PERF1, B-PERF2a (met) and B-PERF2b (< 2 s met at p50, not p90) |
| NFR-2 | 5-minute stability, soak with memory snapshots | Met | As B-PERF3 |
| NFR-3 | Sample-rate handling; no playback drift | Met | `capture.worklet.ts` resamples to 24 kHz PCM16; soak drift ≤ 42 ms |
| NFR-4 | Keys only on the backend; `.env.example` without values | Met | `.env.example`, `scripts/setup_env.py` (mode 600, prints set/missing only); ElevenLabs as a file secret |
| NFR-5 | Latency on one browser clock; server timings as durations | Met | DESIGN §4; ARCHITECTURE §6 |
| CQ-1 | Transport / UI separation via one session interface | Met | As B-CQ1 |
| CQ-2 | Streaming provider interfaces; orchestrator depends only on them | Met | As B-OR1 (Python Protocols instead of C# interfaces) |
| CQ-3.1 | Orchestrator tests with fake streaming providers | Met | `test_cascade_session.py` (25 tests), `providers/fakes.py` |
| CQ-3.2 | Adapter contract tests, no live keys | Met | `tests/contract/` (6 files) |
| CQ-3.3 | Error-path tests | Met | `test_retry_errors.py`, `test_hedge.py`, `test_budget.py`, error tests in `test_cascade_session.py` |
| CQ-3.4 | Frontend transcript state and metrics aggregation | Met | `store/reducer.test.ts`, `audio/clock.test.ts`, transport and normaliser tests |
| CQ-3.5 | "One opt-in live smoke test per provider, skipped without keys" | Partial | `backend/tests/live/` is empty. Live checks exist as scripts instead: `eval/openrouter_check.py`, `eval/anthropic_check.py`, `eval/browser_smoke.py`, and the M5 harness runs |
| CQ-4 (429) | Rate limits: back off and report | Met | As B-CQ4a |
| CQ-4 (timeouts) | Timeouts | Met | As B-CQ4b |
| CQ-4 (empty) | Empty results | Met | As B-CQ4c |
| CQ-4 (mic) | Mic denied | Met | As B-CQ4d |
| CQ-4 (disconnect) | Provider disconnect mid-stream | Met | `test_cascade_session.py::test_mid_stream_failure_is_not_retried`; `test_realtime_relay.py`; WebRTC `disconnected` banner (`realtimeWebrtc.ts`) |
| CQ-4 (token) | Expired ephemeral token | Met | A key is minted per connect and per mode switch (DESIGN §1), so a stale key isn't reused; mint errors map to `auth_error` (`test_realtime_session.py::test_upstream_errors_are_mapped`) |
| CQ-5 | README with setup, run, architecture diagram, stack choice | Met | As B-CQ5 and B-TECH1 |
| PROC-1 | Agentic coding assistant | Met | As B-TECH4 |
| PROC-2 | AGENTS.md with conventions, breakdown, verification, agent mistakes | Met | [`AGENTS.md`](../AGENTS.md) (mistakes recorded per milestone) |
| PROC-3 | Iterative git history | Met | As B-CQ7 |
| PROC-4 | GitLab repo on labs.gauntletai.com | Met | As P-SUB3 |
| DEL-1 | Working app, local run with setup instructions; deploy optional | Met | `make up`; README "Run it" |
| DEL-2 | Comparison write-up with latency, quality, cost, controllability, recommendation | Met | As B-FR8 |
| DEL-3 | README, AGENTS.md, tests, `.env.example` | Met | All present; tests pass |
| DEL-4 | Benchmark evidence: latency data, utterance set, soak notes | Met | `docs/benchmarks/` (`utterances.yaml`, `results/m5/`, `m4-tuning.md`) |
| DEL-5 | Portal submission (repo URL required; deploy, video, notes optional) | N/A | Andre submits it himself; nothing for the repo to show |
| PRD §10 A2 | No audio stored by default | Met | `recording.enabled: false` (A11) |
| PRD §11 | Out of scope: production auth, scaling, compliance | N/A | Documented as gaps in [`SCALING.md`](SCALING.md) and ARCHITECTURE §9 |

## Gaps: what each would take

**Docs-only gaps:** none open. The stale statements found in this review were fixed in the same series of commits (README, ARCHITECTURE, DESIGN, SCALING, KEY_METRICS, comparison).

**Needs code (for the CTO):**
1. **Language pair selector and config-driven pairs** (B-FR5, FR-5 selector, FR-5 config; also unblocks B-KM5).
   - Replace `PAIR = { a: "en", b: "es" }` in `frontend/src/App.tsx` with a selector fed by `config/languages.yaml` (served from an endpoint or `/healthz`).
   - Move the language-name maps out of `providers/mt/openai.py`, `providers/tts/openai.py`, `realtime/session_config.py` and `frontend/src/session/realtimePrompt.ts` into that config.
   - Remove the `"en"`/`"es"` defaults in `api/realtime_session.py`, `api/realtime_relay.py`, `core/events.py`, `cascade/session.py`, `providers/stt/openai_live.py`.
   - Rough size: small to medium. With EN↔ES as the only entry, the visible change is a dropdown with one option.
2. **Third language pair, timed** (FR-11, B-KM5). After item 1: add sentences and fixtures for the pair, extend `eval/harness.py`'s speaker map and `experiments/config.py`'s `directions`, run an Experiments run and a Review set, and record the wall-clock time. Optional in the brief.
3. **Cascade < 2 s at p90** (B-PERF2b, NFR-1). Short-sentence p90 is 2247 ms. The cost split (TTS first byte ≈ 0.6 s; STT final after release) points at TTS first-byte time and the 450 ms release. Options already measured: `STT_DELAY=minimal` (≈ −0.2 s, worse WER) and ElevenLabs Flash (short p90 1607 ms on 4 turns). This is a tuning or provider decision, not a bug.
4. **Opt-in live smoke tests per provider** (CQ-3.5). Add `backend/tests/live/test_<provider>.py`, each skipped unless its key is set (and ElevenLabs only with `ELEVENLABS_LIVE_TEST=1`), as DESIGN §8 planned. Small.

**Recommendations (not requirement gaps):**
- **Default Realtime model.** `config/app.yaml` defaults to `gpt-realtime-mini`, so a grader running plain `make up` gets mini, not the brief's `gpt-realtime`. Consider `realtime.model: gpt-realtime` for the submission (one config line), or say it on the first screen of the README run section (it is said further down today).
- **Demo video** (P-SUB6, optional): a 3–5 minute screen recording of the README demo steps would help reviewers who don't run the app.
