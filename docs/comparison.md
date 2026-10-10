# Realtime vs. Cascade: how to build an AI interpreter

**What we compared.** Two ways to interpret a live English–Spanish conversation. In **Realtime**, one OpenAI model (`gpt-realtime`) hears the speaker and speaks the translation. In the **cascade**, three services run in a chain: **speech-to-text** writes down what was said, a **translation model** translates that text, and **text-to-speech** reads the translation aloud. Each setup was measured the same way on 48 test sentences, about half of them medical or legal, on 8 Oct 2026. Full method and numbers: [comparison-details.md](comparison-details.md).

## Recommendation

| Scenario | Use | Why |
|---|---|---|
| **Live medical or legal conversations** | **Realtime** (`gpt-realtime`) | Fastest on short sentences and steadiest (about 1.0 s, 1.4 s in slower cases); never answered instead of translating. Costs most: about 18¢ per minute of speech. |
| **Terminology, an audit trail or keeping data in-house matter more than a second** | **Cascade** with Claude Haiku as the translator | Best automated translation scores; we see and control the text at every step. About 2.3 s on short sentences: within limits, but slower. |
| **High volume at low cost** | **Realtime** with the smaller `gpt-realtime-mini` | Near `gpt-realtime` speed at about 5¢ per minute, like the cheapest cascade. Weaker English→Spanish, so lower-stakes calls. |
| **Uncommon language pairs** | **Cascade** | Each step can use the best vendor for that language (only English–Spanish was tested). |

## Results

**How to read this.** **Latency** is the delay from when the speaker stops to when the listener first hears the translation, measured in the browser the same way for both setups. The brief's limits are under 1.5 s for Realtime, and under 3 s for the cascade (ideally under 2 s). Speakers used **push-to-talk**: they hold a button while talking, like a walkie-talkie. Our tests let go 0.45 s after the last word, and every figure includes that 0.45 s. **Typical (p50)** means half of the turns were faster; **slower case (p90)** means 9 in 10 were faster. **chrF** is a 0–100 score of how closely a translation matches a reference translation (higher is better; valid rewordings lose points too, so compare scores relatively). Cost is per minute of speech, at 8 Oct 2026 list prices. All 348 test turns completed; times are rounded to 0.1 s.

| Setup | Delay, typical / slower case | Delay on short sentences (typical) | Translation score, EN→ES / ES→EN (chrF) | Cost per minute |
|---|---|---|---|---|
| Realtime, `gpt-realtime` | 1.0 s / 1.4 s | 1.0 s | 76.1 / 81.2 | $0.179 |
| Realtime, `gpt-realtime-mini` | 1.0 s / 1.4 s | 1.2 s | 73.3 / 81.7 | $0.052 |
| Cascade, OpenAI translator | 1.7 s* / 2.2 s | 1.8 s | 72.9 / 78.4 | $0.049 |
| Cascade, Claude Haiku translator | 2.1 s* / 2.7 s | 2.3 s | 81.3 / 83.6 | $0.048 |
| Cascade, ElevenLabs voice (12 sentences only) | 1.4 s* / 1.6 s | 1.5 s | 64.6 / 80.7 | $0.059 |

\*Measured to the first audio of the **last** sentence (DESIGN A21). The cascade translates a long turn's first sentence while the person is still talking and holds it until they let go, so the literal first sound comes sooner: 0.5 s / 2.0 s (OpenAI), 1.7 s / 2.5 s (Haiku), 0.5 s / 1.6 s (ElevenLabs). That mostly measures the 0.45 s release and is not comparable with Realtime.

**Latency.**
- **Realtime** stays near 1.0 s for short and long turns alike, under its 1.5 s limit even in slower cases. **The cascade** on short sentences takes 1.8 s typical with the OpenAI translator (2.2 s in slower cases) and 2.3 s with Haiku. **Hands-free mode** (detecting silence instead of a button press) adds that wait and broke up long monologues, so push-to-talk is better.

**Quality.**
- **Translation scores:** Haiku first, then `gpt-realtime`; the gaps are mostly in English→Spanish.
- **Speech recognition** was accurate on our clear computer voices: word error rate (WER, the share of words written down wrong) about 0.01, or 1 in 100, in English; in Spanish 0.01 for Realtime and 0.01–0.04 for the cascade. Real callers will do worse.
- **Realtime's main risk is answering instead of translating:** early on it replied to the speaker in 2 of 5 turns. Telling it every turn to "translate only, never answer" fixed it (0 of 96 since).
- **Blind human ratings** (one listener, Andre, not told the setup; 12 sentences each; 1–5 against a reference translation). Meaning almost always came through; the OpenAI voice in both cascades scored lowest, so Haiku, best on chrF, rated last: the rankings disagree. One rater is a sanity check, not proof.

| Average rating, 1–5 | Realtime | Cascade, OpenAI | Cascade, Haiku | Cascade, ElevenLabs |
|---|---|---|---|---|
| Accuracy / fluency / natural voice | 5.0 / 5.0 / 4.8 | 4.8 / 4.8 / 3.5 | 4.9 / 4.4 / 3.3 | 5.0 / 4.9 / 4.2 |

**Cost.**
- **Realtime ($0.179/min) costs about 3.7× the cascade,** mostly for audio, partly because recent conversation is re-read and billed on every turn. `gpt-realtime-mini` costs $0.052/min.
- **In the cascade,** speech-to-text is about 55% of the cost, the voice 43% and translation 3%, so a better translator costs almost nothing extra.

**Control.**

| | Realtime | Cascade |
|---|---|---|
| Changing vendors | One vendor | Swap any step without changing the app |
| Terminology | General instructions only | Translator glossary, e.g. drug names (built, untested) |
| Voice | One voice per session | Chosen per language and vendor |
| Audit trail | Transcripts (speaker side from a second model) | Text from every step |
| Lock-in | Models retire 20 Jan 2027 (successor exists) | Its OpenAI parts retire in 2027 too; each replaceable |
| Running it | Simpler: browser talks to OpenAI directly | Audio via our server; 3 vendors; tuning |

## Privacy and compliance

*General background, not legal advice.*
- **Where the data goes:** in the cascade, audio and text pass through our servers, so we decide what is logged, recorded and kept (each vendor still sees its step). Realtime sends audio straight to OpenAI.
- **Health care:** HIPAA doesn't require keeping recordings, but any recording or transcript of a medical conversation is protected health information: it needs encryption, access control and a business associate agreement (BAA) with each vendor that handles it.
- **SOC 2** is an audit framework that, among other things, checks that a company follows its own retention policy. **Legal settings vary:** some US states require all parties to consent to recording.
- **The workbench** logs each turn's text and timings on our server. Audio recording is opt-in (enabled on the server and switched on per session); each saved file is logged and deleted automatically after 30 days by default.

## Limitations

48 computer-voiced sentences per setup (12 for ElevenLabs); one machine, network and day; one reference translation each; one human rater so far (more can rate in the app's Review tab). Prices from 8 Oct 2026; most models tested retire in early 2027.
