# Recording off vs on: cascade latency A/B (2026-10-08, for Butler)

**Verdict: recording adds no measurable latency.** Short-utterance H p50 differs by 4 ms (1785 vs 1781 ms), which is far below the ~100 ms threshold, and the tail did not shift (1733 vs 1720 ms). No fix was needed.

**Setup**
- Default cascade (`gpt-live-transcribe` → `gpt-5.4-nano` → `gpt-4o-mini-tts`), PTT with a fixed 450 ms release, no ElevenLabs, one image (HEAD `f264403`).
- Two containers ran side by side: `off` (default config) and `on` (`RECORDING_ENABLED=1`, toggle ticked through `?record=1`).
- The arms alternated off, on, off, on, so each arm got 2 rounds. Each round was a fresh browser session.
- The same 14 utterances ran every round. The first two (en-s01, en-s02) are **unscored warm-ups**. The 12 scored ones are en-s03..s07, en-m01, es-s01..s05 and es-m01, so 10 are short.
- The `on` arm wrote all 56 WAVs (2 sides × 14 turns × 2 rounds); the `off` arm wrote none.

| arm | n (scored, done) | short n | short H p50 | short H p90 | short H−gap p50 | short tail p50 | all-12 H p50 / p90 | all-12 tail p50 |
|---|---|---|---|---|---|---|---|---|
| off | 24 | 20 | 1785 | 2190 | 1329 | 1733 | 1770 / 2402 | 1762 |
| on  | 24 | 20 | 1781 | 2077 | 1326 | 1720 | 1752 / 2120 | 1720 |

All values are ms. H is the time from the last voiced frame to the first audible sample (browser clock); H−gap subtracts the 450 ms release gap. The tail is `tail_est_ms`: when the last segment's audio starts after the final commit, a server-mark estimate. The short H p50 matches M5's fragment-merge short-turn figure (~1.8 s). The p90 difference (on lower) is provider noise at n=20.

**Why recording is cheap:** per frame it only appends bytes to an in-memory list (source on receive, target on send). The WAV write happens when the turn ends, after the last audio frame has gone out, so it is never between speech end and first audio.

Raw rows: `2026-10-08-recording-ab.csv`; the scripts used: `run.sh`, `analyze.py`.
