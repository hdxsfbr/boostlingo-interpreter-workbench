# M2 Realtime smoke run (browser-measured)

2026-10-08, ~17:15–17:30 PT, hdx-lab, `make up` stack, headless Chrome (`backend/eval/browser_smoke.py`) with TTS-generated WAVs as the fake microphone (EN: "I have had a headache for three days."; ES: "Me duele el pecho cuando respiro profundo."). Model **`gpt-realtime-mini`** (dev model; final runs with `gpt-realtime` are M4). **H** = last voiced mic frame → first audible output sample at the shared output tap, both on the browser clock.

**Release policy.** PTT is released 450 ms after the last voiced frame, so H *includes* ~455 ms of release lag; "system" = H − release lag. 450 ms (not M1's 300 ms) because the ES clip has a 350 ms in-sentence pause: at 300 ms the harness released mid-sentence ("Me duele el pecho."), and the model then *answered* the fragment in 2/5 turns. The M1 ES cascade numbers had the same truncation.

## PTT (default)

| transport | direction | n | H p50 | H max | system p50 | translations |
|---|---|---|---|---|---|---|
| WebRTC (ephemeral secret) | EN→ES | 5 | **950 ms** | 996 | 493 | 5/5 correct |
| WebRTC | ES→EN | 5 | **1014 ms** | 1091 | 556 | 5/5 correct |
| WS relay (fallback) | EN→ES | 5 | 1037 ms | 1059 | 573 | 5/5 correct |
| WS relay | ES→EN | 5 | 893 ms | 900 | 437 | 5/5 correct |
| auto, WebRTC blocked → relay | ES→EN | 2 | 1114 ms | 1132 | 655 | 2/2 correct |
| WebRTC, release 300 ms | EN→ES | 5 | 828 ms | 836 | 516 | 5/5 correct |

All PTT turns are inside the **1.5 s** target. Browser marks (ms after speech end, WebRTC EN→ES, typical): commit sent ≈ 460 (= release lag) → `response.created` ≈ 525 → first output transcript ≈ 690 → `output_audio_buffer.started` ≈ 800 → first audible ≈ 950. The model's own time from commit to first audio is ≈ 0.35–0.4 s; WebRTC jitter buffer + playout adds ≈ 0.15 s.

## VAD (server_vad, silence_duration_ms 400)

| transport | direction | n | H p50 | H max |
|---|---|---|---|---|
| WebRTC | EN→ES | 6 (2 runs) | 1473 ms | 1563 |
| WS relay | ES→EN | 4 | 1275 ms | 1461 |

VAD H includes the 400 ms silence window plus the server's detection lag (`speech_stopped` arrives ≈ 600–700 ms after the last voiced frame), so VAD sits at the edge of the 1.5 s target. A 300/400/500 ms sweep is M4 work (DESIGN §8).

## Cascade, same harness and release policy (for reference)

| direction | n | H p50 | H max | note |
|---|---|---|---|---|
| EN→ES | 5 | 2993 ms | 3258 | STT final 0.42–0.65 s, MT 1st token 0.96–1.96 s, TTS 1st byte 2.16–2.73 s after commit |
| ES→EN | 5 | 517 ms | 519 | the 350 ms pause triggered an in-turn commit, so segment 1 was ready at speech end; the honest number is the tail (`tail_tts_first_byte` 1.36–2.04 s server-side, p50 1.76 s) |

Cascade EN→ES is slower than in M1 (2374 ms p50): +150 ms release lag and noisy MT first-token times (one 1.96 s outlier). Cascade tuning is M3/M4.

## Robustness checks (all PASS)

- **Mic gating:** sampled while the translation plays, WebRTC uplink track `enabled=false` in PTT and VAD (`gate_during_playback`), so the model never hears itself; the local capture/VAD keeps running on the original track.
- **Mode switch leaks:** 2 realtime turns then 6 switches realtime ↔ cascade: exactly 1 open transport afterwards (7 created), engine nodes back to 5 + 1 remote, mic live.
- **Barge-in:** a press while a translation plays stops it: audio ended 52 ms after the press over WebRTC (`output_audio_buffer.clear` round trip), 13 ms over the relay (local flush; late frames of the cancelled turn dropped).
- **History pruning:** the server confirmed `conversation.item.deleted` for the older turn after each response (recorded in `contract/fixtures/openai/realtime_webrtc_three_turns.json`).
- **Relay fallback:** with the SDP POST blocked, `auto` falls back to the relay and shows a non-blocking notice.

Raw per-turn output: [`raw/m2/`](raw/m2/).

Reproduce:
```bash
cd backend
python -m eval.browser_smoke --wav en.wav --mode realtime --rt webrtc --speaker A --turns 5 --release-silence-ms 450
python -m eval.browser_smoke --wav es.wav --mode realtime --rt relay  --speaker B --turns 5 --release-silence-ms 450
python -m eval.browser_smoke --wav en.wav --mode realtime --turn-mode vad --turns 4
python -m eval.browser_smoke --wav en.wav --mode realtime --turns 2 --switches 6 --barge-in
python -m eval.browser_smoke --wav es.wav --mode realtime --rt auto --block-webrtc --speaker B --turns 2
```
