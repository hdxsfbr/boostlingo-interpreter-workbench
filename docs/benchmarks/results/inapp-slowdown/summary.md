# In-app cascade slowdown check (9 Oct 2026)

**Question.** The first Experiments-tab smoke measured cascade-openai at H p50 2261 ms on 6 short utterances (en/es s01–s03). M5 measured 1690 ms on the same ids. Is the in-app runner slower?

**Answer: no. The 2261 ms run was provider-side noise in TTS first-byte time, not the runner.** That smoke had a median TTS first byte (tts_request → tts_first_byte, server clock) of 1000 ms against ~600 ms in every other run, while STT, MT and the release gap were normal. Every later run, wherever the browser ran, landed at 1622–1781 ms, as M5 did.

| Run | n | H p50 | H max | H−gap p50 | release lag p50 | STT final p50 | TTS first byte p50 / max | $ |
|---|---|---|---|---|---|---|---|---|
| M5 (host CLI, 8 Oct) | 12 | 1690 | 2419 | 1233 | 457 | 600 | 620 / 1038 | 0.0231 |
| **App runner, smoke #1 (after realtime-mini)** | 6 | **2261** | 2959 | 1806 | 456 | 518 | **1000** / 1145 | 0.0116 |
| CLI on host, pass 1 | 6 | 1622 | 2050 | 1166 | 455 | 589 | 591 / 636 | 0.0113 |
| CLI in container, pass 1 | 6 | 1697 | 1976 | 1243 | 455 | 669 | 662 / 926 | 0.0112 |
| CLI on host, pass 2 | 6 | 1781 | 1978 | 1324 | 456 | 637 | 649 / 956 | 0.0117 |
| CLI in container, pass 2 | 6 | 1749 | 2165 | 1292 | 455 | 687 | 661 / 792 | 0.0118 |
| App runner, cascade only | 6 | 1710 | 2338 | 1255 | 455 | 700 | 596 / 912 | 0.0116 |
| App runner, smoke #2 (same config as #1) | 6 | 1711 | 2359 | 1256 | 455 | 671 | 587 / 992 | 0.0116 |

All latencies are in ms. Every run used the same running app (`make up`, default config). The host and container CLI runs alternated.

**Ruled out.**
- *Harness location:* the CLI on the host (google-chrome) and in the container (Playwright Chromium) agree within noise (1622/1781 vs 1697/1749).
- *The runner path:* the app runner gives 1710 alone and 1711 after realtime-mini, in the smoke's exact config.
- *Flags:*
  - The in-app command is `--mode cascade --mt openai --tts openai --ids … --dirs en,es --repeat 1 --profile cascade-openai`. M5's was `--profile cascade-openai --record …`, which resolves to the same providers (the page reports `openai_live / openai / openai` in both).
  - The release gap is 455–457 ms in every run.
  - Speculation, fragment merge, hedge (1.5 s) and chunking come from the server config, which the runner doesn't touch. `spec_hit` marks appear in all runs.
  - The only difference is `--record` (M5 also saved the output audio), which can only add work to M5.
- *CPU:* the container has no CPU or memory limit (NanoCpus 0) on a 32-core host. docker stats peaked at 95% of one core during the runs (load average < 1).

**Takeaway.** A 6-utterance p50 can swing by ~500 ms between runs when the TTS provider has a slow spell. Use more utterances or passes before reading differences. The Experiments tab now says so when a setup has fewer than 12 turns.

API spend for this check: $0.0801 (cascade $0.0692 over 6 runs, plus realtime-mini $0.0111 in smoke #2). Raw rows are `*.jsonl` here; the table is `summary.csv`.
