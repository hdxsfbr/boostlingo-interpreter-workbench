# Observability: Langfuse tracing (DESIGN A20, branch `feat/langfuse`)

Optional. **Off by default**; production (Railway) does not run it.

## What is traced

| Langfuse object | From | Contents |
|---|---|---|
| **Trace** `interpreter-session` (one per browser session, `sessionId` = the app's session id) | each finished turn's record (`POST /api/turns`) | tags `mode:…`, `pair:…`, `commit:…` (+ `source:harness` for automated runs); metadata: provider names, model ids, pipeline, prompt version |
| **Span** `turn N · mode · src→tgt` | same record | input/output text, status, **all raw browser + server latency marks**, stage times on the speech-end clock (same formula as the UI, A18), early stages, cost estimate, usage |
| **Generations** `stt`, `mt`, `tts` (cascade) / `realtime` | same record | model, provider, start / first output (`completionStartTime`) / end on the speech-end clock, usage (STT seconds, MT tokens, TTS characters, Realtime tokens), cost estimate from `config/pricing.yaml`, `early` flag |
| **Span** `playback` | same record | audio sent → first audible (browser) |
| **Score** `H_ms` | same record | the headline latency of the turn (equals the UI's "first audible") |
| **Trace** `experiment · setup · utterance` (one per sentence per setup, `sessionId` = `exp-<id>`) | Experiments tab, after a run | tags `experiment:…`, `setup:…`, `commit:…`; metadata: models, prompt version, run config, reference; scores `H_ms`, `H_minus_lag_ms`, `src_wer`, `chrF`, `cost_usd` (and `judge` if present) |
| **Trace** `review · set · clip` | Review tab, on each save | scores `human_<dimension>` (1–5), rater in the comment |

Because the trace is built from the record the UI already shows and logs, the Langfuse numbers equal the Latency card's.

Not traced: the audio pipeline itself. The server never calls Langfuse while a turn is running; the browser posts the turn record after playback.

## Never on the audio path, fail-open

- `emit()` only appends to an in-memory queue (thread-safe, no I/O, never raises).
- One background task sends batches (`max_batch` 50, every `flush_interval_s` 2 s) to `/api/public/ingestion`, with a short timeout plus a hard deadline.
- If Langfuse is down, slow or rejects events, batches are dropped and counted; a warning is logged at most once a minute. A full queue (`max_queue` 2000) drops new events. The app keeps working (tested with an unreachable host and a stalled one).
- Measured: no latency impact (see `docs/benchmarks/results/langfuse-ab/summary.md`).

## Reliability and housekeeping

- **One retry** on 429, 5xx or a timeout (0.5 s backoff, or a short `Retry-After`), then the batch is dropped. Other 4xx errors are not retried.
- **Review deletes:** deleting a rater's ratings in the Review tab also deletes their `human_*` scores in Langfuse. Score ids are deterministic, and the deletes are queued, best effort and fail-open.
- **Status:** the protected `/api/health` reports `tracing.langfuse` with `enabled`, host, `send_text`, `retention_days` and the counts `queued`, `sent`, `retried`, `rejected`, `dropped` and `deleted`. No keys.
- **Retention:** `retention_days` (default 30) runs a daily sweep that deletes traces older than that through the public API. The sweep is **project-wide**, so give this app its own Langfuse project. Also set retention in Langfuse itself where your plan allows it.
- **Hosted default:** when `PORT` or `RAILWAY_ENVIRONMENT/PROJECT_ID/SERVICE_ID` is set, `send_text` defaults to **off** unless `LANGFUSE_SEND_TEXT` says otherwise. Production (Railway) runs with tracing **disabled**.
- **Experiments:** the harness that an Experiment launches tags its own session traces with `experiment:<id>`, so they link to that experiment's per-utterance traces (`sessionId exp-<id>`).
- **Cost:** a single pricing module (`backend/app/core/pricing.py`) prices both the M5/Experiments rows and the live per-stage costs. Realtime cost includes the side transcription (`gpt-4o-transcribe`, billed per minute of the push-to-talk hold).
- **Scores:** `H_ms` is the headline (first audio of the last sentence, A21); `first_audible_ms` is the literal first sound.

## Configure

`config/app.yaml` → `observability.langfuse` (`enabled: false`, `host`, `send_text`, batching). Env overrides:

| env | meaning |
|---|---|
| `LANGFUSE_ENABLED=1` | turn it on |
| `LANGFUSE_HOST` | e.g. `https://us.cloud.langfuse.com` (Cloud US), `https://cloud.langfuse.com` (EU) or a self-hosted URL |
| `LANGFUSE_PUBLIC_KEY_FILE` / `LANGFUSE_SECRET_KEY_FILE` | key files (preferred); or `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` |
| `LANGFUSE_SEND_TEXT=0` | send numbers only: transcripts, translations, references and review notes are stripped |

Locally: `make up-langfuse` (overlay `docker-compose.langfuse.yml` mounts `~/.config/agentforge/langfuse_*` as file secrets). `make up` stays untraced.

Trace links need the trace time: `https://<host>/project/<project id>/traces/<trace id>?timestamp=<trace ISO time, URL-encoded>` (without it the Langfuse UI says "trace not found"); `scripts/langfuse/lf_api.trace_url()` builds them.

Check what arrived: `python3 scripts/langfuse/count.py --since <UTC ISO>`; render one trace tree: `python3 scripts/langfuse/render_trace.py <trace_id> out.png`.

## Privacy: healthcare / PHI caveat

- **Audio is never sent.** Only text and numbers.
- **Transcripts are sent by default** (`send_text: true`) because this is a local test tool with synthetic or consented speech. In a real clinical setting the transcripts are PHI.
- Before tracing real patient conversations you would need, at least: a **BAA** with the observability vendor (or **self-host** Langfuse inside your own boundary), **redaction** of identifiers before sending (or `send_text: false`), and a **retention** limit configured in Langfuse that matches your policy. Also restrict who has access to the Langfuse project.
- Keys are secrets: keep them in files or a secret store, never in `app.yaml` or git.
