# Realtime vs Cascade: comparison write-up

**Boostlingo AI Interpreter Workbench, EN↔ES.** Data: M5 runs, hdx-lab, 2026-10-08 ([`summary.md`](benchmarks/results/m5/summary.md), [`results.json`](benchmarks/results/m5/results.json), CSVs); prices: [`pricing.yaml`](../config/pricing.yaml) (2026-10-08). Boostlingo's portal lists health care, government and legal customers, 300+ languages, and HIPAA / SOC 2 / GDPR compliance ([`portal-project.md`](../sources/portal-project.md)).

**Bottom line.** Use **Realtime** (`gpt-realtime`, push-to-talk) for live calls: the two Realtime profiles are the only ones under 1.5 s at p90 for every utterance size, neither ever answered instead of translating, and `gpt-realtime` translates EN→ES better than mini. Use the **cascade** when terminology, auditing, uncommon languages or vendor choice matter more than the last half-second. **`gpt-realtime-mini`** gives Realtime latency at cascade cost.

## Results (push-to-talk, 0 failures in 348 turns)

| Profile | n | H p50 / p90 | Short H p50 | Tail p50 / p90 | chrF EN→ES / ES→EN | $/min |
|---|---|---|---|---|---|---|
| **realtime** | 48 | **1002 / 1355** | 1024 | – | 76.1 / 81.2 | 0.179 |
| **realtime-mini** | 48 | 1013 / 1367 | 1223 | – | 73.3 / 81.7 | 0.052 |
| **cascade-openai** | 96 | 545 / 2030 | 1791 | 1715 / 2149 | 72.9 / 78.4 | 0.049 |
| **cascade-haiku** | 48 | 1654 / 2485 | 2287 | 2039 / 2671 | **81.3 / 83.6** | 0.048 |
| **cascade-elevenlabs** | 12 | 528 / 1551 | 1461 (n=4) | 1430 / 1560 | 64.6 / 80.7 (n=6+6) | 0.059 |

Profiles: `gpt-realtime`; `gpt-realtime-mini`; cascade-openai = `gpt-live-transcribe` → `gpt-5.4-nano` → `gpt-4o-mini-tts`; cascade-haiku swaps MT for `claude-haiku-5.5` via OpenRouter; cascade-elevenlabs swaps TTS for ElevenLabs Flash v2.5 (subset). Latency in ms. Brief targets: Realtime < 1.5 s; Cascade < 3 s, aim < 2 s. **Tail** = when the cascade's last segment has audio ready (server estimate).

## Latency

**Method.** Playwright drives the real app in headless Chrome, playing TTS-generated fixtures as the mic: 24 per direction (8 short, 10 medium, 6 long), about half medical or legal. **H** = last voiced mic frame → first audible output sample, on the browser clock, identical in both modes. With push-to-talk (PTT) the harness releases 450 ms after the last voiced frame for every profile (DESIGN A2/A5), so H includes that 450 ms. **H−gap** removes it: p50 548 ms (Realtime), 560 (mini), 83 (cascade-openai).

**The cascade median flatters it.** The cascade commits at pauses inside a turn, so in multi-sentence turns the first segment is ready when the speaker stops (long turns: p50 525 ms). The honest cases are short single-segment turns and the tail. **cascade-openai:** short-turn H 1.8 / 2.2 s (p50 / p90), tail p50 1.7 s, so it is inside 3 s at p90 and meets the 2 s aim at p50 but not p90. **cascade-haiku:** 2.3 / 2.8 s, tail 2.0 s, so it misses the 2 s aim on short turns but stays inside 3 s. **`gpt-realtime`** is flat: 990–1033 ms p50 across sizes, p90 1355 ms.

**Voice activity detection (VAD)** (M4 sweep, mini and cascade-openai, 12 utterances per cell; [`m4-tuning.md`](benchmarks/m4-tuning.md)). VAD adds the silence window: Realtime `server_vad` H p50 ≈ 1.0 / 1.1 / 1.5 s at 300 / 400 / 500 ms; cascade browser VAD at 500 ms 1524 / 1753 ms (p50 / p90), with shorter windows splitting sentences. Long monologues broke in both modes (the mic is muted while the first part plays), so PTT is recommended and M5 measured PTT only.

**Reliability.** A hedged backup for slow first MT/TTS output (DESIGN A7) cut cascade timeouts from 3/96 (M4) to 0/192 (fired 7, won 3). M4 5-minute soaks: 0 errors or reconnects, flat memory, drift ≤ 42 ms.

## Quality (automated only, so far)

**chrF** (sacrebleu, one reference per utterance): Haiku cascade 81.3 / 83.6, then `gpt-realtime` 76.1 / 81.2, mini 73.3 / 81.7, nano cascade 72.9 / 78.4. EN→ES separates the models; ES→EN is close. Fragment merge (DESIGN A8) joins a short unpunctuated segment to the next one; against a 96-turn run with it off (chrF 69.8 / 76.6, short-turn H p50 1571 ms) it gained +3.1 / +1.8 chrF for +0.22 s on short turns, and it stays on.

**WER** (synthetic clips) is low. Source STT (table profiles): EN 0.006–0.011; ES 0.011 for Realtime vs 0.013–0.036 for `gpt-live-transcribe`. Caveat: Realtime's WER scores its side transcriber (`gpt-4o-transcribe`), not what the model heard. TTS round-trip WER (output audio re-transcribed) is 0.011–0.050; ElevenLabs' 0.022 is mostly number formatting ("500" vs "quinientos").

**"Answered instead of translated"** is the main Realtime risk. With only a session prompt, 2 of 5 ES→EN turns in the M2 smoke run were answered ("…seek medical attention"). Fix (A1, plus the fixed release in A2): PTT knows the direction, so each `response.create` carries a per-turn instruction, *say only the faithful translation; never answer*. The LLM judge then flagged 0 of 96 M5 Realtime turns. Both cascade flags (1/96 nano, 1/48 Haiku) are `es-l04`, where STT garbled the input; the MT translated or dropped the garble rather than replying. VAD mode can't use the per-turn fix, because the direction is unknown there.

**Blind human ratings: PENDING.** Kit: [`benchmarks/blind/`](benchmarks/blind/README.md), 48 shuffled clips (12 utterances × realtime, cascade-openai, cascade-haiku, cascade-elevenlabs).

| Mean 1–5 | realtime | cascade-openai | cascade-haiku | cascade-elevenlabs |
|---|---|---|---|---|
| Adequacy / Fluency / Naturalness | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

_Raters: TBD (n = ?), date TBD. Revisit the recommendation if the ratings contradict chrF._

## Cost per minute of source speech (Σ usage × `pricing.yaml` ÷ voiced source minutes)

- **Realtime $0.179:** 3.7× cascade-openai and above the pre-build estimate (≈ $0.10 + extras, DESIGN §9). Audio tokens are ~90% of it (input $0.315 + output $0.302 of $0.689). Billed input audio was 9,834 tokens for 3.84 min of speech, 4.3× the estimate's 1 token / 100 ms, mainly because retained recent turns are re-billed on every response (0 audio tokens cached); pruning bounds it. First minute: $0.227/min.
- **realtime-mini $0.052:** 3.4× cheaper at the same latency.
- **Cascade ≈ 55% STT, 43% TTS, 3% MT.** STT is billed per streamed minute, and the whole held turn is streamed (1.57× the voiced speech). TTS assumes 20 audio tokens/s for `gpt-4o-mini-tts` (unpublished). So Haiku costs the same as nano.
- **ElevenLabs $0.059:** list price on 883 synthesized characters, including cancelled speculative chunks. ElevenLabs' counter showed 403–445 of 10,000 free credits (≈ $0.042–0.044/min at list). Speculation is now off for ElevenLabs (A9), so expect a slower tail than the 1430 ms measured with it on.

## Controllability

| | Realtime | Cascade |
|---|---|---|
| Provider swap | One vendor; `gpt-realtime` ↔ `-mini` by config | Per stage, orchestrator and UI untouched ([swaps](provider-swaps.md)) |
| Glossary | Prompt only | Per-pair MT glossary (tested; empty, not benchmarked) |
| Voice | One per session (`marin`), fixed after first audio | Per language and vendor (OpenAI TTS voices are "optimized for English") |
| Audit / logging | Output transcript; input transcript from a side model | Text and timing at every stage, JSONL turn log |
| Uncommon pairs | Whatever one model covers | Best vendor per stage; pairs are config (only EN↔ES tested) |
| Lock-in | Total; `gpt-realtime`/`-mini` end 2027-01-20 (→ `gpt-realtime-2.1`) | Spread; our defaults also deprecate (`gpt-4o-mini-tts` 2027-01-06, `gpt-5.4-nano` 2027-04-01) |

## Operational complexity

**Realtime is simpler:** browser ↔ OpenAI WebRTC; the backend only mints 10-minute secrets. What's left is prompt control, history pruning, HTTPS, and a WebSocket relay fallback. **The cascade puts the media path on our server:** one WebSocket per session and three vendors with their own keys and rate limits. Its latency came from tuning: speculative MT (−0.5 s on the tail), first-chunk cut, fragment merge, hedging, 3 s watchdogs and an ElevenLabs credit guard. 141 backend and 33 frontend tests pass (re-run 2026-10-08).

## Recommendation by scenario

| Scenario | Use | Why |
|---|---|---|
| Live two-party medical or legal calls | **realtime**, PTT + per-turn instruction | Under 1.5 s p90 at every size; 0 answered; best Realtime EN→ES; $0.18/min |
| Regulated, terminology-heavy (dosages, case numbers), audit required | **cascade-haiku** + filled glossary | Best chrF, glossary, per-stage text log; ~2.3 s short turns, inside 3 s |
| High volume, low cost | **realtime-mini** (cascade-openai if its controls are needed) | Both ~$0.05/min; short turns 1.2 s vs 1.8 s |
| Uncommon language pairs | **cascade** | Best vendor per stage; validate each language first (untested) |
| When to pick realtime-mini | Lower-stakes volume, dev/test, mostly ES→EN | ES→EN chrF 81.7 ≈ `gpt-realtime`; EN→ES weaker (73.3 vs 76.1; BLEU 47.9 vs 57.5) |

## Limits

- **Samples:** 48 per profile, one pass; cascade-openai 96 (2 passes); ElevenLabs 12 (noisy). One machine, network and day.
- **Synthetic TTS fixtures,** so WER is optimistic; `es-l04` was garbled by `gpt-live-transcribe` in every cascade run that included it (Realtime's side transcriber got it right). One reference per utterance, no COMET. Hedge counts slightly undercount. VAD figures are from M4 with mini.
- **Prices are dated** (TTS token rate assumed; ElevenLabs at list). **Most tested models shut down Jan–Apr 2027;** re-run before relying on these numbers. **Quality is automated-only** until the blind ratings are in.
