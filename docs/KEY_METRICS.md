# Key metrics

The Boostlingo brief names five key impact metrics:
1. end-to-end latency;
2. cost per minute;
3. interpretation quality (subjective ratings and WER);
4. provider flexibility;
5. time to onboard a new language pair.

This page explains each one in plain terms. For each it covers how this repo measures it (which script, which command, where the results land), the target from the brief or the [PRD](PRD.md), the measured result, and the status.

**Status labels.**
- **Met:** measured, and the target is achieved.
- **Partial:** some of the target is met, or it is met with caveats.
- **Pending:** not measured yet.
- **Done:** measured and reported where the target is only to report; caveats are listed with the result.

**Where the numbers come from.**
- **Main runs:** the final benchmark runs of 8 Oct 2026 ("M5"), in [`benchmarks/results/m5/`](benchmarks/results/m5/) ([`summary.md`](benchmarks/results/m5/summary.md), [`results.json`](benchmarks/results/m5/results.json) and one CSV spreadsheet per setup).
- **Recording check:** the recording on/off comparison in [`benchmarks/results/recording-ab/`](benchmarks/results/recording-ab/summary.md).
- **In-app experiments (since A13):** latency, source WER, chrF, cost per minute and failures can now be produced from the Workbench's **Experiments** tab. It runs the same harness and metrics code as M5, keeps each run with its code version and model ids, and imports M5 as the read-only "M5 baseline" for comparison (README, "Experiments tab"). The figures on this page are still the M5 runs. The answered-instead-of-translated judge and the TTS round trip are only available from the command line (`eval.metrics --judge --roundtrip`).
- **Plain-language background:** [comparison.md](comparison.md) and [comparison-details.md](comparison-details.md).

**The two designs being compared.**
- **Realtime:** one OpenAI model (`gpt-realtime`) hears the speaker and speaks the translation itself.
- **Cascade:** three services in a chain. **Speech-to-text (STT)** writes down what was said, a **translation model (MT, "machine translation")** translates it, and **text-to-speech (TTS)** reads it aloud.

**Setups measured.**

| Setup | What it is |
|---|---|
| `realtime` | `gpt-realtime` |
| `realtime-mini` | The smaller `gpt-realtime-mini` |
| `cascade-openai` | `gpt-live-transcribe` → `gpt-5.4-nano` → `gpt-4o-mini-tts` |
| `cascade-haiku` | Same, with Claude Haiku 5.5 as the translator, via OpenRouter (a service that resells many vendors' models through one account) |
| `cascade-elevenlabs` | Same, with ElevenLabs Flash v2.5 as the voice. A 12-sentence subset, to save free credits |

## 1. End-to-end latency

**Definition.**
- Latency is the delay from the moment the speaker stops talking to the moment the listener first hears the translation.
- We measure it in the browser, on one clock, the same way for both designs. The start is the last moment the microphone picks up voice; the end is the first audible sound of the translation, detected by a small audio monitor in the page's playback path.
- Speakers use **push-to-talk**: they hold a button while talking. The test robot lets go 0.45 s after the last word, as a person would, and every figure below includes that 0.45 s.

**Percentiles.**
- **p50 (typical):** the median; half of the turns were faster.
- **p90 (slower case):** 9 in 10 turns were faster.

**How it is measured.**
- The app shows the delay for every turn live, with a per-step breakdown (`frontend/src/ui/LatencyWaterfall.tsx`).
- **Benchmarks:** the test robot (`backend/eval/harness.py`) drives the real app in a hidden Chrome window, using the browser-automation tool Playwright. It plays recorded test sentences in place of the microphone and writes one line per turn to a JSONL log file. [`benchmarks/utterances.yaml`](benchmarks/utterances.yaml) holds 48 test sentences: 24 per direction, about half medical or legal.
  ```bash
  cd backend
  python -m eval.harness --mode cascade --profile cascade-openai --out run.jsonl
  python -m eval.harness --mode realtime --profile realtime --out rt.jsonl   # app started with REALTIME_MODEL=gpt-realtime
  python -m eval.metrics --run cascade-openai=run.jsonl --run realtime=rt.jsonl --judge --roundtrip --out-dir out/
  ```
- `eval.metrics` writes `<date>-<setup>.csv`, `results.json` and `summary.md`. The final copies are in [`benchmarks/results/m5/`](benchmarks/results/m5/).

**Targets** (brief, PRD §3): Realtime under 1.5 s. Cascade under 3 s, ideally under 2 s.

**Measured** (milliseconds; 1,000 ms = 1 s):

| Setup | Turns | All turns p50 / p90 | Short sentences p50 / p90 |
|---|---|---|---|
| realtime | 48 | 1002 / 1355 | 1024 / 1360 |
| realtime-mini | 48 | 1013 / 1367 | 1223 / 1367 |
| cascade-openai | 96 | 545 / 2030 | 1791 / 2247 |
| cascade-haiku | 48 | 1654 / 2485 | 2287 / 2844 |
| cascade-elevenlabs | 12 | 528 / 1551 | 1461 (4 turns) / 1607 |

- **The cascade's "all turns" median flatters it.** It starts translating the first sentence of a long turn while the person is still talking. Short single sentences are the fair comparison.
- **Recording check (8 Oct 2026, default cascade).**
  - We compared recording off and on, alternating, with 24 scored turns per arm (20 of them short).
  - Short-sentence p50 was 1785 ms off vs 1781 ms on, and p90 was 2190 vs 2077 ms.
  - So recording adds no measurable delay. The audio is only copied in memory during the turn and written to disk after the last sound has been sent.
- **Stability** (PRD target: a 5-minute conversation with no disconnect, audio drift or memory leak). The 5-minute test sessions in both modes had 0 errors, 0 reconnects and flat memory, with at most 42 ms of delay drift ([`m4-tuning.md`](benchmarks/m4-tuning.md)).

**Status.**

| Target | Status |
|---|---|
| Realtime under 1.5 s | **Met** at p90 for every sentence length, with both models |
| Cascade under 3 s | **Met** at p90 for all setups |
| Cascade under 2 s | **Partial.** The OpenAI cascade meets it at p50 on short sentences (1.8 s) but not at p90 (2.2 s). Haiku misses it on short sentences (2.3 s) |
| Stability | **Met** |

## 2. Cost per minute

**Definition.** Dollars spent with the AI vendors per minute of speech: the voiced part of the test sentences, not silence.

**How it is measured.**
- Each service reports its usage per turn: audio seconds, **tokens** (the small chunks of text or audio that AI services bill by) or characters.
- `eval.metrics` multiplies that usage by the dated prices in [`config/pricing.yaml`](../config/pricing.yaml) (as of 2026-10-08), then divides by minutes of speech.
- The results land in the same M5 files, in the `cost` block of `results.json` and the `$/min` column of `summary.md`.

**Target.** The brief and PRD ask for cost per minute to be reported per mode. There is no dollar target.

**Measured.**

| Setup | $/min | $/min in the first minute | Total cost of the run | Minutes of speech |
|---|---|---|---|---|
| realtime | 0.1793 | 0.2270 | $0.6886 | 3.84 |
| realtime-mini | 0.0521 | 0.0575 | $0.2000 | 3.84 |
| cascade-openai | 0.0489 | 0.0551 | $0.3752 | 7.68 |
| cascade-haiku | 0.0479 | 0.0545 | $0.1841 | 3.84 |
| cascade-elevenlabs | 0.0594 | 0.0594 | $0.0657 | 1.11 |

**What drives the cost.**
- **Realtime** costs about 3.7× the cascade. About 90% of its cost is audio, and the recent conversation is re-read and billed again on every turn.
- **The cascade** splits as speech-to-text about 55%, voice 43% and translation 3%.
- **ElevenLabs** is shown at list price. The free tier actually bills credits, and ElevenLabs' own counter showed fewer characters than our guard counted.

Details are in [comparison-details.md](comparison-details.md#cost-breakdown).

**Status.** **Met** (reported per mode).
- **Caveat:** the OpenAI voice's audio-token rate is not published, so we assume 20 tokens per second.

## 3. Interpretation quality

### 3a. WER (word error rate)

**Definition.**
- WER is the share of words the speech-to-text step got wrong compared with what was actually said. 0.01 means 1 word in 100; lower is better.
- **For Realtime,** it scores the separate transcription model (`gpt-4o-transcribe`) that writes the on-screen transcript, not what the interpreting model itself heard.

**How it is measured.**
- `eval.metrics` compares each transcript with the script in `utterances.yaml`, using the `jiwer` tool after standard text clean-up (Whisper's normalisers).
- **Round-trip WER** re-transcribes what the listener actually heard (`--roundtrip`) and compares it with the text the system meant to say. It checks that the voice is clear.

**Target.** Reported per mode and provider (PRD §3).

**Measured.**

| Setup | WER English | WER Spanish | Round-trip WER |
|---|---|---|---|
| realtime | 0.010 | 0.011 | 0.019 |
| realtime-mini | 0.006 | 0.011 | 0.011 |
| cascade-openai | 0.008 | 0.032 | 0.020 |
| cascade-haiku | 0.010 | 0.036 | 0.050 |
| cascade-elevenlabs | 0.011 | 0.013 | 0.022 |

**Translation score.** We also report **chrF**, a 0–100 score of how closely a translation matches a reference translation. Higher is better; valid rewordings also lose points.

| Setup | chrF English→Spanish | chrF Spanish→English |
|---|---|---|
| realtime | 76.1 | 81.2 |
| realtime-mini | 73.3 | 81.7 |
| cascade-openai | 72.9 | 78.4 |
| cascade-haiku | 81.3 | 83.6 |
| cascade-elevenlabs | 64.6 | 80.7 |

**Answering instead of translating.** An AI judge also checks whether the system answered the speaker instead of translating. It flagged 0 of 96 Realtime turns.

**Status.** **Met** (reported).
- **Caveat:** the test voices are computer-generated and clear, so real callers will score worse.

### 3b. Subjective quality (blind human ratings)

**Definition.** People listen to anonymised, shuffled clips and rate each one from 1 to 5 on three scales:
- accuracy (adequacy): does it carry the full meaning?
- fluency: is it natural language?
- naturalness of the voice.

**How it is measured.**
- `python -m eval.blind …` built the kit in [`benchmarks/blind/`](benchmarks/blind/README.md): 48 clips, 12 sentences × 4 setups, a rating sheet (`rating_sheet.csv`) and a separate answer key (`key.csv`).

**Target.** Reported, with an honest rater count (PRD §3).

- **Ratings are now also collected in the product.** The Workbench's **Review** tab (DESIGN A12) plays the same blind clips one at a time and stores 1–5 ratings per named rater in `data/review.sqlite3`. Setup names stay hidden from the page and the API until the rater finishes or presses Reveal. It shows the same statistics next to M5 latency and chrF. Recorded sessions (A11) can be rated the same way. Andre's sheet is preloaded, and the in-app results match `results.md` exactly (`tests/unit/test_review.py`).
- `cd backend && python -m eval.blind_results` joins the rating sheet with the key and writes [`benchmarks/blind/results.md`](benchmarks/blind/results.md) and `results.csv` (mean, median, spread, by direction, and chrF on the same sentences).

**Measured.** One rater (Andre), 12 sentences per setup (6 per direction), 1–5 scale, with the source sentence and a reference translation shown on the sheet. Mean scores (median in brackets):

| Setup | Accuracy (adequacy) | Fluency | Natural voice | Composite (average of the three) |
|---|---|---|---|---|
| Realtime, `gpt-realtime` | 5.00 (5) | 5.00 (5) | 4.75 (5) | 4.92 |
| Cascade, OpenAI translator | 4.83 (5) | 4.75 (5) | 3.50 (3) | 4.36 |
| Cascade, Haiku translator | 4.92 (5) | 4.42 (5) | 3.33 (3) | 4.22 |
| Cascade, ElevenLabs voice | 5.00 (5) | 4.92 (5) | 4.17 (4) | 4.70 |

- **Accuracy is near the top score for every setup.** Only 3 of 48 clips lost a point on meaning.
- **The voice separates them:** the OpenAI text-to-speech voice used by both OpenAI-voiced cascades scored about 1 point below ElevenLabs and Realtime.
- **The ranking disagrees with chrF,** which puts Haiku first; the rating puts it last, mostly on voice. Details: [comparison-details.md](comparison-details.md).

**Status.** **Done** (met: reported with an honest rater count).
- **Caveats:** one rater, 12 sentences per setup, and computer-generated (synthetic) source audio. Treat it as a sanity check, not a statistically meaningful result.

## 4. Provider flexibility

**Definition.** How easily one vendor can be swapped for another in each step of the cascade.

**How it is measured.**
- [`provider-swaps.md`](provider-swaps.md) records which files each swap touched, taken from the git history.
- The swaps were then exercised for real in the M5 benchmark runs.

**Target.** A swap is a contained change: one adapter plus config (PRD CQ-2). An **adapter** is a small file that translates between our standard interface and one vendor's API.

**Measured / demonstrated.**
- **Adapters in the code:** six, plus test fakes, in `backend/app/providers/`:
  - speech-to-text: 1 (`stt/openai_live.py`);
  - translation: 3 (`mt/openai.py`, `mt/anthropic.py`, `mt/openrouter.py`);
  - voice: 2 (`tts/openai.py`, `tts/elevenlabs.py`).
- **Choosing between existing providers is config only:** `config/app.yaml` (`cascade.mt`, `cascade.tts`), environment variables (`CASCADE_MT`, `CASCADE_TTS`), or the per-session *Translator* / *Voice* selectors in the UI.
- **Adding a new provider** takes:
  - the adapter file and its contract test;
  - a one-line registry entry (`providers/registry.py`);
  - a few lines in `build_providers` (`cascade/ws_pipeline.py`) that map config to its settings.
  The orchestrator (`cascade/session.py`), the event contract and the UI did not change for any of the three swaps.
- **Exercised end to end:** `cascade-haiku` (a different translator) and `cascade-elevenlabs` (a different voice) ran with only these changes.
- **Realtime:** the model can be switched between `gpt-realtime` and `gpt-realtime-mini` by config, but there is only one vendor.

**Status.**
- **Met** for the cascade.
- Realtime is single-vendor by nature.

## 5. Time to onboard a new language pair

**Definition.** How long, and how much work, it takes to add a new pair (for example English↔Portuguese) to the app, including checking that it works.

**What is needed today** (from the code, 9 Oct 2026). Adding a pair is **not yet config only**: several files still assume English and Spanish.

1. **Config.**
   - Add the pair to [`config/languages.yaml`](../config/languages.yaml), with an optional glossary.
   - Add the language code to `providers.openai_live.languages`, and a voice per language under `openai_tts.voices` and `elevenlabs.voices` in `config/app.yaml`.
2. **Code** (small, mechanical edits).
   - Add the language's display name to the name maps in `backend/app/providers/mt/openai.py`, `backend/app/providers/tts/openai.py`, `backend/app/realtime/session_config.py` and `frontend/src/session/realtimePrompt.ts`.
   - Replace the fixed pair in `frontend/src/App.tsx` (`PAIR = { a: "en", b: "es" }`) with a selector. The PRD requires one, but the app does not have it yet.
   - Several defaults also say `"en"`/`"es"` (`api/realtime_session.py`, `api/realtime_relay.py`, `core/events.py`, `cascade/session.py`). They are overridden per session, but should be cleaned up.
3. **Evaluation data.**
   - Write test sentences and reference translations for both directions in `benchmarks/utterances.yaml`.
   - Generate test audio (`scripts/make_fixtures.py` has per-language voice and accent settings).
   - Extend the test robot (`eval/harness.py` assumes `en`/`es` speakers) and the WER text clean-up for the new language.
   - Then run the benchmarks and a native-speaker review.
4. **Vendor coverage check.**
   - Each vendor must support the language. ElevenLabs Flash v2.5 lists 32 languages ([`api-research.md`](api-research.md) §4.2).
   - OpenAI notes its voices are "optimized for English".
   - We found no published language list for `gpt-realtime`.

**Measured.** **Not demonstrated.** The optional third pair (PRD FR-11) was not built, so we have no measured onboarding time. We give no hour estimate, because nothing here would ground one.
- **What can be said:** the code changes are a handful of small edits in about ten files.
- **The longer job is evaluation:** writing reference translations, plus native-speaker review.

**Status.** **Pending (untested).**
- **Next step:** make the language names and the pair selector config-driven, then time a real third pair end to end.

## Summary

| Metric | Target | Result | Status |
|---|---|---|---|
| Latency, Realtime | < 1.5 s | p90 1355 ms (`gpt-realtime`), 1367 ms (mini) | Met |
| Latency, Cascade | < 3 s; aim < 2 s | p90 2030 ms (OpenAI); short sentences p50 1791 / p90 2247 ms | Met < 3 s; partial on < 2 s |
| Recording overhead | None measurable | Short-sentence p50 1785 → 1781 ms | Met |
| Cost per minute | Reported | $0.179 Realtime; $0.052 mini; $0.048–0.059 cascade | Met (reported) |
| WER | Reported | 0.006–0.011 English; 0.011–0.036 Spanish | Met (reported) |
| Subjective quality | Reported | 1 rater, 12 sentences per setup: composite 4.92 Realtime, 4.70 ElevenLabs, 4.36 OpenAI cascade, 4.22 Haiku | Done (smoke test) |
| Provider flexibility | One adapter + config | 6 adapters; swapping is config only; 3 swaps with no orchestrator or UI change | Met (cascade) |
| Language-pair onboarding | Reported | Steps listed; not demonstrated | Pending |
