# Langfuse tracing off vs on: latency A/B (2026-10-10, A20, branch feat/langfuse)

**Verdict: tracing adds no measurable latency.** Cascade short-turn H p50 was 1732 ms (off) vs 1773 ms (on). That is +41 ms, inside run-to-run noise and below the ~100 ms threshold. Realtime-mini went one way in the first run (off 980 vs on 1136 ms, n=6) and the other way in a larger follow-up (off 1288 vs on 1151 ms, n=18). Combined realtime: off 1278 vs on 1150 ms (n=24 each). By design, nothing on the audio path touches Langfuse: the browser posts the turn record after playback, and the server only enqueues.

**Setup** (same method as `../recording-ab/`)
- One image (`c1dad9f`), two containers side by side: `off` (default) and `on` (`LANGFUSE_ENABLED=1`, Langfuse Cloud US, transcripts on, keys mounted as files).
- Cascade default (`gpt-live-transcribe` → `gpt-5.4-nano` → `gpt-4o-mini-tts`), PTT with a 450 ms release, no ElevenLabs.
- Arms alternated off, on, off, on (2 rounds each). Every round used 14 utterances, with en-s01 and en-s02 as unscored warm-ups. 12 were scored, 10 of them short. Each round also ran 3 realtime-mini turns (en-s03, es-s03, en-s04).
- Realtime follow-up (`run_rt.sh`): 6 turns per round, arms alternated on, off × 3, with on first to counter order effects.
- Langfuse saw every traced turn, and the `on` server log shows only `207` ingestion responses (0 warnings, 0 rejected events).

| arm | cascade n (short) | short H p50 | short H p90 | short H−gap p50 | all-12 H p50 / p90 | tail p50 |
|---|---|---|---|---|---|---|
| off | 24 (20) | 1732 | 2137 | 1275 | 1698 / 2137 | 1726 |
| on  | 24 (20) | 1773 | 2295 | 1318 | 1736 / 2295 | 1741 |

| realtime-mini | run 1 n / p50 / p90 | follow-up n / p50 / p90 | combined n / p50 / p90 |
|---|---|---|---|
| off | 6 / 980 / 1008 | 18 / 1288 / 1424 | 24 / 1278 / 1424 |
| on  | 6 / 1136 / 1246 | 18 / 1151 / 1363 | 24 / 1150 / 1363 |

All values are ms, measured by the harness (H runs from the last voiced frame to the first audible sample). The p90 values at n=20 are provider noise.

**Fail-open check:** a container pointed at an unreachable host (`http://10.255.255.1:9`) completed 3/3 cascade turns normally (H 1646–1951 ms). The log shows one rate-limited warning (`ConnectTimeout`, 7 events dropped). Unit tests cover a stalled host (the request path stays under 50 ms per call while the flusher times out), a refused connection, 207 partial rejections and a full queue.

Files: `run.sh`, `run_rt.sh`, `analyze.py`, `summary.json`, `realtime-followup.json`, `2026-10-10-langfuse-ab.csv`.
