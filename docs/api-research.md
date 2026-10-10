# API research: AI Interpreter Workbench (Realtime vs Cascade)

**Last checked: Oct 8, 2026.** Sources were read on that date. Prices, model names and limits change often, so re-check them before quoting numbers in `docs/comparison.md`.

**Scope and assumptions**
- Language pair: English ↔ Spanish, both directions. The brief requires "minimum: English ↔ Spanish" ([assignment.pdf](../sources/assignment.pdf), FR-5).
- Stack: Python backend (FastAPI likely) and a TypeScript browser frontend. This follows Andre's latest decision, relayed by Butler. **Note:** `docs/PRD.md` v0.1 still proposes ASP.NET Core (§9) with stack question Q1 open. Update the PRD to match.
- Providers: OpenAI, Anthropic, ElevenLabs, OpenRouter, or local/free tools only. The brief also lists Deepgram, AssemblyAI, Soniox, DeepL, Azure and Polly, but they are out of scope by Andre's choice, so the PRD's Q2 suggestion of Deepgram/DeepL no longer applies.
- Cross-check: this doc was checked against local copies of `docs/PRD.md` and `sources/assignment.pdf` found on the shared box (`/workspace/boost/repo`, captured 2026-10-08). They were **not** fetched from GitLab, because no `glab`/GitLab token is configured. Whether those copies match GitLab HEAD is unverified.
- Notation: "(unverified)" or "Uncertain:" marks anything not confirmed by a source. "Estimate" marks my arithmetic on sourced prices.

---

## Key recommendations

1. **Realtime mode: browser WebRTC straight to OpenAI, using an ephemeral client secret minted by FastAPI.**
   - The secret comes from `POST /v1/realtime/client_secrets` with `session.type: "realtime"`.
   - Use `gpt-realtime-mini` in development and `gpt-realtime` for final numbers.
   - OpenAI recommends WebRTC over WebSockets for browser clients ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)).
2. **Make the voice agent act as a strict interpreter.**
   - `output_modalities: ["audio"]` plus tight interpreter instructions with an explicit language policy.
   - `server_vad` with `create_response: true`, and `silence_duration_ms` tuned down from the 500 ms default. Consider `interrupt_response: false` so translations aren't cut off.
   - Input transcription on for the source text; `response.output_audio_transcript.*` for the target text.
   - Prune old conversation items. History is re-billed on every turn and can tempt the model to "answer" instead of translate ([cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)).
3. **Benchmark `gpt-realtime-translate` as an optional third variant ("Realtime-Translate"), not as the required Realtime mode.**
   - It is OpenAI's dedicated streaming speech-to-speech translation model, at $0.034/min, on its own `/v1/realtime/translations` endpoint ([guide](https://developers.openai.com/api/docs/guides/realtime-translation)).
   - The brief mandates `gpt-realtime` for Realtime mode, so offer this one as a comparison data point only.
4. **Cascade mode: browser → FastAPI WebSocket (PCM16) → STT → streaming LLM → streaming TTS → browser.**
   - **STT:** OpenAI `gpt-live-transcribe` realtime transcription. It needs no VAD of its own; commit each turn from your VAD. Start with `delay: "low"` or `"minimal"`. Alternative: ElevenLabs `scribe_v2_realtime` with VAD commits.
   - **Translation:** start on each committed segment with `gpt-5.4-nano` (reasoning `none` is its default), `gpt-6-luna` with `reasoning.effort: "none"`, or `claude-haiku-5-5` with `thinking: {type: "disabled"}`.
   - **TTS:** ElevenLabs `eleven_flash_v2_5` over the input-streaming WebSocket, sending `flush: true` at the end of each segment. OpenAI `gpt-4o-mini-tts` streamed as `pcm` is the alternative, but it is deprecated with a Jan 6, 2027 shutdown.
5. **Measure "speech end → first audio out" in the browser on one clock.**
   - Speech end comes from a local energy-based VAD on the mic track. First audio is the first non-silent output sample, read with a Web Audio `AnalyserNode` on the playback path.
   - Also log the server events (`input_audio_buffer.speech_stopped`, `output_audio_buffer.started`, first `response.output_audio_transcript.delta`) as diagnostics only. `speech_stopped` already includes the VAD silence window ([server events](https://developers.openai.com/api/reference/resources/realtime/server-events)).
6. **Plan for echo.**
   - Use headphones for demos and benchmarks, and keep `echoCancellation` on.
   - In Cascade mode (audio played via Web Audio, not a WebRTC remote track), also mute or gate the mic while TTS plays. Browser AEC is aimed at remote peer audio ([MDN echoCancellation](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation)); how well it cancels Web Audio playback is unverified.
7. **Expected cost per minute of interpreted speech (pre-build estimates, now superseded by the measured numbers in §5.2):**
   - `gpt-realtime`: about $0.10 (measured: $0.179), audio only, before history re-reads.
   - `gpt-realtime-mini`: about $0.03 (measured: $0.052).
   - `gpt-realtime-translate`: $0.034.
   - Cascade (`gpt-live-transcribe` + nano/Haiku + ElevenLabs Flash): about $0.05 (measured: $0.059 with ElevenLabs, $0.049 all-OpenAI).
   - Keep prices in a dated config file, as the PRD requires.
8. **Quality evaluation:**
   - STT accuracy: `jiwer` WER on Whisper-normalized text (`EnglishTextNormalizer` for EN, `BasicTextNormalizer` for ES), using a scripted set of about 20 utterances per direction.
   - Translation: `sacrebleu` chrF (plus BLEU) against reference translations. Optionally COMET `Unbabel/wmt22-comet-da` run locally, and a 1–5 adequacy/fluency rubric.

> **Deprecation watch (doesn't block an Oct 11 deliverable):**
> - `gpt-realtime` and `gpt-realtime-mini` shut down on **Jan 20, 2027**. Replacements: `gpt-realtime-2.1` and `gpt-realtime-2.1-mini`.
> - `gpt-4o-mini-tts` shuts down on **Jan 6, 2027**.
> - `gpt-4o-transcribe` and `gpt-4o-mini-transcribe` shut down on **Feb 26, 2027**.
> - `gpt-5.4-nano` shuts down on **Apr 1, 2027**.
>
> Source: [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations). Make model IDs config values so these swaps are trivial, and mention this in the write-up as a vendor-lock-in data point.

---

## 1. OpenAI Realtime API (Realtime mode)

### 1.1 Models
| Model | Use here | Notes (source) |
|---|---|---|
| `gpt-realtime` | Final numbers. Required by the brief | GA model, snapshot `gpt-realtime-2025-08-28`, 32k context, WebRTC/WebSocket/SIP ([model page](https://developers.openai.com/api/docs/models/gpt-realtime)) |
| `gpt-realtime-mini` | Development | Snapshot `gpt-realtime-mini-2025-12-15` ([model page](https://developers.openai.com/api/docs/models/gpt-realtime-mini)) |
| `gpt-realtime-2.1` / `-2.1-mini` | Optional comparison | "Reasoning model with tool use", 128k context, configurable reasoning effort; "Higher reasoning effort can increase latency" ([model page](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)). The docs' code samples now default to `gpt-realtime-2.1` ([getting started](https://developers.openai.com/api/docs/guides/realtime)) |
| `gpt-realtime-translate` | Optional third variant (§1.8) | Dedicated translation endpoint ([model page](https://developers.openai.com/api/docs/models/gpt-realtime-translate)) |

The Realtime **Beta** interface was removed on May 12, 2026. Use only the GA interface: no `OpenAI-Beta` header, `session.type` set, GA event names ([changelog](https://developers.openai.com/api/docs/changelog), [Beta→GA migration](https://developers.openai.com/api/docs/guides/realtime#beta-to-ga-migration)).

OpenAI now also promotes **GPT-Live** (`gpt-live-1`, $0.05/min) for new conversational apps ([Audio and voice](https://developers.openai.com/api/docs/guides/audio), [pricing](https://developers.openai.com/api/docs/pricing)). It is an assistant-with-backend-delegation product, not a translation pipeline. It is out of scope because the brief names `gpt-realtime`.

### 1.2 WebRTC vs WebSocket (browser app)
- OpenAI's guidance: "When connecting to a Realtime model from the client (like a web browser or mobile device), we recommend using WebRTC rather than WebSockets for more consistent performance" ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)).
- WebSockets are recommended for server-to-server use. Browser WebSocket with an ephemeral key is possible, but "WebRTC will be a more robust solution" ([WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets)).
- With WebRTC, audio rides media tracks. JSON events go over a data channel labelled `oai-events`. You don't handle audio events "in the same granular way" as over WebSockets, and the peer connection plays the audio ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)).
- In WebRTC/SIP the server manages the output audio buffer and **automatically truncates unplayed audio on interruption**. Over WebSockets the client must do this ([Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)).
- **Recommendation:** WebRTC from the browser for Realtime mode. A FastAPI WebSocket relay to OpenAI is only a fallback; it adds a hop and makes you play PCM yourself.

**Two WebRTC connection flows** ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)):
1. **Unified interface.**
   - The browser POSTs its SDP offer to your server.
   - The server sends a multipart form (`sdp` plus `session` JSON) to `POST https://api.openai.com/v1/realtime/calls` with the standard API key, then returns the SDP answer.
   - Docs: "simpler setup and faster connections", but your server sits in the critical path of session setup.
2. **Ephemeral token.**
   - The server mints a client secret.
   - The browser POSTs `offer.sdp` to `https://api.openai.com/v1/realtime/calls` with `Authorization: Bearer <ek_...>` and `Content-Type: application/sdp`.

Both flows keep the real key server-side, which satisfies PRD FR-2.1 and NFR-4. Either is fine. The PRD names client secrets, so the code examples below use flow 2.

Optional: WARP connection-startup optimizations exist, but they are Internet-Drafts with partial browser support (Chrome needs an origin trial for SNAP; no browser supports SPED) ([WARP guide](https://developers.openai.com/api/docs/guides/realtime-webrtc-warp)). **Skip them for this project.**

### 1.3 Ephemeral client secrets (current endpoint and shape)
- **Endpoint:** `POST https://api.openai.com/v1/realtime/client_secrets`, authenticated with the standard key ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)).
- **Body:** `{ "expires_after": { "anchor": "created_at", "seconds": 600 }, "session": { "type": "realtime", "model": "...", ... } }`.
  - `seconds` ranges from 10 to 7200. The default is 600 (10 minutes).
  - `session` can also be a transcription session config.
- **Response:** `{ "value": "ek_...", "expires_at": <epoch s>, "session": {...effective config...} }`. The browser uses `value` as its Bearer token.
- Optionally set the `OpenAI-Safety-Identifier` header (a hashed user ID) on the minting request. It is bound to the token ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc), [getting started](https://developers.openai.com/api/docs/guides/realtime)).
- The maximum Realtime session length is **60 minutes** ([conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)). That covers the 5-minute soak (NFR-2) easily.
- The token TTL only needs to cover connection setup. Mint a fresh token per session or mode switch, and handle expiry as an error state (CQ-4).

Python (FastAPI) sketch. The key comes from env/config and is never logged:
```python
@app.post("/api/realtime/session")
async def realtime_session(body: SessionReq):
    payload = {
        "expires_after": {"anchor": "created_at", "seconds": 600},
        "session": build_interpreter_session(body.source_lang, body.target_lang, model=settings.realtime_model),
    }
    r = await http.post("https://api.openai.com/v1/realtime/client_secrets",
                        headers={"Authorization": f"Bearer {settings.openai_api_key}"}, json=payload)
    r.raise_for_status()
    data = r.json()
    return {"value": data["value"], "expires_at": data["expires_at"]}
```

### 1.4 Session config for translation-only behavior
All fields below are from the [client secrets / session reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets) unless noted. Example:
```json
{
  "type": "realtime",
  "model": "gpt-realtime",
  "output_modalities": ["audio"],
  "instructions": "<interpreter prompt, see below>",
  "audio": {
    "input": {
      "noise_reduction": { "type": "near_field" },
      "transcription": { "model": "gpt-4o-transcribe", "language": "en" },
      "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 400,
        "create_response": true,
        "interrupt_response": false
      }
    },
    "output": { "voice": "marin" }
  }
}
```

**`instructions`**
- No official interpreter template exists in the Realtime prompting guide (unverified that none exists; I didn't find one).
- The guide does say to **control language explicitly and separately from accent**. Avoid instructions like "Respond naturally in the user's language" or "Switch languages when appropriate", because the model may switch on accents, fillers or isolated foreign words ([Prompting Realtime models](https://developers.openai.com/api/docs/guides/voice-prompting)).
- Suggested prompt (my draft, not from a source):

  > You are a professional consecutive interpreter between English and Spanish. When you hear English, say only its faithful Spanish translation; when you hear Spanish, say only its faithful English translation. Never answer questions, add commentary, greet, or ask for clarification. Preserve names, numbers, dates and register. If audio is unintelligible, stay silent.

- For fixed directions, put the direction in the prompt and rebuild the session (or `session.update`) when the user swaps.

**Turn detection** ([VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad), [reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets))
- VAD is on by default in speech-to-speech sessions. It is configured at `session.audio.input.turn_detection`.
- **`server_vad`** chunks on silence.
  - `threshold`: 0–1, default 0.5.
  - `prefix_padding_ms`: default 300.
  - `silence_duration_ms`: default 500. Shorter values detect turns faster but "may jump in on short pauses".
  - `idle_timeout_ms` exists but would make the model speak unprompted. Leave it unset.
- **`semantic_vad`** decides from the words whether the user has finished.
  - `eagerness`: `low | medium | high | auto`, with max timeouts of 8 s, 4 s and 2 s; `auto` = `medium`.
  - The docs say it "may have a higher latency".
- **`create_response` / `interrupt_response`** (conversation-only):
  - Both `false`: VAD events still fire, but responses are never created automatically. Call `response.create` yourself.
  - `turn_detection: null`: no VAD. The client must `input_audio_buffer.commit` and then `response.create` (push-to-talk) ([conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)).
- **Recommendation:** `server_vad`. Sweep `silence_duration_ms` over 300/400/500 ms against the 1.5 s budget. Offer push-to-talk (`turn_detection: null`) as a noisy-room fallback (PRD Q5).

**Interruptions and truncation** ([conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations))
- With VAD, new speech cancels the in-progress response. The guide says "a `response.cancelled` event will be emitted"; the server-events reference doesn't list it, so also check `response.done` status (uncertain). Over WebRTC the server truncates unplayed audio automatically.
- Over WebSocket, the client sends `conversation.item.truncate` with `audio_end_ms`.
- Truncation removes the unplayed transcript text, so the output transcript can't be aligned precisely after a cut.
- Manual cut-off: `response.cancel` plus `output_audio_buffer.clear` (WebRTC).
- **Interpreter tradeoff (my inference):** the default `interrupt_response: true` means a reply from the other party cancels the translation still playing. For interpretation, `false` is usually better: let each translation finish. Expose it as a toggle and record the choice in the write-up.

**Conversation growth (cost, and the "assistant answers instead of translating" risk)**
- "The entire conversation is sent to the model for each Response", so later turns cost more. Caching is automatic but best-effort.
- Truncation is configurable: `truncation.retention_ratio`, `token_limits.post_instructions`, or `"disabled"`.
- Items can be removed with `conversation.item.delete` ([cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)).
- **Recommendation:** after each completed translation (`response.done`), delete old user/assistant items, keeping the last 1–2 turns for context. This bounds cost and reduces drift. Validate quality with and without pruning.
- **Out-of-band responses:** `response.create` with `response.conversation: "none"` creates a response that isn't added to the default conversation ([conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)). It is an alternative pattern if you turn off `create_response`.

### 1.5 Audio formats and sample rates
- Session input/output formats ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)):
  - `audio/pcm` at **24 kHz only** (`rate: 24000`);
  - `audio/pcmu` (G.711 μ-law);
  - `audio/pcma` (G.711 A-law).
- WebSocket examples use "PCM16, 24 kHz, mono" chunks ([conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)).
- Over WebRTC the codec is negotiated by SDP. The browser handles capture and playback, so no manual resampling is needed. The GPT-Live WebRTC docs say to omit `audio.format` ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)). Uncertain: whether the Realtime (non-Live) API also ignores `audio.format` over WebRTC. Omitting it is safe.
- Audio token accounting: user audio is 1 token per 100 ms; assistant audio is 1 token per 50 ms ([cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)).
- Voices: `alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar`. `marin` and `cedar` are recommended. The voice can't change after the first audio response ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)). Mode/direction switches therefore need a new session if you want a different voice.

### 1.6 Events for transcripts (exact GA names)
Source: [server events reference](https://developers.openai.com/api/reference/resources/realtime/server-events).

| Purpose | Event | Notes |
|---|---|---|
| Speech start/stop (VAD) | `input_audio_buffer.speech_started`, `input_audio_buffer.speech_stopped` | Fields `audio_start_ms` (includes `prefix_padding_ms`) and `audio_end_ms` (includes the silence duration), plus `item_id` |
| Turn committed | `input_audio_buffer.committed` | |
| **Source text (partial)** | `conversation.item.input_audio_transcription.delta` | Only when `audio.input.transcription` is set |
| **Source text (final)** | `conversation.item.input_audio_transcription.completed` | Includes `transcript` and `usage` |
| Source transcription segment/failure | `conversation.item.input_audio_transcription.segment`, `...failed` | Handle `failed` as an empty result (CQ-4) |
| **Target text (partial)** | `response.output_audio_transcript.delta` | The model's spoken output, transcribed |
| **Target text (final)** | `response.output_audio_transcript.done` | |
| Target audio (WebSocket only) | `response.output_audio.delta` / `.done` | Base64 audio chunks. Over WebRTC, audio arrives on the media track instead |
| Output playback (WebRTC/SIP only) | `output_audio_buffer.started`, `.stopped`, `.cleared` | `started` fires "when the server begins streaming audio to the client" |
| Lifecycle | `response.created`, `response.done`, `error`, `rate_limits.updated` | `response.done` carries usage for cost tracking. The conversations guide mentions a `response.cancelled` event on interruption, but it isn't a heading in the server-events reference. Uncertain: detect cancellation via `response.done` status, and log both |

Caveats:
- Input transcription "is not native to the model… runs asynchronously… and should be treated as guidance of input audio content rather than precisely what the model heard" ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)).
  - Source text may arrive **after** the translation starts.
  - WER for Realtime mode measures the side transcriber, not the speech-to-speech model itself. State this in the write-up.
- Transcription is billed separately at the transcription model's rates ([cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)).
- Ordering between completion events from different turns isn't guaranteed. Key on `item_id` ([realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription)).
- **Which transcription model in a speech-to-speech session?**
  - The session reference accepts `whisper-1`, `gpt-transcribe`, `gpt-live-transcribe`, `gpt-4o-mini-transcribe(-2025-12-15)`, `gpt-4o-transcribe`, `gpt-4o-transcribe-diarize` and `gpt-realtime-whisper`.
  - The model pages list `v1/realtime` as "Supported" only for `gpt-4o-transcribe` and `gpt-4o-mini-transcribe`. `gpt-transcribe`, `gpt-live-transcribe` and `gpt-realtime-whisper` show only `v1/realtime/transcription_sessions` ([gpt-4o-transcribe](https://developers.openai.com/api/docs/models/gpt-4o-transcribe), [gpt-live-transcribe](https://developers.openai.com/api/docs/models/gpt-live-transcribe)). Yet the transcription guide says `gpt-transcribe` "performs input transcription in a Realtime API session" ([transcription guide](https://developers.openai.com/api/docs/guides/transcription)).
  - **Uncertain:** the docs conflict. Start with `gpt-4o-transcribe`, which every source lists as supported, and try `gpt-live-transcribe` if time allows.

### 1.7 Measuring speech-end → first-audio latency (Realtime)
Definition from the brief: "speech end → first audio out" perceived latency, under 1.5 s. The PRD (NFR-5) requires one browser clock.

- **Primary (honest, browser-side):**
  - `t_speech_end`: a local VAD on the mic `MediaStreamTrack` (`AudioWorklet` or `AnalyserNode` RMS below a threshold for about 150–200 ms; take the timestamp of the *last voiced frame*).
  - `t_first_audio`: an `AnalyserNode` on the remote WebRTC track (the `pc.ontrack` stream) detecting the first non-silent frame.
  - Latency = `t_first_audio − t_speech_end`, using `performance.now()` for both. This includes the network, server VAD wait, model time and jitter buffer, which is what the user perceives.
- **Diagnostics (server-relative, logged per turn):**
  - Arrival time (`performance.now()`) of `input_audio_buffer.speech_stopped`, `response.created`, `output_audio_buffer.started`, and the first `response.output_audio_transcript.delta`.
  - **Caveat:** `speech_stopped` fires only after `silence_duration_ms` of silence, and its `audio_end_ms` "includes" that silence ([server events](https://developers.openai.com/api/reference/resources/realtime/server-events)). Measuring from `speech_stopped` *understates* perceived latency by roughly `silence_duration_ms` plus network. Report both numbers and say which one meets the target.
- Over WebSocket (relay/fallback), the equivalent server marker is the first `response.output_audio.delta`. Perceived latency must still be taken at the browser playback point.
- `t_speech_end` is approximate. Use the same local VAD for both modes so the comparison is fair.

### 1.8 What `gpt-realtime-translate` is, and whether it fits
- **What it is:** "a streaming speech-to-speech translation model for live multilingual audio experiences… returns translated audio plus transcript deltas while source audio is still arriving", priced by audio duration at **$0.034/min** ([model page](https://developers.openai.com/api/docs/models/gpt-realtime-translate)). Released May 7, 2026 alongside `gpt-realtime-2` and `gpt-realtime-whisper` ([changelog](https://developers.openai.com/api/docs/changelog)).
- **How it works** ([Realtime translation guide](https://developers.openai.com/api/docs/guides/realtime-translation)):
  - Dedicated endpoint `/v1/realtime/translations` (not `/v1/realtime`).
  - The model "acts as an interpreter", "streams continuously from incoming audio", and you **don't** call `response.create`.
  - Keep appending audio, including silence.
  - Browser flow: the server mints a secret at `POST /v1/realtime/translations/client_secrets` with `{ session: { model: "gpt-realtime-translate", audio: { output: { language: "es" } } } }`, then the browser POSTs its SDP to `/v1/realtime/translations/calls`.
  - WebSocket flow: `wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate`, sending `session.input_audio_buffer.append` (base64 24 kHz PCM16).
  - Events ([translation server events](https://developers.openai.com/api/reference/resources/realtime/translation-server-events)): `session.output_transcript.delta` (target text), `session.input_transcript.delta` (source text, only if `audio.input.transcription` is set), and `session.output_audio.delta` (PCM16, `sample_rate` 24000 in the example). Each carries an `elapsed_ms` alignment field in 200 ms steps.
  - Close with `session.close` and wait for `session.closed`.
- **Two-way conversation:** use **one translation session per direction** (A→B's language, B→A's language), with separate speaker tracks ([guide](https://developers.openai.com/api/docs/guides/realtime-translation)). EN↔ES therefore means two sessions and two mic/track routes. With one shared mic, you'd need to pick the active direction.
- **Language list:** I couldn't find a published supported-language list. Spanish (`"es"`) appears in OpenAI's examples, so treat Spanish as likely but unverified.
- **Does it count as "Realtime mode"?**
  - Technically it is part of the OpenAI Realtime API family.
  - The brief says: "OpenAI Realtime API (model: gpt-realtime) required for Realtime mode" ([assignment.pdf](../sources/assignment.pdf)). Substituting it for the required mode risks failing that requirement.
  - **Recommendation:** build Realtime mode on `gpt-realtime`. Add `gpt-realtime-translate` as a stretch third transport, or at least discuss it in the write-up as the likely production-grade voice-to-voice option. It is continuous (simultaneous rather than consecutive), cheaper per minute, and has no "assistant" failure mode. Its latency semantics differ: output begins while the speaker is still talking, so "speech end → first audio" isn't directly comparable.

---

## 2. OpenAI streaming transcription (Cascade STT)

### 2.1 Which models exist (Oct 2026)
| Name | Exists? | Role and facts (source) |
|---|---|---|
| `gpt-live-transcribe` | **Yes** | Recommended for **realtime** transcription: "low-latency transcript deltas", tunable latency, `prompt`, `keywords`, `languages`. **No** `server_vad`/`semantic_vad`: omit or null `turn_detection` and send `input_audio_buffer.commit` per turn. No word timestamps, speaker labels or confidence. $0.017/min ([guide](https://developers.openai.com/api/docs/guides/realtime-transcription), [model](https://developers.openai.com/api/docs/models/gpt-live-transcribe), [VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad)) |
| `gpt-realtime-whisper` | **Yes** | "Streaming speech-to-text model for realtime transcription", $0.017/min. Turn detection must be `null`. `delay` is supported; `prompt` is not ([model](https://developers.openai.com/api/docs/models/gpt-realtime-whisper), [reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)). The docs call it an existing option, not the recommended start ([transcription guide](https://developers.openai.com/api/docs/guides/transcription)) |
| `gpt-transcribe` | Yes | File transcription, plus committed-turn realtime transcription over WebSocket with detected `languages` in the completion event. $0.0045/min ([guide](https://developers.openai.com/api/docs/guides/realtime-transcription), [pricing](https://developers.openai.com/api/docs/pricing)) |
| `gpt-4o-transcribe` | Yes, **deprecated** (shutdown Feb 26, 2027) | Token-priced, est. $0.006/min. Supports VAD in realtime sessions (models that support VAD default to `server_vad`) ([pricing](https://developers.openai.com/api/docs/pricing), [deprecations](https://developers.openai.com/api/docs/deprecations), [VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad)) |
| `gpt-4o-mini-transcribe` | Yes, **deprecated** (Feb 26, 2027) | Est. $0.003/min; snapshot `-2025-12-15` ([pricing](https://developers.openai.com/api/docs/pricing)) |

### 2.2 Realtime transcription sessions (how to use)
Source: [Realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription).
- **Session type:** `session.type: "transcription"`, with `audio.input.format: {type: "audio/pcm", rate: 24000}`, `audio.input.transcription.model: "gpt-live-transcribe"`, and `turn_detection: null`.
- **Context:** `transcription.prompt`, `keywords` (no `<`, `>` or newlines), and `languages: ["en","es"]`. Don't also send the singular `language`.
- **Latency vs accuracy:** `transcription.delay` takes `minimal | low | medium | high | xhigh`. "Lower delay settings can produce earlier partial text. Higher delay settings… can improve word error rate"; "the exact delay in milliseconds can vary… benchmark" (no millisecond figures are published).
- **Audio in:** `input_audio_buffer.append` (base64 PCM16), then `input_audio_buffer.commit` at the end of each turn. "Use client-side VAD to detect the end of speech."
- **Events:** `conversation.item.input_audio_transcription.delta` gives partials; `...completed` gives finals. Match on `item_id`; cross-turn ordering isn't guaranteed.
- **Partials can be revised:** "Decide how your UI should revise partial text when later deltas correct earlier text."
- **Transport:** WebSocket for a server pipeline, WebRTC for browser audio.
  - Cascade runs through FastAPI, so use a WebSocket from the backend.
  - The model pages list the route `v1/realtime/transcription_sessions`. **Uncertain:** the exact WebSocket URL/query string for a transcription session isn't shown on the pages I read. Check the SDK (`openai` Python `client.realtime.connect(...)`) or the reference before coding.
- **VAD for Cascade:** `gpt-live-transcribe` has no server VAD, so you need your own end-of-speech detector to know when to commit and start translating. Options:
  - (a) A simple energy VAD in the browser AudioWorklet that sends a "commit" control message.
  - (b) A Python VAD on the backend (e.g., Silero VAD, a local/free tool; unverified detail).
  - (c) `gpt-4o-transcribe` with `server_vad` (deprecated, but it gives `speech_started/stopped` events).
  - (d) ElevenLabs Scribe v2 Realtime with built-in VAD commit (below).

### 2.3 Alternative allowed STT: ElevenLabs Scribe v2 Realtime
- `scribe_v2_realtime`: "Low latency (~150ms†)", 90+ languages, word timestamps. † means "Excluding application & network latency" ([ElevenLabs models](https://elevenlabs.io/docs/overview/models)).
- Price: **$0.39/hour** ([ElevenLabs API pricing](https://elevenlabs.io/pricing/api)), which is ≈ $0.0065/min (estimate: 0.39 ÷ 60).
- It gives **partial** and **committed** transcripts. Commit strategy is manual (the default) or **VAD**, with example params `vad_silence_threshold_secs=1.5`, `vad_threshold=0.4`, `min_speech_duration_ms=100`, `min_silence_duration_ms=100`.
  - VAD is recommended for mic input.
  - "Transcript processing starts after the first 2 seconds of audio are sent."
  - The example sends `sample_rate: 16000` ([commit strategies](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies)).
- The 1.5 s VAD silence example would by itself eat most of a 2 s budget. Tune it down and measure.

---

## 3. Streaming translation via LLM (Cascade middle stage)

### 3.1 Candidate low-latency models
No provider publishes time-to-first-token (TTFT) numbers for these models on the pages I checked. **Measure TTFT yourself:** time from request send to the first streamed text delta, with median and p90 over the scripted set.

| Model | Why | Price (input/output per 1M tokens) | Latency notes (source) |
|---|---|---|---|
| `gpt-5.4-nano` | "designed for tasks where speed and cost matter most"; reasoning effort defaults to **`none`** | $0.20 / $1.25 | Deprecated, shutdown Apr 1, 2027 → `gpt-6-luna` ([model](https://developers.openai.com/api/docs/models/gpt-5.4-nano), [pricing](https://developers.openai.com/api/docs/pricing), [deprecations](https://developers.openai.com/api/docs/deprecations)) |
| `gpt-6-luna` | "most efficient model for focused, high-volume tasks"; `reasoning.effort` supports `none` (the default is `medium`, so **set `none`**) | $0.10 / $0.50 | ([model](https://developers.openai.com/api/docs/models/gpt-6-luna), [pricing](https://developers.openai.com/api/docs/pricing)) |
| `gpt-4.1-nano` / `gpt-4.1-mini` | "low latency without a reasoning step" | $0.10/$0.40; $0.40/$1.60 | ([model](https://developers.openai.com/api/docs/models/gpt-4.1-nano), [pricing](https://developers.openai.com/api/docs/pricing)) |
| `gpt-5.4-mini` | Stronger quality fallback; effort defaults to `none` | $0.75 / $4.50 | ([model](https://developers.openai.com/api/docs/models/gpt-5.4-mini)) |
| `claude-haiku-5-5` | Anthropic's "Fastest" model, released Oct 7, 2026. Adaptive thinking is **on by default**; `thinking: {type: "disabled"}` is accepted at effort `high` or below. Don't send `temperature/top_p/top_k` (400 error) | $0.10 / $0.50 (prompts ≤100k tokens) | ([Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview), [thinking](https://platform.claude.com/docs/en/build-with-claude/thinking), [models overview](https://platform.claude.com/docs/en/models/overview)) |
| `claude-sonnet-5-5` | Quality fallback, "Fast". Rejects `disabled`; use `thinking: {type: "between_tools"}` to avoid up-front thinking | $2 / $10 | ([thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)) |
| Any of the above via **OpenRouter** | One API for provider swapping. `provider.sort: "latency"` routes to the lowest-latency provider; `preferred_max_latency` is a soft preference; `:nitro` sorts by throughput | Pass-through pricing, plus a fee on credit purchases | ([provider routing](https://openrouter.ai/docs/guides/routing/provider-selection), [FAQ](https://openrouter.ai/docs/faq)). Adds a network hop (unverified size); measure it |

Other levers:
- OpenAI "Fast mode" claims "up to 2.5× faster speeds" at 2× price on supported models ([Fast mode](https://developers.openai.com/api/docs/guides/fast-mode), [gpt-6-luna page](https://developers.openai.com/api/docs/models/gpt-6-luna)). Whether it lowers **TTFT** specifically is unverified.
- Keep the system prompt static and first so prompt caching applies ([latency guide](https://developers.openai.com/api/docs/guides/latency-optimization): "Maximize shared prompt prefix").
- Stream the output tokens.
- Anthropic rate limits for Haiku 5.5 on the Start tier: 1,000 RPM, 2M ITPM, 400k OTPM ([rate limits](https://platform.claude.com/docs/en/api/rate-limits)).

**Recommendation:**
- Default translator: `gpt-5.4-nano` or `gpt-6-luna` (effort `none`). Second adapter: `claude-haiku-5-5` (thinking disabled). Both sit behind one `Translator` interface; this also proves provider flexibility.
- Pick the default by measured TTFT and a quick chrF/LLM-judge check on the scripted set.

### 3.2 Chunking strategy (partial vs final transcript)
OpenAI's latency guide recommends **streaming** ("the single most effective approach") and **chunking** output that needs further processing such as translation ([latency guide](https://developers.openai.com/api/docs/guides/latency-optimization)). Everything below is engineering judgment, not sourced.
- **Translate on committed/final segments (recommended default).**
  - The STT "completed" event (or VAD commit) triggers one translation request.
  - Stream the tokens out, and feed TTS at clause/sentence boundaries (`. ? ! ; :` and `, ` after N≥ 8 words), or let ElevenLabs `auto_mode`/`chunk_length_schedule` handle it (§4.2).
  - Simple and stable: no retractions.
  - Latency = VAD wait + STT finalize + LLM TTFT + first-clause tokens + TTS TTFB.
- **Optional "eager" mode for long utterances.**
  - While the speaker continues, translate *stable prefixes*: text unchanged across the last k partials, ending at a clause boundary.
  - Send each prefix once; never re-speak.
  - Risks: EN↔ES reorders words (adjective/noun order, verb-final clauses), so early chunks can be wrong or awkward. Partials from `gpt-live-transcribe` can be revised ([guide](https://developers.openai.com/api/docs/guides/realtime-transcription)).
- **Re-translation (retranslate the whole partial each time) is a display-only technique.**
  - Fine for live target captions, but audio can't be retracted, so never send retranslated text to TTS.
- **Context:** include the last 1–2 translated turns in the prompt for pronoun and gender consistency. Keep the static instructions first for caching.
- **Prompt:** "Translate from {src} to {tgt}. Output only the translation, no quotes or notes." Set a small `max_output_tokens`/`max_tokens`. With Claude, keep the thinking-disabled setting and avoid JSON/tools for this call.

---

## 4. Streaming TTS (Cascade final stage)

### 4.1 OpenAI `gpt-4o-mini-tts` (`POST /v1/audio/speech`)
- **Streaming:** "realtime audio streaming using chunk transfer encoding". `stream_format` is `"audio"` (raw bytes) or `"sse"` ([TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech), [speech reference](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)).
- **Formats:** `mp3` (default), `opus`, `aac`, `flac`, `wav`, `pcm`.
  - "For the fastest response times, we recommend using `wav` or `pcm`."
  - **`pcm` = raw 24 kHz, 16-bit signed little-endian samples, no header.**
- **Options:**
  - `instructions` controls voice and style (not supported on `tts-1`/`tts-1-hd`).
  - `speed` ranges from 0.25 to 4.0.
  - `input` max is 4096 characters (reference). The model page says max input tokens is 2000 ([model](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)).
- **Spanish:** language support "generally follows the Whisper model", and Spanish is in the list. However, **"voices are currently optimized for English"** ([TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech)).
- **Latency:** no published TTFB figure. Measure it.
- **Limitation:** it takes **whole text per request**, with no input streaming. In a cascade you'd send one request per clause/sentence, which costs a TTFB each time.
- **Price:** $0.60 / 1M text input tokens and $12 / 1M audio output tokens ([pricing](https://developers.openai.com/api/docs/pricing)). The audio-tokens-per-second rate for TTS output isn't stated on the pages I read, so **no per-minute figure can be derived from sources.** Read `usage` from responses and compute from that (unverified whether the speech endpoint returns usage in `audio` stream mode).
- **Deprecated:** shutdown Jan 6, 2027. OpenAI recommends `gpt-realtime-2.1-mini` as the replacement ([deprecations](https://developers.openai.com/api/docs/deprecations)).

### 4.2 ElevenLabs
- **Models** ([models](https://elevenlabs.io/docs/overview/models), [pricing](https://elevenlabs.io/pricing/api)):
  - **`eleven_flash_v2_5`**: "Ultra-low latency (~75ms†)". 32 languages including `es`. 40,000-character limit. "50% lower price per character".
  - `eleven_turbo_v2_5`: "functionally equivalent" to Flash but slower on average. "We recommend using the Flash models over Turbo models in all use cases."
  - Newer: **`eleven_v4_turbo`**, "Our most expressive, real-time speech synthesis model (~100ms†)", 90+ languages including "Spanish, LatAm". **But** it is "available via the Text to Dialogue websocket", not the TTS stream-input WebSocket.
  - `eleven_v3_conversational` (~280 ms) is also available.
  - † = "Excluding application & network latency".
- **Latency numbers:**
  - "75ms refers to model inference time only" ([latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)).
  - Published **TTFB with Flash over WebSockets: 100–150 ms in North America/Europe/SE Asia, 150–200 ms in South/NE Asia** (same page).
  - Time-to-first-audio adds network (20–200 ms) and player buffering ("A 500ms buffer is common") ([understanding latency](https://elevenlabs.io/docs/eleven-api/concepts/latency)).
  - Default/synthetic/IVC voices are faster than Professional Voice Clones (same pages).
  - `api.us.elevenlabs.io` pins US servers.
- **HTTP streaming:** `POST /v1/text-to-speech/{voice_id}/stream` returns audio chunks progressively. ElevenLabs recommends it "when the input text is available up-front" ([latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)).
  - `output_format` values include `pcm_16000, pcm_22050, pcm_24000, pcm_44100, pcm_48000, ulaw_8000, mp3_*, opus_48000_*`.
  - `language_code` (ISO 639-1) enforces language and normalization.
  - `optimize_streaming_latency` is **deprecated** ([stream reference](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)).
- **WebSocket input streaming:** `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id=eleven_flash_v2_5` ([WebSocket reference](https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input), [guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts)).
  - Designed for text "being streamed or generated in chunks" (LLM output).
  - **Query params:** `output_format`, `language_code`, `auto_mode` (default false), `inactivity_timeout` (default 20 s, max 180), `sync_alignment`, `single_use_token`. Header auth is `xi-api-key`.
  - **Chunking:** `chunk_length_schedule` defaults to `[120, 160, 250, 290]` characters. With `auto_mode` off, the model "will wait for enough text… potentially increasing latency".
    - **Set `auto_mode=true`**, or send `flush: true` at the end of each segment ("advise using `flush: true`… at the end of conversation turn").
  - **Idle connections:** the connection closes after 20 s idle by default. Keep it alive by sending `" "`; an empty string `""` closes it.
  - Responses carry base64 `audio`, optional alignment, and `isFinal`.
  - ElevenLabs notes WebSockets can have "slightly higher latency" than HTTP when the whole text is known up front.
- **Spanish:** Flash v2.5 supports `es` ([models](https://elevenlabs.io/docs/overview/models)). There is no published Spanish quality metric; judge it subjectively (and use a Spanish-native voice from the Voice Library, unverified which voice is best).
- **Recommendation:**
  - Use Flash v2.5 over the stream-input WebSocket with `auto_mode=true`, `output_format=pcm_24000` (one sample rate everywhere) and `language_code` set to the target.
  - Open one socket per target language per session, and keep it warm with `" "` keep-alives so you don't pay the connect cost per turn.
  - Make OpenAI `gpt-4o-mini-tts` the second adapter, for provider flexibility.

---

## 5. Pricing, rate limits, and gotchas

### 5.1 Unit prices (as listed Oct 8, 2026)
| Item | Price | Source |
|---|---|---|
| `gpt-realtime` audio | $32 in / $0.40 cached in / $64 out per 1M; text $4 / $0.40 / $16 | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-realtime-mini` audio | $10 / $0.30 / $20 per 1M; text $0.60 / $0.06 / $2.40 | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-realtime-2.1` audio | $32 / $0.40 / $64; text $4 / $0.40 / $24 | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-realtime-translate` | $0.034 / min | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-live-transcribe`, `gpt-realtime-whisper` | $0.017 / min | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-4o-transcribe` / `-mini-transcribe` | est. $0.006 / $0.003 per min | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-4o-mini-tts` | $0.60 / 1M text in; $12 / 1M audio out | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-5.4-nano`; `gpt-6-luna` | $0.20/$1.25; $0.10/$0.50 per 1M | [pricing](https://developers.openai.com/api/docs/pricing) |
| `claude-haiku-5-5` | $0.10 / $0.50 per 1M (≤100k prompt) | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| ElevenLabs Flash/Turbo TTS | $0.04 / 1K characters | [ElevenLabs API pricing](https://elevenlabs.io/pricing/api) |
| ElevenLabs v4 Turbo TTS | $0.04 / 1K chars list; **$0.011 promo "72% off until Oct 12"** | [ElevenLabs API pricing](https://elevenlabs.io/pricing/api) |
| ElevenLabs Scribe v2 Realtime | $0.39 / hour | [ElevenLabs API pricing](https://elevenlabs.io/pricing/api) |
| OpenRouter | Pass-through provider pricing ("no markup on inference pricing"); a fee applies when buying credits. The page source shows 5.5% ($0.80 min) for card purchases (unverified as rendered) | [OpenRouter FAQ](https://openrouter.ai/docs/faq) |

Uncertain: whether ElevenLabs' per-1K-character API prices depend on the subscription plan (the pricing page shows these as API prices; plan inclusion and overage rules weren't checked).

### 5.2 Per-minute estimates (show-the-math; **all estimates**)

> **Superseded by measured numbers (Oct 9, 2026).** The estimates below were written before the build. Quote the measured per-minute costs instead, which are estimated from usage, not invoices. They were computed from per-run token usage priced with `config/pricing.yaml` as of Oct 8, over the 48-sentence M5 run:
> - `gpt-realtime`: $0.179/min. This is above the estimate below, mainly because the input transcription is billed on top.
> - `gpt-realtime-mini`: $0.052/min.
> - Cascade, all OpenAI: $0.049/min.
> - Cascade with Haiku via OpenRouter: $0.048/min.
> - Cascade with ElevenLabs: $0.059/min at list price.
>
> See the measured cost table in the repo (CTO's M5 results) for the source of truth.

Assumption A: one minute of source speech produces about one minute of translated speech. Assumption B (not sourced): about 150 spoken words/min, about 900 characters/min of Spanish/English text, and about 200 text tokens/min. Replace these with measured values.

**Realtime `gpt-realtime`, audio tokens only** (token rates from the [cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)):
- Input: 60 s ÷ 0.1 s = 600 tokens × $32/1M = **$0.0192**.
- Output: 60 s ÷ 0.05 s = 1,200 tokens × $64/1M = **$0.0768**.
- Total ≈ **$0.096/min**, plus instructions, output text tokens (transcript, $16/1M), input transcription (e.g. `gpt-4o-transcribe` ≈ $0.006/min), and **history re-reads**.

**History re-read example:** by minute 5 the conversation holds about 3,000 input and 6,000 output audio tokens (9,000 total).
- Re-sent on a turn as cached input: 9,000 × $0.40/1M ≈ $0.0036 per turn.
- If the cache misses: 9,000 × $32/1M ≈ **$0.29 per turn**.
- That is why §1.4 recommends pruning items.

**Realtime `gpt-realtime-mini`:** 600 × $10/1M + 1,200 × $20/1M = $0.006 + $0.024 ≈ **$0.030/min** (same exclusions).

**`gpt-realtime-translate`:** **$0.034/min** of audio. Uncertain: whether the silence you stream between phrases is billed. The pricing says "audio duration", and the guide says to stream silence, so assume wall-clock session time is billed (unverified).

**Cascade (`gpt-live-transcribe` + `gpt-5.4-nano` + ElevenLabs Flash):**
- STT: $0.017/min. Uncertain: billed on streamed duration or speech only.
- LLM, assuming ~10 requests/min × ~400 input tokens (prompt + context) and ~250 output tokens/min:
  - 4,000 × $0.20/1M = $0.0008;
  - 250 × $1.25/1M = $0.0003;
  - total ≈ $0.001/min.
- TTS: 900 chars × $0.04/1K = $0.036/min.
- Total ≈ **$0.054/min**.
- Swapping in Scribe v2 Realtime ($0.0065/min) gives ≈ $0.044/min. Swapping in v4 Turbo at the promo rate would cut TTS to ≈ $0.010/min, but the promo ends Oct 12 and v4 Turbo uses the Text-to-Dialogue WebSocket.

### 5.3 Rate limits and tiers
- OpenAI tiers: **Build** ($5 purchased, $500/mo usage limit), **Launch** ($100, $5,000/mo) and **Grow** ($500, $200,000/mo) ([rate limits](https://developers.openai.com/api/docs/guides/rate-limits)).
  - 429s carry `Retry-After`, and `x-ratelimit-*` headers report remaining quota.
  - Realtime sessions emit `rate_limits.updated` ([server events](https://developers.openai.com/api/reference/resources/realtime/server-events)).
- Per-model limits at **Build** tier:
  - `gpt-realtime`, `gpt-realtime-mini`, `gpt-realtime-2.1`: 400 RPM / 200k TPM.
  - `gpt-realtime-translate`: 200 audio-minutes per minute.
  - `gpt-realtime-whisper`: 350 audio-minutes per minute.
  - `gpt-live-transcribe`: 2,000 RPM / 210k TPM.
  - `gpt-4o-mini-tts`: 2,000 RPM / 150k TPM.
  - Sources: the model pages linked above.
  - None of this matters for a single-user demo.
- Anthropic Start tier, Haiku 5.5: 1,000 RPM, 2M ITPM, 400k OTPM ([rate limits](https://platform.claude.com/docs/en/api/rate-limits)).
- ElevenLabs: concurrency depends on plan ("Enterprise customers benefit from increased concurrency limits") ([latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)). The exact per-plan concurrency wasn't checked (unverified).

### 5.4 Gotchas
- **Echo/feedback loops.** Translated audio from speakers re-enters the mic, triggers VAD, and gets "translated" again.
  - `echoCancellation` is a widely supported constraint. A string value `"remote-only"` removes system audio "from remote sources (as represented by MediaStreamTracks sourced from an RTCPeerConnection)" ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation)).
  - So Realtime/WebRTC playback is the case AEC is built for.
  - Cascade playback through Web Audio isn't an RTCPeerConnection source. **Inference:** AEC may cancel it less reliably. Use headphones, and/or mute the mic track (`track.enabled = false`) while TTS plays.
  - Set `noise_reduction: near_field` (headset) or `far_field` (laptop mic) in Realtime sessions ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)).
- **Sample rates.** OpenAI Realtime PCM is 24 kHz only. OpenAI TTS `pcm` is 24 kHz. ElevenLabs offers `pcm_24000`.
  - The browser `AudioContext` defaults to the output device's preferred rate, "44,100 Hz is the most common"; you can request a `sampleRate` ([MDN AudioContext](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/AudioContext)).
  - For Cascade, capture through an `AudioWorklet` (secure context required, [MDN](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet)), downsample to 24 kHz mono Int16 in the worklet, and send 20–100 ms frames.
  - Play back through an `AudioContext({sampleRate: 24000})` queue that schedules each buffer at `max(ctx.currentTime, lastEnd)`. This avoids gaps and overlaps and prevents drift over 5 minutes (NFR-3). The scheduling approach is engineering practice, not sourced.
- **Mic permission.** `getUserMedia()` is secure-context-only and prompts the user.
  - Denial rejects with `NotAllowedError`; no device gives `NotFoundError`.
  - The promise may **never settle** if the user ignores the prompt, so add a UI timeout ([MDN getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)).
- **HTTPS.** `http://localhost` counts as a secure context; `http://<LAN-IP>` doesn't ([MDN secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)). OpenAI's WebRTC prerequisites also say "running on HTTPS or localhost" ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)). Any deployed or phone demo needs TLS.
- **Autoplay.** Audible playback is generally allowed only after user interaction; otherwise "the playback will likely be blocked" ([MDN autoplay](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay)).
  - Create or resume the `AudioContext` and call `audio.play()` inside the Start-button click handler.
  - OpenAI's sample falls back to showing controls if `play()` rejects ([WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc)).
- **Ephemeral key expiry.** It defaults to 10 minutes. Mint per connect, and handle 401 on SDP POST as "token expired → re-mint" ([reference](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets)). The exact error status is unverified.
- **ElevenLabs WebSocket idle close.** The socket closes after 20 s by default. Send `" "` keep-alives, or set `inactivity_timeout` (max 180) ([guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts)).
- **Transcript deltas.** Translation transcript deltas are append-only fragments: "should not insert unconditional spaces between deltas" ([translation events](https://developers.openai.com/api/reference/resources/realtime/translation-server-events)). Concatenate realtime deltas as-is too.

---

## 6. Quality and latency evaluation plan

### 6.1 WER (STT accuracy)
- **Tool:** `jiwer` (`pip install jiwer`; Apache-2.0) provides `wer`, `cer`, `mer`, `wil` and `process_words`, the last with insertion/deletion/substitution counts. As of v4, the empty-reference behavior is defined (e.g. `wer('', 'silence') == 1`) ([jiwer README](https://github.com/jitsi/jiwer)).
- **Normalization:** use OpenAI Whisper's normalizers (`from whisper.normalizers import EnglishTextNormalizer, BasicTextNormalizer`) ([source](https://github.com/openai/whisper/tree/main/whisper/normalizers)).
  - `EnglishTextNormalizer` for EN references.
  - `BasicTextNormalizer(remove_diacritics=False)` for ES, which lowercases and strips symbols and punctuation (behavior per the source code; verify output on a few samples). Keep the accents: in Spanish, accents can change meaning.
- **Set:** about 20 scripted utterances per direction (PRD Q7), including numbers, dates, names and a medical/legal flavor.
  - Record each once as WAV.
  - Replay the same audio into both modes through a virtual mic or a file-driven test harness, so the inputs are identical.
- **What to score:**
  - Realtime mode: score `conversation.item.input_audio_transcription.completed`. It is a side transcriber, so state that caveat (§1.6).
  - Cascade mode: score the STT final transcript.
  - Optionally, back-transcribe the *target* audio to measure TTS intelligibility (e.g., run `gpt-transcribe` on the recorded output, then WER against the target text).
- Also report empty, truncated and delayed transcripts separately, as OpenAI suggests ([realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription)).

### 6.2 Lightweight translation quality
- **chrF (primary) + BLEU** via `sacrebleu` (`pip install sacrebleu`) on detokenized target text against 1 reference translation per utterance ([sacrebleu README](https://github.com/mjpost/sacrebleu)). chrF is more stable than BLEU on short segments (general MT-eval knowledge; unverified in a source here).
- **COMET (optional, local):** `pip install unbabel-comet`. The default `Unbabel/wmt22-comet-da` is reference-based and scores 0–1. `Unbabel/wmt22-cometkiwi-da` is reference-free but needs HF license acceptance. CPU runs with `--gpus 0` ([COMET README](https://github.com/Unbabel/COMET)). It is a large download; skip it if time is short.
- **LLM-as-judge rubric:** score each utterance 1–5 on adequacy (meaning preserved, numbers/names exact) and 1–5 on fluency (natural Spanish/English), plus a flag for "answered instead of translated".
  - Use a different model family from the one under test (e.g., Claude judging OpenAI output) and keep the rubric prompt fixed.
  - Add a small human spot-check, as OpenAI recommends: "Automated metrics can help, but they won't catch every error" ([translation guide](https://developers.openai.com/api/docs/guides/realtime-translation)).
- **Subjective voice naturalness:** 1–5 per mode, with the rater count stated (PRD).

### 6.3 Latency measurement plan (both modes)
- **One browser clock** (`performance.now()`), as NFR-5 requires.
- **Per turn, log:**
  - `t0` = local VAD speech end (last voiced frame).
  - Realtime: `t_speech_stopped` (event arrival), `t_out_started` (`output_audio_buffer.started` arrival), and `t_first_audio` (first non-silent frame on the remote track via `AnalyserNode`).
  - Cascade: server-stamped stage durations from FastAPI (monotonic clock, durations only): STT commit→final, LLM request→first token, LLM first clause, TTS request→first byte. Then browser `t_first_audio` at the first non-silent scheduled sample.
- **Headline metric:** `t_first_audio − t0`. Report median and p90 over at least 20 turns per mode (PRD §3), at fixed VAD settings (state `silence_duration_ms`).
- **Export:** JSON/CSV per turn → `docs/benchmarks/`.
- **Soak:** a 5-minute alternating EN/ES script. Record the JS heap before and after (`performance.memory` in Chrome; non-standard, unverified on other browsers), audio-queue lag (`lastEnd − ctx.currentTime` should stay bounded), and disconnects.

---

## Open questions / not verified
- Exact WebSocket URL for a `gpt-live-transcribe` transcription session. The model page lists `v1/realtime/transcription_sessions`; the guide doesn't show the URL.
- Which input-transcription models really work inside a `type: "realtime"` session: the session reference vs model pages conflict (§1.6).
- `gpt-realtime-translate` supported-language list, and whether streamed silence is billed.
- `gpt-4o-mini-tts` per-minute cost: the audio-token rate for TTS output isn't published on the pages read.
- No published TTFT for any candidate LLM, and no published TTFB for OpenAI TTS. Measure both.
- How well browser AEC handles Web Audio (non-WebRTC) playback.
- ElevenLabs per-plan concurrency, and whether API per-character prices vary by plan.
- Freshness of local PRD/assignment copies vs GitLab HEAD.

## Sources
**OpenAI**
- Getting started with Realtime: https://developers.openai.com/api/docs/guides/realtime
- Audio and voice overview: https://developers.openai.com/api/docs/guides/audio
- WebRTC: https://developers.openai.com/api/docs/guides/voice-webrtc
- WebSockets: https://developers.openai.com/api/docs/guides/voice-websockets
- WebRTC with WARP: https://developers.openai.com/api/docs/guides/realtime-webrtc-warp
- Realtime conversations: https://developers.openai.com/api/docs/guides/realtime-conversations
- Voice activity detection: https://developers.openai.com/api/docs/guides/realtime-vad
- Realtime transcription: https://developers.openai.com/api/docs/guides/realtime-transcription
- Transcription overview: https://developers.openai.com/api/docs/guides/transcription
- Realtime translation: https://developers.openai.com/api/docs/guides/realtime-translation
- Prompting Realtime models: https://developers.openai.com/api/docs/guides/voice-prompting
- Cost optimization (Realtime costs): https://developers.openai.com/api/docs/guides/voice-latency-cost
- Text to speech: https://developers.openai.com/api/docs/guides/text-to-speech
- Latency optimization: https://developers.openai.com/api/docs/guides/latency-optimization
- Fast mode: https://developers.openai.com/api/docs/guides/fast-mode
- Rate limits: https://developers.openai.com/api/docs/guides/rate-limits
- Pricing: https://developers.openai.com/api/docs/pricing
- Deprecations: https://developers.openai.com/api/docs/deprecations
- Changelog: https://developers.openai.com/api/docs/changelog
- Client secrets reference: https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets
- Realtime server events: https://developers.openai.com/api/reference/resources/realtime/server-events
- Realtime client events: https://developers.openai.com/api/reference/resources/realtime/client-events
- Translation server events: https://developers.openai.com/api/reference/resources/realtime/translation-server-events
- Speech (TTS) reference: https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create
- Model pages:
  - https://developers.openai.com/api/docs/models/gpt-realtime
  - https://developers.openai.com/api/docs/models/gpt-realtime-mini
  - https://developers.openai.com/api/docs/models/gpt-realtime-2.1
  - https://developers.openai.com/api/docs/models/gpt-realtime-translate
  - https://developers.openai.com/api/docs/models/gpt-realtime-whisper
  - https://developers.openai.com/api/docs/models/gpt-live-transcribe
  - https://developers.openai.com/api/docs/models/gpt-4o-transcribe
  - https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe
  - https://developers.openai.com/api/docs/models/gpt-4o-mini-tts
  - https://developers.openai.com/api/docs/models/gpt-5.4-nano
  - https://developers.openai.com/api/docs/models/gpt-5.4-mini
  - https://developers.openai.com/api/docs/models/gpt-6-luna
  - https://developers.openai.com/api/docs/models/gpt-4.1-nano

**Anthropic**
- Models overview: https://platform.claude.com/docs/en/models/overview
- Claude Haiku 5.5: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Thinking (turning thinking off): https://platform.claude.com/docs/en/build-with-claude/thinking
- Effort: https://platform.claude.com/docs/en/build-with-claude/effort
- Rate limits: https://platform.claude.com/docs/en/api/rate-limits

**ElevenLabs**
- Models: https://elevenlabs.io/docs/overview/models
- API pricing: https://elevenlabs.io/pricing/api
- Latency optimization: https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization
- Understanding latency: https://elevenlabs.io/docs/eleven-api/concepts/latency
- Real-time TTS WebSocket guide: https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts
- TTS WebSocket reference: https://elevenlabs.io/docs/api-reference/text-to-speech/v-1-text-to-speech-voice-id-stream-input
- TTS stream (HTTP) reference: https://elevenlabs.io/docs/api-reference/text-to-speech/stream
- Scribe realtime commit strategies: https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/transcripts-and-commit-strategies

**OpenRouter**
- Provider routing: https://openrouter.ai/docs/guides/routing/provider-selection
- FAQ (pricing and fees): https://openrouter.ai/docs/faq

**Browser (MDN)**
- getUserMedia: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- Secure contexts: https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts
- Autoplay guide: https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay
- echoCancellation: https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation
- AudioContext constructor: https://developer.mozilla.org/en-US/docs/Web/API/AudioContext/AudioContext
- AudioWorklet: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet

**Evaluation tools**
- jiwer: https://github.com/jitsi/jiwer
- Whisper normalizers: https://github.com/openai/whisper/tree/main/whisper/normalizers
- sacrebleu: https://github.com/mjpost/sacrebleu
- COMET: https://github.com/Unbabel/COMET

**Project**
- `sources/assignment.pdf` and `docs/PRD.md`. Local box copies at `/workspace/boost/repo`, not fetched from GitLab.
