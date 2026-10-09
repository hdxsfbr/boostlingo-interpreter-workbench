# PRD: AI Interpreter Workbench (Realtime API vs Cascade Pipeline)

| | |
|---|---|
| **Partner** | Boostlingo (Gauntlet Platinum partner) |
| **Owner** | Andre Batista |
| **Due** | Sunday 2026-10-11 (from Andre; the portal shows no due date) |
| **Budget** | 3–4 days, about 15–20 hours (brief) |
| **Status** | v0.2, 2026-10-08: amended per DESIGN.md D10 (stack, providers, push-to-talk) |
| **Sources** | [`sources/assignment.pdf`](../sources/assignment.pdf) (authoritative) and [`sources/portal-project.md`](../sources/portal-project.md) (portal capture) |

**Conventions**
- Requirement IDs (FR-, NFR-, CQ-, PROC-, DEL-) are checkable.
- *[Brief]* means a statement taken from the PDF or portal.
- *[Assumption]* means our choice, which Andre can overrule.
- Nothing here about Boostlingo goes beyond the two sources.

---

## 1. Problem

*[Brief]* Boostlingo connects people who need language interpretation with professional human interpreters, and live interpretation is its core product.

AI offers two architectures for live interpretation:
- **Direct voice-to-voice** (OpenAI Realtime API): "less control, lower latency".
- **Composable STT → Translation → TTS cascade**: "more control, more moving parts to operate".

Their trade-offs in latency, quality, cost and operational control "are not obvious until both are built". The architecture choice will drive cost per minute, the latency floor, vendor lock-in, and the ability to offer differentiated quality on uncommon language pairs. It will inform product and platform investment over the next 12–18 months.

**What we are building:** a browser workbench that runs the *same conversation* through either architecture, instruments every stage, and produces a defensible recommendation for when each one fits.

## 2. Users

- **Primary: Boostlingo engineering and product evaluators** (hiring-partner reviewers). They need to switch modes, watch latency per stage, judge quality, and read a recommendation they can trust.
- **Demo users:** two people holding an English ↔ Spanish conversation through the app. For testing, one operator can play both sides with a microphone.
- **Graders:** Gauntlet reviewers checking requirements, code quality and git history.

## 3. Goals and success metrics

*[Brief]* key impact metrics: end-to-end latency (ms), cost per minute, interpretation quality (subjective + WER), provider flexibility, and time-to-onboard a new language pair.

| Metric | How we measure it | Target |
|---|---|---|
| Realtime perceived latency | Speech end → first translated audio out, measured in the browser, per turn; report median and p90 over at least 20 turns | **< 1.5 s** *[Brief]* |
| Cascade perceived latency | Same definition | **< 3 s; target < 2 s with full streaming** *[Brief]* |
| Per-stage latency (cascade) | STT finalization, translation first token / complete, TTS first byte, playback start | Shown live in the UI *[Brief]* |
| Stability | A 5-minute back-and-forth conversation | No disconnect, audio drift or memory leak *[Brief]* |
| Cost per minute | Provider usage per session (audio seconds, tokens, characters) × prices from a config file | Reported per mode in the write-up. Prices are entered from provider pricing pages on the measurement date; none are hard-coded as facts |
| Quality: WER | STT WER on a scripted EN and ES utterance set with reference transcripts; for Realtime, use its input transcription | Reported per mode/provider |
| Quality: subjective | A blind rating of translation adequacy, fluency and voice naturalness (1–5) on the same scripted set | Reported. Rater count is stated honestly (likely 1–2) |
| Provider flexibility | Files touched to swap one provider | Swapping a provider is a contained change: one adapter plus config (CQ-2) |
| Time to onboard a language pair | Steps and config needed to add a third pair, demonstrated or estimated | Reported in the write-up |

## 4. Functional requirements (must-haves)

The PDF's numbered must-haves are FR-1 to FR-8. Items marked *(derived)* are needed to satisfy them.

- **FR-1 Browser SPA with mic capture and playback.**
  - FR-1.1 Request mic permission. Handle denial with a clear message and a retry path.
  - FR-1.2 Capture audio continuously during a session.
  - FR-1.3 Play translated audio with a playback queue: no overlapping utterances, and interruption handled.
- **FR-2 Realtime mode.** Voice in, voice out using OpenAI Realtime API model `gpt-realtime` *[Brief]*.
  - FR-2.1 The backend mints short-lived client secrets (`POST /v1/realtime/client_secrets`). **The OpenAI key never reaches the browser.**
  - FR-2.2 The session is instructed to act as an interpreter for the selected pair (translate only, no answering). *Amended (D2/D10):* turn-taking defaults to **push-to-talk** with Speaker A / Speaker B buttons (`turn_detection: null` + explicit commit); server VAD remains a selectable option and is benchmarked with matched silence windows.
  - FR-2.3 Source and target transcripts come from Realtime transcription and output-transcript events.
  - *[Assumption]* Transport is browser **WebRTC** directly to OpenAI, for the lowest latency. A server WebSocket relay is the fallback. The connection flow follows OpenAI's current GA Realtime docs and must be re-checked at build time.
- **FR-3 Cascade mode.** STT → Translation → TTS, streaming end to end. There is no full-utterance blocking at any stage *[Brief]*.
  - FR-3.1 Streaming STT with interim and final results, plus endpointing.
  - FR-3.2 Translation starts on stable or final segments (clause-level chunking allowed) and streams its output tokens where the provider supports it.
  - FR-3.3 TTS streams audio as soon as the first translated chunk exists. Audio chunks are played as they arrive.
  - FR-3.4 Stages are connected by async streams or channels (backpressure-aware) inside a backend session.
- **FR-4 Mode toggle.** Switch Realtime ↔ Cascade pre-session or mid-session *[Brief]*.
  - A mid-session switch tears down the old transport cleanly (no leaked sockets or audio nodes) and keeps the transcript history, marking the switch point.
- **FR-5 Language pair selection.** At minimum English ↔ Spanish *[Brief]*.
  - *(derived)* Bidirectional: either speaker can speak either language. *[Assumption]* The direction is chosen by an explicit "speaker A / speaker B" control, or by detected language where the provider supports it. Default: an explicit source-language selector with a swap button.
  - The pair list is config-driven, so new pairs are configuration, not code.
- **FR-6 Live transcripts.** Source and target text are shown as they're produced: interim results styled differently, then replaced by final text *[Brief]*.
- **FR-7 Per-stage latency display.** Visible to the user *[Brief]*.
  - Per turn, a timeline or waterfall: speech end → STT final → translation first token → TTS first byte → playback start (cascade); speech end → first audio delta → playback start (Realtime).
  - A rolling median and p90 are shown. Per-turn metrics can be exported as JSON or CSV for the write-up.
- **FR-8 Comparison write-up (1–2 pages).** Covers latency, quality, cost, controllability, and a recommendation for which mode fits which scenario *[Brief]*. See DEL-2.

**Should-haves (only if time allows):**
- FR-9: provider selector in the UI for each cascade stage.
- FR-10: session recording of metrics, without storing audio by default.
- FR-11: a third language pair to demonstrate onboarding time.

## 5. Non-functional requirements

- **NFR-1 Latency.** Realtime < 1.5 s; Cascade < 3 s, target < 2 s. Both measured as speech end → first audio out *[Brief]*.
- **NFR-2 Stability.** A 5-minute conversation with no disconnection, audio drift or memory leak *[Brief]*. Verified by a scripted soak run with browser memory snapshots before and after (DEL-4).
- **NFR-3 Audio correctness.**
  - Correct sample-rate handling (for example 48 kHz mic → provider rate) and a consistent PCM format per provider.
  - The playback queue must not drift or accumulate delay over 5 minutes.
- **NFR-4 Secrets.**
  - Provider API keys live only on the backend (environment / user-secrets / `.env`, all gitignored). The browser gets only ephemeral credentials.
  - `.env.example` lists the variables with no values.
- **NFR-5 Timing honesty.** Perceived latency is measured in the browser on one clock. Server stage timings are reported as durations, never compared across clocks.

## 6. Code-quality requirements

- **CQ-1 Separation.** Clean separation between mode-specific transport (Realtime WebRTC, Cascade WebSocket) and mode-agnostic UI *[Brief]*. The UI talks to a single `InterpreterSession`-style interface that emits transcript, audio and metric events.
- **CQ-2 Provider abstractions.** Interfaces for `ISpeechToText`, `ITranslator` and `ITextToSpeech`, each streaming *[Brief]*.
  - Swapping a provider is a contained change: a new adapter plus a DI or config entry.
  - The pipeline orchestrator depends only on the interfaces.
- **CQ-3 Tests.** Targeted tests on the cascade pipeline and provider boundaries, with critical paths tested; full coverage is not required *[Brief]*. Minimum set:
  - CQ-3.1 The orchestrator with fake streaming providers: ordering, chunking, latency stamps, cancellation.
  - CQ-3.2 Provider adapter contract tests: event mapping and error mapping, using recorded or fake responses with no live keys in CI.
  - CQ-3.3 Error paths (CQ-4).
  - CQ-3.4 Frontend state for the transcript (interim → final) and metrics aggregation.
  - CQ-3.5 One opt-in live smoke test per provider, skipped without keys.
- **CQ-4 Error handling** *[Brief]*. Each case shows a user-visible state and a recovery path:
  - rate limits (429): back off and report;
  - timeouts;
  - empty results (no speech, or an empty translation);
  - mic permission denied;
  - provider disconnect mid-stream;
  - expired ephemeral token.
- **CQ-5 Documentation.** A README with setup, run and an architecture overview *[Brief]*, including a diagram of both data paths and an explanation of the stack choice ("Candidate should explain their choice" *[Brief]*).

## 7. Process requirements

- **PROC-1 Agentic coding assistant.** Required; tab completion alone is not enough *[Brief]*. Development is done with an agentic coding assistant.
- **PROC-2 `AGENTS.md`** (and/or `CLAUDE.md`). Documents how Andre directed the coding agent *[Brief]*: conventions, the task breakdown, prompts and plans used, review and verification practice, and what the agent got wrong and how it was corrected.
- **PROC-3 Git history.** Reflects iterative development. Commits are scoped to logical units with meaningful messages; no single "initial commit" dump *[Brief]*.
- **PROC-4 Repository.** A GitLab repo on labs.gauntletai.com. It is a *required* field of the portal submission.

## 8. Deliverables

- **DEL-1 Working app.** Local run with clear setup instructions. Deployment is optional, with AWS preferred if deploying *[Brief]*.
- **DEL-2 Comparison write-up.** `docs/comparison.md`, 1–2 pages, built from measured data:
  - latency (median and p90 per stage);
  - quality (WER plus subjective ratings);
  - cost per minute, with dated pricing;
  - controllability (provider choice, glossary or terminology control, voice, language coverage, observability);
  - a recommendation by scenario.
- **DEL-3** README, `AGENTS.md`, tests, and `.env.example`.
- **DEL-4 Benchmark evidence.** The exported latency data, the scripted utterance set, and soak-test notes (`docs/benchmarks/`).
- **DEL-5 Portal submission.**
  - Required: GitLab repo URL.
  - Optional: deployed link (plus credentials if login-gated), demo video URL, notes.
  - Andre submits it himself.

## 9. Architecture *(decided: see DESIGN.md; amended per D10)*

> **Amendment (2026-10-08, D10):** the backend is **Python / FastAPI**, not ASP.NET Core. Andre chose Python for faster iteration on streaming audio SDKs; the brief prefers .NET but accepts Python, and the README explains the choice (CQ-5). The diagram below keeps the original component split, which is unchanged.

```
Browser (React + TypeScript + Vite)
 ├─ Mode-agnostic UI: language pair, mode toggle, transcripts, latency waterfall
 ├─ InterpreterSession interface
 │   ├─ RealtimeTransport: WebRTC to OpenAI with an ephemeral key from the backend
 │   └─ CascadeTransport: WebSocket to the backend; PCM up, audio/transcript/metric events down
 └─ AudioIO: mic capture (AudioWorklet) and a playback queue

Backend (Python 3.12, FastAPI)  [was: ASP.NET Core, C#; amended per D10]
 ├─ POST /api/realtime/session  → mints the client secret (OpenAI key stays server-side)
 ├─ WS  /ws/cascade             → per-connection CascadeSession
 │     STT adapter ─▶ segmenter ─▶ Translator adapter ─▶ TTS adapter   (streams/channels, latency stamps)
 ├─ Provider interfaces + DI registration; config-driven pairs/providers
 └─ Metrics: per-turn stage durations sent to the client
```

## 10. Open questions and assumptions (for Andre)

- **Q1 Stack.** *Resolved (D10): Python/FastAPI backend + React/Vite/TS frontend, Docker Compose on hdx-lab.* The brief prefers .NET/C# backend and TypeScript frontend; Python is acceptable.
  - *Proposal:* ASP.NET Core (.NET 8 LTS or .NET 9) plus React/Vite/TS.
  - Lab check (2026-10-08): **no .NET SDK is installed on hdx-lab**; Node is available via nvm (v22/v24). Andre may build on his Mac instead.
  - Decide: .NET (matches the partner's preference and stack) or Python (faster for audio SDKs).
- **Q2 Cascade providers.** *Resolved (D4/D10): providers are limited to OpenAI, Anthropic, ElevenLabs (free tier), OpenRouter and local/free tools. Defaults: `gpt-live-transcribe` → OpenAI small model (chosen by measured TTFT) → `gpt-4o-mini-tts`; swaps: `claude-haiku-5-5` MT, ElevenLabs Flash TTS. Deepgram/DeepL/Azure below are superseded.*
  - *Proposal:* Deepgram (streaming STT) → OpenAI small chat model with streamed tokens (translation) → ElevenLabs or OpenAI TTS (streaming).
  - DeepL is a strong option for translation quality and glossaries, but it returns whole segments, not tokens.
  - Decide based on keys and accounts available and on the latency budget.
- **Q3 API keys.**
  - **An OpenAI API key is required.** `gpt-realtime` is not available through OpenRouter, so a direct OpenAI account with Realtime access and billing is needed.
  - Other keys depend on Q2: ~~Deepgram, DeepL, Azure~~ (superseded, D10) → Anthropic (optional, Haiku MT), ElevenLabs (free tier, benchmark subset + demo only), OpenRouter (optional).
  - OpenRouter could serve LLM translation in cascade mode if desired.
  - Decide which accounts exist and the spend cap.
- **Q4 Model naming.** The brief says `gpt-realtime`. OpenAI's docs also show newer realtime model names.
  - *Assumption:* use `gpt-realtime` as the default for compliance, and make the model a config value so a newer snapshot can be compared.
- **Q5 Turn-taking.** Server VAD is the default for both modes; is push-to-talk wanted as a fallback for noisy demos? Who speaks when: speaker-A/B buttons vs auto language detection?
- **Q6 Deployment.** Local-only is acceptable. Optional AWS (for example App Runner, ECS or Lightsail plus CloudFront for the SPA). WebRTC and mic require HTTPS when not on localhost. Decide whether to deploy and whether to record a demo video (an optional submission field).
- **Q7 Quality evaluation.** Size of the scripted EN/ES utterance set (proposal: about 20 per direction, mixed domains, including a medical or legal-flavoured set, given Boostlingo's customers per the portal). Who rates subjectively?
- **Q8 Cost model.** Pricing sources and the date they are captured. No prices are hard-coded in code, and they are cited in the write-up.
- **Assumption A1:** single-user demo; no auth, persistence or multi-tenant concerns.
- **Assumption A2:** no audio is stored by default (privacy). Metrics only.

## 11. Out of scope

- Human-interpreter routing, scheduling, billing, telephony/video integrations (Zoom, Teams and so on), and compliance certification (HIPAA, SOC 2, GDPR). These are mentioned on the portal as Boostlingo's platform, not as part of this brief.
- Production auth, multi-tenancy and horizontal scaling.
- Full test coverage *[Brief: not required]*.
- Language pairs beyond EN ↔ ES (optional FR-11 only).
- Custom model training or fine-tuning.

## 12. Milestones (suggested, about 15–20 h)

| # | Slice | Rough effort |
|---|---|---|
| M0 | Repo, `AGENTS.md`, stack scaffold, `.env.example`, CI-less test runner | 1–2 h |
| M1 | Audio I/O (mic capture, playback queue) and the mode-agnostic UI shell | 2–3 h |
| M2 | Realtime mode end to end, with latency stamps | 3 h |
| M3 | Cascade mode: interfaces, fakes and tests first, then real adapters, streaming | 5–6 h |
| M4 | Latency waterfall, mode switch mid-session, error states | 2 h |
| M5 | Benchmarks (latency, WER, soak), cost model, `docs/comparison.md` | 2–3 h |
| M6 | README and architecture, polish, optional deploy and demo video | 1–2 h |

## Appendix: status as built (2026-10-09)

The requirements above are kept as planned. Their status, with evidence for each ID, is in [`REQUIREMENTS_TRACE.md`](REQUIREMENTS_TRACE.md). In short:
- **Met:** FR-1 to FR-4, FR-6 to FR-10, NFR-2 to NFR-5, CQ-1 to CQ-5 (except CQ-3.5), PROC-1 to PROC-4, DEL-1 to DEL-4.
- **Partial:** FR-5 (English ↔ Spanish works both ways, but there is no pair selector and pairs aren't config-only), NFR-1 (cascade meets < 3 s, and < 2 s only at the median), CQ-3.5 (live checks are scripts, not opt-in tests).
- **Not met:** FR-11 (no third pair; optional). The FR-5 config-driven pair list counts as Not met in the trace.
- **Changed by later decisions:** the backend is Python, not .NET (D10); turn-taking defaults to push-to-talk (D2); Haiku runs via OpenRouter (A3); audio recording exists but is opt-in (A11); in-app ratings (A12) and experiments (A13) were added after M5. DEL-5 (portal submission) is Andre's.
