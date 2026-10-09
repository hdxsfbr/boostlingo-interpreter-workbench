# Scaling: from one demo user to 100,000 users

This document looks at what it would take to run the interpreter workbench for 10, 100, 1,000, 10,000 and 100,000 users. For each size ("tier") it covers three things: what breaks first, what has to change, and a rough monthly cost.

It is an **analysis, not a load test**. Today the app is a single-user demo on one machine. The provider prices, rate limits and per-minute costs below come from our own measurements and research (linked). Everything about usage patterns is an **assumption**, and these are marked *(estimate)*. Where we don't know a number we say "unknown" rather than guess.

How the app works today is described in [ARCHITECTURE.md](ARCHITECTURE.md). The measured numbers come from [KEY_METRICS.md](KEY_METRICS.md) and the M5 benchmark ([summary](benchmarks/results/m5/summary.md)). Provider limits come from [api-research.md](api-research.md) §5.3.

## 1. Terms used here

- **User**: a person with an account who uses the interpreter during the month, for example a clinic interpreter-desk seat.
- **Speech-minute**: one minute of someone actually talking into the app. Our measured costs are per speech-minute: the benchmark divides the total provider bill by the minutes of source speech.
- **Session**: one open conversation in the browser. A session lasts longer than the speech in it because of pauses, listening and silence.
- **Concurrency**: how many sessions (or how many people talking) at the same moment. Servers and rate limits care about concurrency, not monthly totals.
- **Peak**: the busiest moment of a normal day.
- **Realtime mode**: one OpenAI speech-to-speech model handles the whole turn. Audio goes from the browser straight to OpenAI over **WebRTC** (the browser's built-in protocol for live audio and video).
- **Cascade mode**: three steps run on our server. **STT** (speech-to-text) turns speech into text, **MT** (machine translation) translates the text, and **TTS** (text-to-speech) speaks the translation. Audio reaches our server over a **WebSocket** (a long-lived two-way connection between browser and server).
- **RPM / TPM**: requests per minute and tokens per minute, the two main rate limits providers set. A **token** is the unit providers bill and count by; for text it is roughly ¾ of a word, and audio is converted into tokens too.
- **Rate limit**: the ceiling a provider puts on how much one account can send. Going over it gets an **HTTP 429** ("too many requests") error.
- **Quota / usage tier**: a provider's monthly spending cap and the limit level that comes with it. OpenAI moves accounts up tiers (Build → Launch → Grow) as they spend more.
- **Container**: the packaged app process, run with Docker. Today there is exactly one.
- **Load balancer**: a front door that spreads incoming connections across several containers.
- **Sticky session (affinity)**: a load-balancer rule that keeps all of one session's traffic on the same container.
- **Stateless backend**: a server that keeps no conversation data in its own memory or disk, so any container can serve any request.
- **Object storage**: cloud file storage such as Amazon S3 or Azure Blob, with built-in encryption and automatic deletion rules.
- **Managed database**: a database (e.g. PostgreSQL) run by a cloud provider, with backups and failover handled for us.
- **Multi-tenancy**: one deployment serving many customer organisations (tenants) while keeping each one's data separate.
- **TURN**: a relay server that carries WebRTC audio when a network blocks direct connections, common on hospital and corporate networks.
- **BAA (Business Associate Agreement)**: the contract US healthcare law (HIPAA) requires before a vendor may handle patient health information.
- **Failover**: switching automatically to another provider or server when one fails or is throttled.

## 2. Assumptions

| # | Assumption | Value | Basis |
|---|---|---|---|
| A | Speech-minutes per user per month (`m`) | **100** | *(estimate)*: about 5 minutes of interpreted speech per working day. Not measured; real usage could be far higher for full-time interpreter desks. |
| B | Working time in a month | 22 days × 8 h = **10,560 min** | *(estimate)*: weekday business hours, one time zone. |
| C | Peak-to-average ratio (`p`) | **3×** | *(estimate)*: usage clusters in mid-morning and early afternoon. |
| D | Session-minutes per speech-minute (`k`) | **2** | *(estimate)*: half of a session is pauses and listening. |
| E | Realtime / cascade mix (`s`) | **50% / 50%** of speech-minutes | *(estimate)*: no customer data yet. |
| F | Realtime cost | **$0.1793** per speech-minute (`gpt-realtime`) | Measured, M5. `gpt-realtime-mini` measured **$0.0521**. |
| G | Cascade cost | **$0.0489** per speech-minute (OpenAI STT + `gpt-5.4-nano` + OpenAI TTS) | Measured, M5. The cost splits roughly 55% STT, 43% TTS and 3% MT. |
| H | Share of cascade minutes recorded | **20%** | *(estimate)*: recording is off by default and opt-in per session. |
| I | Prices | Vendor list prices as of 2026-10-08 | No volume discounts assumed. |

**Formulas**

- Monthly speech-minutes = `U × m`, where `U` is the number of users.
- Peak people talking at once = `U × m ÷ 10,560 × p`.
- Peak open sessions = peak people talking × `k`.
- Monthly provider cost = `U × m × (s × $realtime + (1 − s) × $cascade)`.
  - With the defaults: `U × 100 × (0.5 × 0.1793 + 0.5 × 0.0489)` = `U × 100 × $0.1141` = **$11.41 per user per month**.
  - Low-cost variant (`gpt-realtime-mini` instead of `gpt-realtime`): `U × 100 × (0.5 × 0.0521 + 0.5 × 0.0489)` = `U × 100 × $0.0505` = **$5.05 per user per month**.

**What these costs leave out**

- **Hosting, storage, monitoring and support staff.** These are listed per tier but are small next to provider costs until the top tiers.
- **Silence in cascade sessions.** In the benchmark, STT streamed 1.57 minutes of audio per speech-minute because the microphone stream keeps flowing between sentences. Real sessions with long pauses will stream more silence. That makes the cascade's real cost per session higher than $0.0489 × speech-minutes (unmeasured).
- **Short Realtime sessions.** These cost more per minute: the first-minute figure is $0.2270 because of the fixed instructions sent at the start.

**Derived load per tier** (all values *estimates* built from the assumptions above)

| Users | Speech-min / month | Peak people talking | Peak open sessions | of which Realtime (talking) |
|---|---|---|---|---|
| 10 | 1,000 | 0.3 | ~1 | 0.1 |
| 100 | 10,000 | 2.8 | ~6 | 1.4 |
| 1,000 | 100,000 | 28 | ~57 | 14 |
| 10,000 | 1,000,000 | 284 | ~570 | 142 |
| 100,000 | 10,000,000 | 2,841 | ~5,700 | 1,420 |

## 3. Provider capacity (the ceilings that matter)

The ceilings below are per account, at the OpenAI **Build** tier, from [api-research.md](api-research.md) §5.3. The per-session load figures are measured in M5.

| Provider / model | Limit (Build tier) | Load per person talking (measured) | People talking at once before throttling |
|---|---|---|---|
| `gpt-realtime` / `-mini` | 400 RPM, 200k TPM | ≈ 12.5 responses and ≈ 5,962 tokens per speech-minute (48 turns, 22,893 tokens over 3.84 min) | **≈ 32** (RPM-bound; TPM allows ≈ 33) |
| `gpt-live-transcribe` (cascade STT) | 2,000 RPM, 210k TPM | One streaming connection per session. How streamed audio counts toward TPM is **unknown**. | **unknown** |
| `gpt-5.4-nano` (cascade MT) | **unknown** (not in our research) | ≈ 5,300 tokens per speech-minute (40,699 tokens over 7.68 min) | **unknown** |
| `gpt-4o-mini-tts` (cascade TTS) | 2,000 RPM, 150k TPM | ≈ 833 characters of text per speech-minute. How TTS audio output counts toward TPM is **unknown**. | likely well above Realtime's, but **unknown** |
| Claude Haiku 5.5 (quality MT option) | Anthropic Start tier: 1,000 RPM, 2M input TPM, 400k output TPM | We call it through OpenRouter, whose own limits are **unknown** | **unknown** via OpenRouter |
| ElevenLabs (alternative TTS) | Free tier: 10,000 credits per month. Concurrency per paid plan is **unverified**. | ≈ 833 characters ≈ 833 credits per speech-minute | Free tier runs out after **≈ 12 speech-minutes per month** |

**Other provider limits**

- **Concurrent Realtime sessions.** Any cap OpenAI places on concurrent Realtime sessions is **unknown**: it is not in our research.
- **Higher tiers.** The Launch and Grow tiers raise the limits, but we did not record their values for these models, so they are **unknown**.
- **Monthly spend caps.** These are a separate ceiling: Build allows $500, Launch $5,000 and Grow $200,000 per month.

## 4. Tier by tier

### 4.1 Ten users

**Load:** about one session at a time; 1,000 speech-minutes a month.

**What breaks first**

1. **No authentication.** Today, anyone who can reach the port can use the app and mint OpenAI keys on our account. That is fine on `127.0.0.1` (only reachable from the same machine) but not for ten people on different machines. This is the first blocker, before any capacity issue.
2. **ElevenLabs free tier.** 1,000 speech-minutes would need about 833,000 characters, against 10,000 free credits. Any real ElevenLabs use exhausts the free tier on day one. The app's budget guard (`core/budget.py`, with the ledger in `data/elevenlabs_ledger.json`) caps ElevenLabs at 1,500 characters per session and 8,000 per month. When a cap is reached it stops ElevenLabs and tells the user to switch TTS to OpenAI, so this fails safely but needs a manual switch.
3. **Local files.** Session logs and recordings sit on one disk with no backup. A lost machine means lost data. That's acceptable for a pilot only if the users know.

**Capacity:** everything else is far below every limit. One container handles a handful of sessions; the exact capacity is unmeasured, but our benchmark runs one session at a time without strain.

**Required changes**

- **A login in front of the app.** A single sign-on proxy is enough at this size. The ephemeral-key endpoint must sit behind it.
- **Hosting.** Move from a laptop to one small cloud VM with HTTPS (the browser requires HTTPS for microphone access off `localhost`).
- **A paid ElevenLabs plan,** if ElevenLabs is offered. Otherwise keep the OpenAI-only cascade.
- **Nightly backups** of `data/`, if recordings are kept.

**Rough monthly cost**

- Providers: `10 × 100 × $0.1141` = **≈ $114** (low-cost variant ≈ $51).
- Hosting: one small VM, roughly tens of dollars *(estimate)*.

### 4.2 One hundred users

**Load:** about 3 people talking and ~6 sessions open at peak; 10,000 speech-minutes a month.

**What breaks first**

1. **OpenAI monthly spend cap.** ≈ $1,141 a month exceeds the Build tier's $500 cap, so requests would start failing mid-month. The account must move to Launch ($5,000 cap). This is a billing setting, not code, but it is the first hard stop.
2. **No tenants or roles.** A hundred users usually means several departments or customers. Today the app has no idea who a user is, and every session log sits in one folder.
3. **Recordings with no encryption at rest.** About 8.7 GB of WAV recordings are kept at a time (formula in §5), in plain files on the server's disk. For patient conversations this is the main compliance gap.
4. **No observability.** Errors go to the container log, and there are no dashboards or alerts, so a broken provider key would only be noticed when users complain.

**Required changes**

- **Real authentication.** Use an identity provider (e.g. Microsoft Entra ID or Okta) with per-user accounts and an admin role.
- **Per-tenant data separation.** Start tagging every session, log line and recording with a tenant id.
- **Encrypted storage.**
  - Move recordings to encrypted object storage with a 30-day lifecycle rule.
  - The rule replaces the in-process retention sweep, which only works on a local disk.
- **Basic monitoring.**
  - Uptime checks.
  - Error-rate and latency dashboards fed by the turn metrics already in the session logs.
  - Alerts on provider 429s and 5xx errors.
- **Throttling that users can understand.** The cascade already retries a provider call up to 2 times when it fails before producing output, with backoff that honours the `Retry-After` header (`core/retry.py`). It does not retry once audio has started. Add a clear "busy, retrying" state in the UI and count 429s per provider.
- **Compliance groundwork, if any customer is a healthcare provider.**
  - Get a **BAA** with every vendor that touches audio or text: OpenAI, OpenRouter/Anthropic, ElevenLabs and the cloud host.
  - Whether each vendor will sign one for these specific APIs is **unverified**. Vendors that won't must be switched off for that tenant.

**Rough monthly cost**

- Providers: `100 × 100 × $0.1141` = **≈ $1,141** (low-cost ≈ $505).
- Hosting and storage: still small, roughly low hundreds of dollars *(estimate)*.

### 4.3 One thousand users

**Load:** about 28 people talking and ~57 sessions open at peak, 14 of them talking in Realtime mode; 100,000 speech-minutes a month.

**What breaks first**

1. **The single container.**
   - Today one Python process holds every cascade session in memory. It runs the audio buffering, WebSocket handling and file writes on one event loop (Python's single-threaded scheduler for concurrent tasks).
   - At ~57 open sessions, roughly half of them cascade, we don't know whether one process keeps latency flat. Its CPU and WebSocket capacity are **unmeasured**.
   - If the container restarts, every live cascade session drops and its in-memory state is lost.
2. **Spend cap and rate headroom.**
   - ≈ $11,410 a month exceeds Launch's $5,000 cap, so the account needs the Grow tier.
   - 14 people talking in Realtime at once is within the Build-tier rate limit of ≈ 32, but a busy hour at twice our assumed peak would hit it. The limits at higher tiers are unknown.
3. **Local JSONL logs and the retention sweep.**
   - Every session writes a log file on the container's disk, about 13 KB per speech-minute, so roughly 1.3 GB a month.
   - With more than one container, logs and recordings would be scattered across machines.
   - The sweep in each container would only see its own disk.
4. **Network reach.** Some hospital networks block WebRTC. The app has a relay fallback (`/ws/realtime`) that carries Realtime audio through our server instead. Every relayed session adds load to the container, and TURN has not been tested.

**Required changes**

- **Horizontal scaling.**
  - Run several containers behind a load balancer.
  - Cascade and relay WebSockets need **sticky sessions** because the session's state lives in that container's memory.
  - Health checks should drain a container before restarting it.
- **Make storage stateless.**
  - Session logs and metadata go to a **managed database**.
  - Recordings go straight to object storage.
  - The ElevenLabs credit ledger, today a local JSON file, moves to the database so all containers share one counter.
- **A write queue.** Session-log and recording writes go through a queue so a slow database never delays audio.
- **A load test** to measure sessions per container (CPU, memory and latency at 10, 25 and 50 cascade sessions), so the container count is based on data.
- **Provider headroom.**
  - Request higher limits from OpenAI.
  - Watch the `x-ratelimit-*` headers and Realtime's `rate_limits.updated` events.
  - Add a fallback: if Realtime is throttled, offer `gpt-realtime-mini` or the cascade. The app already supports both modes, so this is a routing rule, not new pipelines.
- **Per-tenant quotas** (minutes per month), so one customer can't consume the whole account's limit.
- **TURN.** Test on locked-down networks. Either rely on the relay fallback, capacity-planned, or add a TURN service.

**Rough monthly cost**

- Providers: `1,000 × 100 × $0.1141` = **≈ $11,410** (low-cost ≈ $5,050).
- Hosting: a few containers, a managed database, object storage (~86 GB of recordings kept) and monitoring: roughly $1,000–2,000 *(estimate)*.

### 4.4 Ten thousand users

**Load:** about 284 people talking and ~570 sessions open at peak, 142 of them talking in Realtime mode; 1,000,000 speech-minutes a month.

**What breaks first**

1. **OpenAI rate limits.**
   - 142 people talking in Realtime at once is about 4× the Build-tier ceiling of ≈ 32 (400 RPM).
   - The cascade's STT, MT and TTS limits for this load are unknown; nano's limits are not in our research.
   - Whether the Grow tier covers this is **unknown**. If it doesn't, users get 429 errors mid-sentence, the worst failure for live interpreting.
2. **Single-provider dependency.** Every default path runs on OpenAI. An OpenAI outage or throttling event stops all users at once.
3. **Cost.**
   - ≈ $114,100 a month at the 50/50 mix is now a business decision.
   - The mode mix matters most: moving Realtime traffic to `gpt-realtime-mini` roughly halves the bill (≈ $50,500) for a small quality drop (chrF 73.3 vs 76.1 English→Spanish in M5).
4. **Model retirements.** `gpt-4o-mini-tts` retires Jan 6 2027 and `gpt-realtime`/`-mini` Jan 20 2027. At this size, a forced model change needs a re-benchmark and a staged rollout, not a config edit on one machine.

**Required changes**

- **Several provider accounts or an enterprise agreement with OpenAI.** Get committed rate limits (and, for healthcare, a BAA) in writing.
- **Multi-provider failover.**
  - Use the adapter design (6 adapters today: STT 1, MT 3, TTS 2) to add second providers for STT and TTS.
  - Route around 429s and outages automatically.
  - The adapter layer is already config-driven, so the new work is health tracking and routing.
- **Admission control.** When capacity is short, queue or refuse new sessions with a clear message rather than letting live sessions degrade.
- **Cost controls.**
  - Per-tenant budgets and alerts.
  - Default to the cheaper Realtime model unless a tenant pays for the premium one.
  - Stop streaming silence to STT.
- **Regional deployment.** Run containers near users (e.g. US East and US West) to keep the server leg of cascade latency low, and use providers' regional endpoints where they exist.
- **HIPAA-eligible infrastructure.**
  - A cloud account under a BAA, encrypted database and storage, and access logging.
  - An audit trail for every recording view and deletion, extending the audit line already written in the session log.
- **Full observability.**
  - Per-tenant dashboards for latency (the same H measure the benchmark uses), error rate and cost per minute.
  - On-call alerts.

**Rough monthly cost**

- Providers: `10,000 × 100 × $0.1141` = **≈ $114,100** (low-cost ≈ $50,500).
- Hosting:
  - Tens of containers across two regions, database, ~865 GB of recordings kept, and monitoring: roughly $10,000–20,000 *(estimate)*.
  - Plus engineering and on-call staff.

### 4.5 One hundred thousand users

**Load:** about 2,841 people talking and ~5,700 sessions open at peak, 1,420 of them talking in Realtime mode; 10,000,000 speech-minutes a month.

**What breaks first**

1. **Cost.**
   - ≈ $1.14 million a month in provider fees at the 50/50 mix, or ≈ $505,000 at the low-cost mix.
   - Per-minute vendor pricing becomes the dominant cost of the product.
2. **Provider capacity.**
   - 1,420 people talking in Realtime at once is ~44× the Build-tier ceiling.
   - Whether any public tier supports this is **unknown**; it would need a negotiated agreement.
3. **Recording and log volume.**
   - ≈ 8.7 TB of recordings kept at a time and ≈ 130 GB of session logs a month.
   - Both are manageable in object storage, but deletion on schedule, legal holds and access audits become a compliance programme rather than a feature.

**Required changes** (all of the 10,000-user tier, plus:)

- **Self-hosted STT and TTS for the cascade.**
  - Run open speech models on our own GPUs to replace the 98% of cascade cost that is STT + TTS.
  - The adapter layer allows this without changing the pipeline.
  - The quality and latency of self-hosted models are **untested** here and would need the same M5 benchmark before any switch.
  - GPU fleet cost is **unknown** without a sizing test.
- **Negotiated contracts** with at least two speech-to-speech or STT/TTS vendors, for volume pricing, committed capacity and BAAs.
- **Multi-region, active-active deployment** with data residency per tenant.
- **A dedicated platform team:** security reviews, penetration tests, SOC 2 / HIPAA audits, and 24/7 on-call.

**Rough monthly cost**

- Providers at list price: `100,000 × 100 × $0.1141` = **≈ $1,141,000** (low-cost ≈ $505,000).
- Volume discounts and self-hosting could lower this substantially, but by how much is **unknown**.
- Infrastructure is **unknown** without the GPU sizing test; tens of thousands of dollars a month at least *(estimate)*.

## 5. Storage growth

Storage is not the first thing to break, but it grows linearly with use and carries the compliance risk.

**Recordings (WAV)**

- **Formula:** recordings kept = monthly cascade speech-minutes × share recorded × MB per speech-minute.
- **MB per speech-minute: ≈ 8.65 MB.**
  - WAV measured at 2.88 MB per audio-minute per side.
  - The cascade records both the input stream (1.57 audio-minutes per speech-minute, because silence is streamed too) and the translated output (1.43 audio-minutes per speech-minute).
  - So 2.88 × (1.57 + 1.43) ≈ 8.65 MB.
- **Why "kept" equals one month:** with the 30-day retention, the amount stored at any time is about one month of recordings.
- **Realtime recordings** are compressed browser audio (webm/opus). Their size per minute is **unmeasured**, but it should be several times smaller than WAV.

**Session logs**

- **≈ 13 KB per speech-minute:** about 12.5 turns per speech-minute × ≈ 1.07 KB per log line.

| Users | Recordings kept (20% of cascade min) | Session logs per month |
|---|---|---|
| 10 | ~0.9 GB | ~13 MB |
| 100 | ~8.7 GB | ~130 MB |
| 1,000 | ~87 GB | ~1.3 GB |
| 10,000 | ~865 GB | ~13 GB |
| 100,000 | ~8.7 TB | ~130 GB |

## 6. Numbers we could not ground

These need a load test, a vendor conversation or real customer data before the plan above can be trusted:

**Usage assumptions**

- Speech-minutes per user, peak ratio, session-to-speech ratio, the Realtime/cascade mix and the recording share are all assumptions.

**Provider limits**

- OpenAI concurrent Realtime session caps, and Launch/Grow tier limits for every model we use.
- `gpt-5.4-nano` rate limits.
- How streamed STT audio and TTS output count toward TPM.
- OpenRouter's limits for Haiku.
- ElevenLabs concurrency per paid plan.

**Our own capacity**

- Sessions per container (CPU, memory, WebSockets).
- Relay-mode server load.
- Whether TURN is needed on customer networks.

**Storage and cost**

- Realtime recording size per minute.
- Cascade cost with real-world silence.
- Volume discounts.
- Self-hosted STT/TTS quality, latency and GPU cost.

**Compliance**

- Which vendors will sign a BAA for these specific APIs.

## 7. Summary

| Users | Peak people talking *(est.)* | What breaks first | Biggest required change | Provider cost / month (formula: U × 100 × $0.1141) | Low-cost mix (U × 100 × $0.0505) |
|---|---|---|---|---|---|
| 10 | <1 | No authentication; ElevenLabs free tier | Login in front of the app, HTTPS hosting | ≈ $114 | ≈ $51 |
| 100 | ~3 | OpenAI Build spend cap ($500); unencrypted local recordings | Real auth + tenants, encrypted object storage, monitoring | ≈ $1,141 | ≈ $505 |
| 1,000 | ~28 | Single container with in-memory sessions; Launch spend cap | Horizontal scaling with sticky sessions, managed DB, write queue, load test | ≈ $11,410 | ≈ $5,050 |
| 10,000 | ~284 | OpenAI rate limits (≈ 32 talking Realtime at Build tier); single-provider dependency | Enterprise limits + multi-provider failover, per-tenant quotas, HIPAA-eligible infra, regions | ≈ $114,100 | ≈ $50,500 |
| 100,000 | ~2,841 | Cost and provider capacity | Self-hosted STT/TTS, negotiated contracts, multi-region platform team | ≈ $1,141,000 | ≈ $505,000 |
