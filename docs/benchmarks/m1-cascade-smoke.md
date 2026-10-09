# M1 cascade smoke run (browser-measured)

2026-10-08 ~17:10 PT, hdx-lab, `make up` stack, headless Chrome driven by `backend/eval/browser_smoke.py` with a TTS-generated WAV as the fake microphone (so WER here is not meaningful). Pipeline: `gpt-live-transcribe` (delay low) → `gpt-5.4-nano` → `gpt-4o-mini-tts`. PTT released 300 ms after the last voiced frame; **H** = speech end (last voiced mic frame) → first audible output sample, both on the browser clock, so H *includes* that 300 ms release lag. Server marks are ms after the server received the final commit.

| direction | n | H p50 | H max | H − release lag p50 | STT final | MT 1st token | TTS 1st byte |
|---|---|---|---|---|---|---|---|
| EN→ES ("I have had a headache for three days.") | 5 | 2374 ms | 2450 ms | 2067 ms | 361–552 | 839–1568 | 1714–2084 |
| ES→EN ("Me duele el pecho…") | 5 | 1965 ms | 2951 ms | 1654 ms | 433–801 | 920–1322 | 1474–2599 |
| loopback (transport + playout floor) | 4 | 444 ms | 448 ms | 36 ms | – | – | – |

Reading: single-segment turns are inside the 3 s limit but above the 2 s aim. The budget goes roughly STT ≈ 0.5 s, MT TTFT ≈ 0.5–0.9 s, TTS first byte ≈ 0.4–1.1 s. When a turn has an in-turn pause, the first segment is translated and synthesised while the speaker is still talking, so H falls to ~0.5 s and the honest number is the **tail** (`tail_tts_first_byte`, 1.5–2.0 s); both are recorded per turn.

Tuning candidates for M4 (not done yet): STT `delay: minimal`; start MT from the accumulated deltas at commit instead of waiting for `completed` (~0.4 s); a shorter first TTS chunk; ElevenLabs Flash (published TTFB 100–150 ms) as the TTS swap.
