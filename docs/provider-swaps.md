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
| Anthropic Haiku (direct) | **disabled, key dropped** (`providers.anthropic.enabled: false`; `setup_env.py` no longer loads the key) | M3 check: HTTP 400. M4's one diagnostic call showed the cause: `invalid_request_error` "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits." Andre then dropped the direct route (DESIGN A3); the adapter stays in code, mock-tested. |
| ElevenLabs Flash | **disabled** (`ELEVENLABS_ENABLED=0`) | Free-tier credits are reserved for the final benchmark subset and the demo. Never called in tests or dev. |
| OpenRouter → Haiku (`anthropic/claude-haiku-5.5`) | **enabled: this is `cascade-haiku`** (`CASCADE_MT=openrouter` or the per-session selector) | Approved by Andre in M4; `setup_env.py` loads the key into the mode-600 `.env`. One check through the adapter (`eval/openrouter_check.py`): **HTTP 200**, served `anthropic/claude-haiku-5.5`. Benchmarks and demo only; tests mock it. |
