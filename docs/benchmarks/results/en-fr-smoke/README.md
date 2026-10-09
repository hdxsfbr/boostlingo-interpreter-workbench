# EN↔FR onboarding smoke (9 Oct 2026, DESIGN A14)

Shows that the newly configured pair works end to end. **Not a benchmark: no quality claims.**

| Mode | Utterance | Heard | Spoken | H (ms) |
|---|---|---|---|---|
| realtime (gpt-realtime-mini, WebRTC) | en-s01 | Do you have any allergies? | Avez-vous des allergies ? | 1452 |
| realtime (gpt-realtime-mini, WebRTC) | fr-s01 | J'ai mal à la tête depuis hier. | I have had a headache since yesterday. | 1261 |
| cascade (gpt-live-transcribe → gpt-5.4-nano → gpt-4o-mini-tts) | fr-s01 | J'ai mal à la tête Depuis hier. | I have a headache since yesterday. | 2494 |

Cost: realtime-mini $0.0035, cascade $0.0024, plus <$0.001 to synthesise the 4 fixtures (OpenAI TTS).

Reproduce:

    python scripts/make_fixtures.py --utterances docs/benchmarks/pairs/en-fr.yaml --out data/fixtures-en-fr
    cd backend && python -m eval.harness --mode realtime --rt webrtc --rt-model gpt-realtime-mini \
      --pair en,fr --dirs en,fr --utterances ../docs/benchmarks/pairs/en-fr.yaml --fixtures ../data/fixtures-en-fr --ids en-s01,fr-s01
