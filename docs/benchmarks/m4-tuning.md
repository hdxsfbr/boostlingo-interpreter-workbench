# M4: cascade latency tuning, VAD sweep and 5-minute soak

Measured 2026-10-08, 17:30–21:45 CT, on hdx-lab with the new Playwright harness (`backend/eval/harness.py`). It drives the real SPA in headless Chrome with `?source=file` and plays fixtures from `docs/benchmarks/utterances.yaml` (24 EN + 24 ES; `make fixtures`, OpenAI TTS voices ash/sage/coral/verse, not the pipeline voice marin) as the microphone. Dev models only: `gpt-realtime-mini`; cascade `gpt-live-transcribe` → `gpt-5.4-nano` → `gpt-4o-mini-tts`. No `gpt-realtime`, no ElevenLabs. Raw per-turn rows are in `results/m4/*.jsonl`. Tables are produced by `python -m eval.summarize`, `eval.vad_table`, `eval.soak_report` and `eval.stt_wer`.

## How to read the numbers

- **H** = last voiced frame → first audible sample, measured in the browser (DESIGN §4).
- **PTT release (DESIGN A2/A5):** the harness releases 450 ms after the utterance's *last* voiced frame. Every PTT figure is given as measured and as **H−gap**, which subtracts the per-turn release gap.
- **Pipelining caveat (important for cascade):** the cascade commits at in-turn pauses ≥ 300 ms (FR-3.1). For multi-clause utterances, the first segment is already translated and synthesized when the user stops, so H is ≈ release gap + 60 ms. That is real ("speech end → first audio"), but it flatters the median. Two more columns isolate the hard case:
  - **tail** = when the *last* segment's audio is ready (server `tail_tts_first_byte` + browser commit offset; excludes ~40–60 ms network/playout; an estimate).
  - **short H** = the 8 short utterances per direction, which are mostly a single segment, so there's no head start.
- p50 / p90 are in ms.

## Cascade before / after (450 ms release, full set, both directions)

"Before" = the M3 configuration. "After" = M4 defaults: speculative MT on, first TTS chunk at a word boundary after 20 chars, TTS connection warm-up, STT `delay: low`. "After (minimal)" = the same with STT `delay: minimal`.

| Variant | n | H | H−gap | tail | tail−gap | short H | short H−gap |
|---|---|---|---|---|---|---|---|
| Before (M3) | 48 | 567 / 2164 | 111 / 1709 | 2080 / 2332 | 1622 / 1870 | 1962 / 2321 | 1507 / 1864 |
| **After (M4 default, delay low)** | 47 | 527 / 1620 | 71 / 1163 | **1578** / 1992 | 1122 / 1536 | **1375** / 1861 | 914 / 1407 |
| After, STT delay minimal | 46 | 530 / 1491 | 73 / 1037 | 1378 / 1726 | 923 / 1271 | 1130 / 1702 | 671 / 1244 |

By direction (before → after, default):

| Direction | H p50 | H−gap p50 | tail p50 | tail−gap p50 | short H p50 | short H−gap p50 |
|---|---|---|---|---|---|---|
| EN→ES | 567 → 525 | 111 → 70 | 2069 → 1657 | 1612 → 1200 | 1354 → 1021 | 899 → 567 |
| ES→EN | 827 → 527 | 371 → 73 | 2083 → 1492 | 1626 → 1038 | 2031 → 1375 | 1574 → 914 |

**Result:**
- Every percentile is under the 3 s cascade target.
- The hard case (the last segment, or a one-segment utterance) is now **~1.4–1.6 s p50 including the 450 ms release**, and ~0.9–1.1 s without it. That beats the 2 s aim at p50. p90 is 1.9–2.0 s.
- `delay: minimal` would save another ~0.2 s, but raises STT word error rate 2–3× (see "Quality check"), so it is not the default.

## What each change bought (24-utterance subset, 4 per size per direction)

| Variant | n | H | H−gap | tail | tail−gap | short H | short H−gap |
|---|---|---|---|---|---|---|---|
| Before (M3) | 24 | 580 / 2164 | 123 / 1709 | 2097 / 2332 | 1641 / 1870 | 2031 / 2164 | 1574 / 1709 |
| + TTS warm-up (4 pooled connections) | 24 | 527 / 2187 | 72 / 1732 | 2061 / 2584 | 1604 / 2127 | 2003 / 2262 | 1547 / 1806 |
| + STT delay minimal | 24 | 533 / 2262 | 76 / 1804 | 2039 / 2560 | 1584 / 2107 | 2096 / 2262 | 1642 / 1804 |
| + speculative MT | 24 | 526 / 1657 | 72 / 1204 | 1518 / 1826 | 1061 / 1370 | 1621 / 1755 | 1165 / 1297 |
| + first chunk at 20 chars | 24 | 533 / 1599 | 75 / 1143 | 1450 / 2004 | 993 / 1551 | 1472 / 1630 | 1018 / 1176 |
| spec + minimal + pause hint (150 ms) | 24 | 525 / 1745 | 70 / 1289 | 1552 / 1834 | 1095 / 1377 | 1669 / 1781 | 1212 / 1326 |
| spec + **low** + pause hint | 24 | 524 / 1915 | 68 / 1457 | 1777 / 1998 | 1322 / 1538 | 1778 / 1933 | 1321 / 1477 |
| Final default (low, spec, chunk 20) | 23 | 527 / 1613 | 71 / 1159 | 1495 / 2008 | 1042 / 1547 | 1523 / 1861 | 1068 / 1407 |

- **Speculative MT is the win (~−0.5 s on the tail).**
  - Why it works: probing the transcription socket showed that partials stream during speech. With `delay: minimal` the partial is complete at commit; with `low` the last word lands ~0.2 s after commit. Either way, the `completed` final arrives ~0.45–0.55 s after commit.
  - What it does: MT/TTS start on the partial and are held until the final matches.
  - Across 242 adoptions in the tuning runs there were **0 mismatches**. The cost is restarts when a later partial changes the text: 20 extra MT starts per 61 adoptions with minimal, more with low + hint.
- **First chunk at 20 chars:** ~−0.1 s on short turns. TTS time-to-first-byte barely depends on text length (`eval/tts_ttfb.py`: gpt-4o-mini-tts ≈ 530–700 ms whether 15 or 60 chars), so cutting the first chunk earlier mostly saves the MT streaming wait. The cost is a possible prosody seam at the cut. This needs a by-ear check during the demo run.
- **TTS warm-up and STT `delay: minimal` alone:** no measurable gain (within run-to-run noise).
- **Pause hint** (speculate at 150 ms of silence, before the 300 ms pause commit): no gain, and +65% speculative starts. It ships off (`?hint_ms=`).
- **TTS variants** (from `eval/tts_ttfb.py`, p50 of 3 rounds): gpt-4o-mini-tts with instructions 533–703 ms; without instructions 570–996 ms; `tts-1` 792–1424 ms. The current config stays.

What's left in the tail (default config, short utterances, ms after the final commit):
- STT-final-independent MT first token ≈ 250–450 (speculation starts at the pause commit, ~150 ms before the release);
- first chunk +100–150;
- TTS first byte +450–650.

TTS time-to-first-byte is now the largest stage.

## Cascade-haiku via OpenRouter (dev turns, 6 utterances)

| MT | n | H | H−gap | tail | tail−gap | short H | short H−gap |
|---|---|---|---|---|---|---|---|
| gpt-5.4-nano (same 6 ids, default run) | 6 | 521 / 525 | 66 / 69 | 1662 / 2008 | 1206 / 1547 | 930 / 1360 | 474 / 901 |
| `anthropic/claude-haiku-5.5` via OpenRouter (`provider.sort: latency`) | 6 | 516 / 791 | 59 / 333 | 2024 / 2142 | 1570 / 1686 | 1379 / 1967 | 922 / 1511 |

Haiku-via-OpenRouter adds ~0.35 s on the tail at this tiny n. Translations were good, e.g. "I have a really bad headache.", "Su presión arterial está un poco alta hoy…". One miss: "Moxifloxacino" for "amoxicillin", which STT had already heard as "a moxacillin". Usage was kept to these 6 turns; more runs belong to the final benchmark.

## Realtime PTT (gpt-realtime-mini, WebRTC, 24 utterances; unchanged in M4)

| | n | H | H−gap | short H | short H−gap |
|---|---|---|---|---|---|
| EN→ES | 12 | 976 / 1208 | 519 / 753 | 957 / 978 | 502 / 518 |
| ES→EN | 12 | 974 / 1469 | 518 / 1014 | 961 / 982 | 506 / 525 |
| All | 24 | 976 / 1277 | 519 / 822 | 960 / 978 | 504 / 518 |

## VAD silence-window sweep (12 utterances per cell, 2 per size per direction; no release gap in VAD mode)

| Mode | window | utterances | 1 turn | split | no turn / stuck | H p50 / p90 (short+medium, 1 turn) | H p50 (all done) |
|---|---|---|---|---|---|---|---|
| Realtime (server_vad, WebRTC) | 300 ms | 12 | 6 | 1 | 5 | 985 / 988 (n=6) | 982 |
| Realtime (server_vad, WebRTC) | 400 ms | 12 | 6 | 1 | 5 | 1119 / 1181 (n=6) | 1137 |
| Realtime (server_vad, WebRTC) | 500 ms | 12 | 8 | 1 | 3 | 1541 / 1632 (n=8) | 1535 |
| Cascade (browser VAD) | 300 ms | 12 | 4 | 8 | 0 | 1599 / 1897 (n=4) | 460 |
| Cascade (browser VAD) | 400 ms | 12 | 5 | 7 | 0 | 1636 / 2032 (n=5) | 519 |
| Cascade (browser VAD) | 500 ms | 12 | 8 | 4 | 0 | 1524 / 1753 (n=8) | 568 |

"1 turn" = the utterance became exactly one turn. "split" = several turns. "no turn / stuck" = the harness saw no completed turn within 40 s. The "all done" median includes split turns, whose later part benefits from pipelining. Realtime rows: `results/m4/rt_vad2_*`. Cascade rows: `cas_vad3_*` (after the queueing fixes below).

Transcript WER in VAD mode is 0.16 (realtime, 400 ms) and 0.31–0.39 (cascade). It is dominated by deletions: speech that falls inside a gated playback window is dropped.

- **Realtime `server_vad`:** H grows with the window, as expected (300 → 500 ms: ~1.0 → ~1.5 s), and 400 ms is the balance. The "no turn / stuck" column is long, multi-sentence utterances. Server VAD splits them at the 0.5–0.9 s sentence pauses. The mic is gated while the first part's translation plays, so the rest of the speech is lost or a response collides (`conversation_already_has_active_response`). Two harness/client bugs found here were fixed (see below). The remaining failures are the inherent clash between VAD turn-taking and mic gating during playback with long monologues. **PTT stays the recommended mode for long turns.**
- **Cascade browser VAD:**
  - At 300 and 400 ms, short and medium utterances get split at in-sentence pauses: 4 and 3 of 8. Splits mean fragment translations ("¿Tienes? / ¿Alguna alergia?").
  - **At 500 ms none are split, and single-turn H is ~1.5 s p50.** 500 ms is the recommended cascade window. For Realtime, 400 ms balances latency (1.1 s) against splits.
  - Long monologues hit the same playback-gating limit as Realtime: later sentences are lost while the first part plays.
  - One TTS 3 s watchdog timeout occurred in 36 cascade VAD utterances.

## 5-minute soak (stable session)

| | Realtime PTT (mini, WebRTC) | Cascade PTT (default config) |
|---|---|---|
| Session | 300 s, 36 turns, 1 session, 1 transport (`created=1`) | 303 s, 30 turns, 1 session, 1 transport |
| Turns failed / errors / reconnects | 0 / 0 / 0 | 0 / 0 / 0 |
| JS heap (start → end) | 6.3 → 8.3 MB (oscillating 6.1–8.5) | 5.8 → 10.0 MB (turn history kept in the UI store) |
| Backend RSS | 47.8–48.7 MB, flat | 46.2–47.7 MB, flat |
| Audio graph nodes | 6 constant | 5 constant |
| Latency drift vs the same utterances in a fresh session | H +9 ms (first half), +26 ms (second half) | tail +12 ms / +42 ms |
| STT WER over the soak | 0.021 | 0.022 |

There were no leaks, disconnects or meaningful drift in either mode. The cascade heap growth is the per-turn transcript and waterfall history (~140 kB/turn), which the session keeps by design.

## Quality check (STT WER vs the fixture text; `eval.stt_wer`)

| Run | STT delay | WER |
|---|---|---|
| Before (M3), 48 turns | low | 0.030 |
| TTS warm (24) / spec + low + hint (24) | low | 0.015 / 0.018 |
| STT minimal (24) / spec + minimal (24) / + hint (24) | minimal | 0.056 / 0.033 / 0.047 |
| After, default (47) | low | **0.029** |
| After, minimal (46) | minimal | 0.074 |
| Realtime mini, side transcript (24) | – | 0.021 |

`delay: minimal` makes STT faster but less accurate. Errors look like "Thank you For waited", "Divo aquí", and a 0.15 WER in a minimal-config soak that was aborted and re-run with `low`. For medical/legal interpreting the default stays `low`; `STT_DELAY=minimal` is an option worth ~0.2 s.

Segment-level translation also costs quality when a TTS voice pauses mid-sentence. For example, "Do you have / any allergies?" became "¿Tienes? ¿Alguna alergia?". That behaviour predates M4 (pause commits at 300 ms). It is a candidate for the final write-up and for tuning (`pauseCommitMs`).

## Reliability notes

- Provider first-output watchdogs (3 s) fired in 3 of 96 tuned cascade turns: 2 MT, 1 TTS. Before M4 it was 0 of 48. These look like slow OpenAI tails. A link to speculation (more concurrent requests) is not ruled out at this sample size. The turns failed with a clear error banner, and the harness recorded them as failures. A hedged retry (second request at ~1.5 s) is the obvious next mitigation; it was not implemented in M4.
- Bugs found by the M4 harness and fixed:
  - The file source sent pure digital silence, so WebRTC went quiet and server VAD never ended the turn. Fix: a −60 dBFS noise floor.
  - Realtime VAD turns stayed "playing" forever when two responses shared one output-buffer start/stop. Fix: earlier turns end when the buffer stops for a later one.
  - Cascade VAD back-to-back turns cancelled the previous turn's translation ("superseded"). Fix: queue behind a committed turn, keep the audio in order, and start the next STT only after the previous turn's STT finishes on the shared socket.
