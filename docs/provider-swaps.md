# Provider swaps (M3): what a swap costs

The brief asks for provider flexibility. DESIGN §2 claims **a swap = one adapter file + one config value + its contract test**, with the orchestrator (`backend/app/cascade/session.py`) and the UI untouched. This page records the files each M3 swap actually touched (from `git show --stat`).

## How to swap

- **Default for every session:** `config/app.yaml` → `cascade.mt` / `cascade.tts`, or env `CASCADE_MT=anthropic|openrouter|openai` and `CASCADE_TTS=elevenlabs|openai`.
- **Per session (FR-9):** use the *Translator* / *Voice* selectors in the UI (cascade mode), or `?mt=…&tts=…` in the URL. Only the cascade WebSocket reconnects.
- `/healthz` → `swaps` lists each option, whether it's ready, and the reason when it isn't.

## Files touched per swap

| Swap | Adapter + contract test | Wiring | Config / secrets | Orchestrator or UI touched? |
|---|---|---|---|---|
| **MT → Anthropic `claude-haiku-5-5`** | `providers/mt/anthropic.py` (88 lines), `tests/contract/test_anthropic_mt.py`, fixture `contract/fixtures/anthropic/…synthetic.json` | +1 line in `providers/registry.py`; constructor-kwargs block + enable gate in `cascade/ws_pipeline.py` | `providers.anthropic` in `app.yaml`; `ANTHROPIC_WORKSPACE_ID` in `.env.example`, `setup_env.py`, `config.py` | no |
| **TTS → ElevenLabs Flash v2.5** | `providers/tts/elevenlabs.py` (170 lines), `tests/contract/test_elevenlabs_tts.py`; plus the credit guard `core/budget.py` + `tests/unit/test_budget.py` | +1 line in the registry; kwargs + guard wrapping in `ws_pipeline.py` | `providers.elevenlabs` (caps, voices, prewarm) in `app.yaml`; key is a Compose file secret (since M0) | no |
| **MT → OpenRouter** | `providers/mt/openrouter.py` (59 lines), `tests/contract/test_openrouter_mt.py` | +1 line in the registry; kwargs in `ws_pipeline.py` | `providers.openrouter` in `app.yaml`; `OPENROUTER_API_KEY` in `.env.example`, `config.py` | no |

**Honest count.** Besides the adapter, its test and the config value, each swap needs a one-line registry entry (adapters are imported lazily, so optional providers need no keys or deps) and a few lines in `build_providers` mapping config to constructor arguments. `CascadeSession`, the event contract and the UI did not change for any swap. The UI selector (FR-9) was added once and is generic over `/healthz` → `swaps`.

## Status of each swapped provider (2026-10-08)

| Provider | Live status | Why |
|---|---|---|
| Anthropic Haiku | **disabled** (`providers.anthropic.enabled: false`) | The one allowed validity check, sent *with* `anthropic-workspace-id`, returned **HTTP 400**. Enable with `ANTHROPIC_ENABLED=1` after a passing check. |
| ElevenLabs Flash | **disabled** (`ELEVENLABS_ENABLED=0`) | Free-tier credits are reserved for the final benchmark subset and the demo. Never called in tests or dev. |
| OpenRouter | **no key loaded** | A key file exists on hdx-lab, but OpenRouter use wasn't authorised for this run, so `setup_env.py` doesn't load it. |
