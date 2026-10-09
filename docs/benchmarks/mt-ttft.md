# Cascade MT model choice by measured TTFT (M1)

Measured 2026-10-08 ~17:30 PT from hdx-lab with `backend/eval/mt_ttft.py`: OpenAI Responses API, streaming, warm keep-alive connection, `reasoning.effort: none` where supported, 10 utterances (5 EN→ES, 5 ES→EN, medical/legal flavour) × 2 rounds, models interleaved. TTFT = request sent → first text delta.

| model | n | TTFT p50 ms | TTFT p90 ms | total p50 ms |
|---|---|---|---|---|
| `gpt-6-luna` | 20 | 610 | 1786 | 827 |
| `gpt-5.4-nano` | 20 | **412** | **709** | **628** |
| `gpt-4.1-nano` (reference, no reasoning param) | 20 | 533 | 1249 | 748 |

**Decision:** `gpt-5.4-nano` is the cascade MT default (`config/app.yaml` → `providers.openai.model`). It has the lowest median and, more importantly for a < 2 s budget, the tightest tail. Spot-checked output quality was comparable across the three (one register slip in `gpt-5.4-nano`: "tráigame" for "bring"). Caveats: a single evening's sample from one network location; `gpt-5.4-nano` is deprecated with an Apr 1 2027 shutdown (switching is a config change, `MT_MODEL=gpt-6-luna`). Re-measure in M4 alongside `claude-haiku-5-5`.
