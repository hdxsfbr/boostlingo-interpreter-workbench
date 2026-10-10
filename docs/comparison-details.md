# Realtime vs. Cascade: technical details

This is the companion to [comparison.md](comparison.md), the two-page write-up. It explains how we measured and gives the full numbers, plus what we learned while building the cascade. Terms are explained as they come up.

The raw data is in [`benchmarks/results/m5/`](benchmarks/results/m5/):
- [`summary.md`](benchmarks/results/m5/summary.md);
- [`results.json`](benchmarks/results/m5/results.json);
- one spreadsheet (CSV) per setup, with one row per test sentence.

Earlier tuning work is in [`m4-tuning.md`](benchmarks/m4-tuning.md) and [`m2-realtime-smoke.md`](benchmarks/m2-realtime-smoke.md). Prices are in [`config/pricing.yaml`](../config/pricing.yaml), as of 8 Oct 2026. Design decisions are cited as "DESIGN A1" and so on, after the amendments in [`DESIGN.md`](DESIGN.md).

## The setups we tested

| Name in the data | What it is |
|---|---|
| `realtime` | OpenAI's `gpt-realtime`. One model hears the speech and speaks the translation |
| `realtime-mini` | The same, with the smaller and cheaper `gpt-realtime-mini` |
| `cascade-openai` | The cascade with OpenAI parts throughout: speech-to-text `gpt-live-transcribe`, translator `gpt-5.4-nano`, text-to-speech `gpt-4o-mini-tts` |
| `cascade-openai-nomerge` | The same, with short-fragment merging switched off (see finding 2) |
| `cascade-haiku` | The OpenAI cascade with Anthropic's `claude-haiku-5.5` as the translator, reached through OpenRouter (a service that resells many vendors' models through one account) |
| `cascade-elevenlabs` | The OpenAI cascade with ElevenLabs Flash v2.5 as the voice. Only 12 sentences, to save free-tier credits |

## How we measured

**Test sentences.**
- There were 24 per direction (English→Spanish and Spanish→English): 8 short, 10 medium and 6 long (several sentences each). About half were medical or legal: dosages, drug names, dates and case numbers.
- Each sentence came with a reference translation.
- The test audio was generated with OpenAI voices, different from the interpreter's own voice, rather than recorded by people.

**Automation.**
- A browser-automation tool (Playwright) runs the real app in a Chrome window with no screen, and plays each test clip in place of the microphone.
- Both setups go through exactly the code a user would use.

**Latency.**
- It is measured in the browser, on one clock: from the last moment the speaker's voice is detected to the first audible sound of the translation.
- With push-to-talk (the speaker holds a button while talking), the test "lets go" 0.45 s after the last word, the same for every setup (DESIGN A2/A5). That 0.45 s is included in the main figures.
- **System delay** subtracts it, showing how fast the system itself is.

**Percentiles.**
- **p50 (typical):** the median; half of the turns were faster.
- **p90 (slower case):** 9 in 10 turns were faster. p95: 19 in 20 were faster.
- With an even number of turns, the median is the average of the two middle values. Haiku's 2060 ms, for example, sits between 2048 and 2071 ms.

**Runs.**
- Each setup ran its 48 sentences once, one setup at a time, on one lab machine (hdx-lab) on 8 Oct 2026.
- `cascade-openai` and its no-merge comparison each ran twice, 96 turns each.

**Quality scores.**
- **chrF** is a 0–100 score of how closely a translation matches the reference translation, based on matching character sequences. Higher is better. It is scored across all sentences of a direction together, using the standard `sacrebleu` tool.
- **BLEU** is an older 0–100 score from the same tool. It matches whole words, so it is harsher on valid rewordings.
- **Word error rate (WER)** is the share of words that speech-to-text got wrong compared with the script; 0.01 means 1 word in 100. It is computed with the `jiwer` tool after standard text clean-up.
  - For Realtime, WER scores a separate transcription model (`gpt-4o-transcribe`) that writes the transcript on the side, not what the interpreting model itself heard.
- **Round-trip WER:** we recorded what the listener actually heard, transcribed it again with `gpt-4o-transcribe`, and compared it with the text the system meant to say. This checks that the voice is clear.
- **"Answered" rate:** an AI judge (`gpt-5.4-mini`) flagged turns where the system replied to the speaker instead of translating.

**Cost per minute.** We take the usage each service reported (audio seconds, tokens or characters), multiply by the listed prices, and divide by the minutes of actual speech in the test clips. A **token** is the small unit of text or audio that AI services bill by.

## Full results

All 348 turns completed with **0 failures**.

**Latency (milliseconds; 1,000 ms = 1 s).** The "last-part delay" column applies only to the cascade (see the note under the table).

| Setup | n | Delay p50 / p90 | System delay p50 / p90 | Short p50 | Medium p50 | Long p50 | Last-part delay p50 / p90 |
|---|---|---|---|---|---|---|---|
| realtime | 48 | 1002 / 1355 | 548 / 898 | 1024 | 1033 | 990 | – |
| realtime-mini | 48 | 1013 / 1367 | 560 / 911 | 1223 | 973 | 1174 | – |
| cascade-openai | 96 | 1744 / 2196 | 1286 / 1742 | 1791 | 1750 | 1684 | 1715 / 2149 |
| cascade-openai-nomerge | 96 | 1647 / 2143 | 1189 / 1690 | 1664 | 1647 | 1638 | 1638 / 2114 |
| cascade-haiku | 48 | 2060 / 2671 | 1604 / 2214 | 2287 | 2042 | 1993 | 2039 / 2671 |
| cascade-elevenlabs | 12 | 1443 / 1607 | 988 / 1154 | 1461 (n=4) | 1424 (n=4) | 1444 (n=4) | 1430 / 1560 |

- **Delay = speech end to the first audio of the last sentence (DESIGN A21).** The cascade cuts a turn into pieces at the speaker's pauses and starts translating the first piece while the person is still talking; that piece is held until they let go and is heard almost at once. On such split turns the delay is taken at the last piece's audio (the last-part estimate below), so long turns are no longer flattered.
- **Literal first sound¹:** cascade-openai 545 / 2030 ms (medium 530, long 525), no-merge 534 / 1943, Haiku 1654 / 2485 (medium 819, long 520), ElevenLabs 528 / 1551 (system delay 83 / 1572, 77 / 1487, 1198 / 2033, 74 / 1098). On split turns that is the held first piece, mostly the 0.45 s release; Realtime is unchanged (it never splits).
- **Last-part delay:** the server's estimate of when the final piece's audio is ready, not counting the last network hop.
- **Short sentences at p90:** 2247 ms for cascade-openai and 2844 ms for cascade-haiku.
¹ Before 10 Oct 2026 these literal figures were published as the headline.
- **Brief targets:** Realtime under 1.5 s; cascade under 3 s, ideally under 2 s.
  - Both Realtime setups meet theirs at p90 for every sentence length.
  - cascade-openai meets the 2 s aim at p50 but not at p90.
  - cascade-haiku misses the 2 s aim on short sentences but stays under 3 s.

**Quality and cost.**

| Setup | chrF EN→ES / ES→EN | BLEU EN→ES / ES→EN | WER EN / ES | Answered | Round-trip WER | $/min | $/min, first minute | $ total | Speech minutes |
|---|---|---|---|---|---|---|---|---|---|
| realtime | 76.1 / 81.2 | 57.5 / 67.7 | 0.010 / 0.011 | 0.000 | 0.019 | 0.1793 | 0.2270 | 0.6886 | 3.84 |
| realtime-mini | 73.3 / 81.7 | 47.9 / 67.2 | 0.006 / 0.011 | 0.000 | 0.011 | 0.0521 | 0.0575 | 0.2000 | 3.84 |
| cascade-openai | 72.9 / 78.4 | 42.7 / 53.5 | 0.008 / 0.032 | 0.010 | 0.020 | 0.0489 | 0.0551 | 0.3752 | 7.68 |
| cascade-openai-nomerge | 69.8 / 76.6 | 36.2 / 50.2 | 0.019 / 0.021 | 0.000 | 0.032 | 0.0497 | 0.0573 | 0.3819 | 7.68 |
| cascade-haiku | 81.3 / 83.6 | 58.4 / 71.0 | 0.010 / 0.036 | 0.021 | 0.050 | 0.0479 | 0.0545 | 0.1841 | 3.84 |
| cascade-elevenlabs | 64.6 / 80.7 | 25.6 / 61.7 | 0.011 / 0.013 | 0.000 | 0.022 | 0.0594 | 0.0594 | 0.0657 | 1.11 |

The ElevenLabs quality figures rest on 6 sentences per direction, so treat them as noisy.

**Hands-free mode** (the app detects silence instead of the speaker pressing a button). This comes from the M4 tuning runs, with `gpt-realtime-mini` and the OpenAI cascade, 12 sentences per setting.
- **The wait for silence is added to every turn.** For Realtime, typical delay was about 1.0, 1.1 and 1.5 s with silence windows of 300, 400 and 500 ms (985, 1119 and 1541 ms).
- **Cascade at 500 ms:** 1524 / 1753 ms (p50 / p90). Shorter windows split sentences in the middle.
- **Long monologues broke in both modes,** because the microphone is muted while the first part's translation plays. That is why we recommend push-to-talk, and why the final tests used it.

**Blind human ratings.** One rater (Andre) listened to 48 anonymised, shuffled clips: the same 12 sentences (6 per direction) for each of 4 setups (`realtime-mini` was not rated). Each clip is the spoken output exactly as the listener heard it. He scored each from 1 (very poor) to 5 (excellent) on:
- **adequacy (accuracy):** does it carry the full meaning, including numbers, names and negations?
- **fluency:** is it grammatical, natural target-language speech?
- **naturalness:** does the voice sound natural (rhythm, pronunciation, no glitches)?

The rating sheet showed the source sentence and one reference translation (described as one acceptable rendering, not the only one), so scores are anchored on that reference. The key linking clips to setups is a separate file that the kit instructions say to open only after rating. Script: `backend/eval/blind_results.py`; full output, including the per-direction tables and every clip scored 3 or lower: [`benchmarks/blind/results.md`](benchmarks/blind/results.md) and `results.csv`.

Each cell is mean / median, then standard deviation (sd, the typical spread around the mean) and range. "Composite" is the average of the three means.

| Setup | Adequacy | Fluency | Naturalness | Composite | chrF, same 12 sentences | chrF, all M5 sentences |
|---|---|---|---|---|---|---|
| realtime | 5.00 / 5 (0.00, 5–5) | 5.00 / 5 (0.00, 5–5) | 4.75 / 5 (0.45, 4–5) | 4.92 | 71.9 | 78.6 |
| cascade-openai | 4.83 / 5 (0.39, 4–5) | 4.75 / 5 (0.45, 4–5) | 3.50 / 3 (0.67, 3–5) | 4.36 | 70.9 | 75.6 |
| cascade-haiku | 4.92 / 5 (0.29, 4–5) | 4.42 / 5 (0.79, 3–5) | 3.33 / 3 (0.65, 3–5) | 4.22 | 78.4 | 82.4 |
| cascade-elevenlabs | 5.00 / 5 (0.00, 5–5) | 4.92 / 5 (0.29, 4–5) | 4.17 / 4 (0.58, 3–5) | 4.70 | 72.5 | 72.5 |

By direction (composite, 6 clips each): EN→ES realtime 4.89, cascade-openai 4.28, cascade-haiku 4.22, cascade-elevenlabs 4.67; ES→EN 4.94, 4.44, 4.22, 4.72. The order is the same in both directions.

- **Adequacy is near the ceiling for every setup** (4.83–5.00). Only 3 of 48 clips lost a point on meaning (2 cascade-openai, 1 cascade-haiku, all English→Spanish), so the ratings cannot separate the setups on accuracy.
- **Naturalness drives the ranking.** Both OpenAI-voiced cascades (same `gpt-4o-mini-tts` voice) averaged 3.3–3.5, with a median of 3; ElevenLabs averaged 4.2 and Realtime 4.8. This is a judgment on the voice, not the translation.
- **Fluency:** cascade-haiku was lowest (4.42), with two 3s on long English→Spanish sentences, although it has the highest chrF.
- **Comparison with chrF:** the rankings **disagree**. On the same 12 sentences chrF ranks Haiku 1st, ElevenLabs 2nd, Realtime 3rd and cascade-openai 4th; the composite rating ranks Realtime 1st, ElevenLabs 2nd, cascade-openai 3rd and Haiku 4th. chrF scores text overlap with one reference; the listener judged the audio, where the voice dominates and valid rewordings are not penalised. With one rater and n = 12, differences of a few tenths are within noise; only the voice gap (about 1 point) is large.
- **Effect on the recommendation:** none. Realtime rated best, which supports it for live conversations. The Haiku cascade is recommended for control and terminology, not for a better-sounding result, and its lower voice scores come from the OpenAI voice, which can be swapped (ElevenLabs rated 0.7–0.8 higher).

## What we learned building it

1. **Stopping Realtime from answering instead of translating** (DESIGN A1).
   - With only a general instruction, `gpt-realtime-mini` replied to the speaker in 2 of 5 Spanish→English turns in an early test ("…seek medical attention").
   - With push-to-talk the app knows who is speaking, so every request now carries "say only the faithful translation; never answer".
   - Together with the fixed 0.45 s release, all 20 following test turns were correct translations, and the AI judge flagged 0 of 96 Realtime turns in the final runs.
   - Hands-free mode can't use this fix, because the direction isn't known in advance.
2. **Merging short fragments** (DESIGN A8).
   - Cutting turns at short pauses produced choppy translations: "Do you have / any allergies?" became "¿Tienes? / ¿Alguna alergia?".
   - Now a short piece without end punctuation is joined to the next one before it is translated.
   - Against the no-merge run, chrF rose from 69.8 to 72.9 (EN→ES) and from 76.6 to 78.4 (ES→EN). Short sentences got 0.22 s slower (typical 1571 → 1791 ms); medium and long were unchanged. It stays on.
3. **Translating the partial transcript early** (DESIGN A4, M4).
   - Speech-to-text sends a running draft while the person speaks. The cascade starts translating and voicing that draft at once, holds the audio, and plays it only if the final transcript matches; otherwise it redoes the work.
   - This cut the last-part delay from about 2.08 s to 1.58 s typical, with 0 mismatches in 242 uses during tuning. The cost is some extra translation calls when the draft changes.
4. **A backup request for slow responses** (DESIGN A7).
   - If the translator or the voice has produced nothing after 1.5 s, an identical second request starts, and whichever answers first wins.
   - Before this, 3 of 96 tuned cascade turns hit the 3 s time limit. Afterwards, 0 of 192 did in the two final cascade-openai runs.
   - The backup fired 7 times and won 3. These counts slightly undercount, because repeats within one turn are counted once.
5. **Accuracy vs. speed in speech-to-text.** A faster speech-to-text setting saved about 0.2 s, but raised word error from 0.029 to 0.074, so we kept the accurate setting.
6. **Where the cascade's time now goes.** The slowest step is the voice: `gpt-4o-mini-tts` takes about 530–700 ms to start speaking.
7. **Stability.** Five-minute sessions in both modes had 0 failures, errors or reconnects, flat memory use, and at most 42 ms of drift in delay.

## Cost breakdown

**Realtime ($0.6886 for 3.84 min of speech).**

| Item | Usage | Cost |
|---|---|---|
| Audio in | 9,834 tokens | $0.315 |
| Audio out | 4,725 tokens | $0.302 |
| Text (instructions and transcripts) | in, out and cached | $0.049 |
| Side transcription | 3.84 min | $0.023 |

- **Audio is about 90% of the cost.**
- **Input audio was 4.3× the planning estimate.** The estimate assumed 1 audio token per 100 ms of speech, which would be about 2,300 tokens; 9,834 were billed.
- **Re-billed history is the likely main cause.** The app keeps the last one or two turns as context, the model re-reads them on every reply, and no audio was billed at the cheaper "cached" rate. The held push-to-talk audio adds a little more. This explanation is our inference.
- **The first minute costs more:** $0.227 per minute.
- **The pre-build estimate** was about $0.10 per minute plus extras (DESIGN §9).

**Cascade, split by step** (cost per minute of speech).

| Setup | Speech-to-text | Translation | Voice |
|---|---|---|---|
| cascade-openai | $0.0267 | $0.0014 | $0.0208 |
| cascade-haiku | $0.0267 | $0.0012 | $0.0201 |
| cascade-elevenlabs | $0.0262 | $0.0013 | $0.0320 |

- **Speech-to-text is billed per minute of streamed audio.** The whole time the button is held gets streamed: 724 s for 461 s of speech in cascade-openai, about 1.57×.
- **The OpenAI voice's cost is an estimate.** OpenAI doesn't publish its audio-token rate, so we assume 20 tokens per second.
- **Translation is about 3% of the cost,** which is why Haiku costs the same as nano.

## Notes and reconciliation

- **`es-l04`** is the Spanish sentence "Mi hija tose mucho por las noches. Le di jarabe…".
  - `gpt-live-transcribe` garbled it in every cascade run that included it (WER 0.14–0.27). Realtime's side transcriber got it right (WER 0.0).
  - Both cascade "answered" flags (1 of 96 nano, 1 of 48 Haiku) are this sentence. The translator translated or dropped the garbled words; it did not actually reply to the speaker.
  - It is not in the ElevenLabs subset.
- **ElevenLabs credits.**
  - Our budget guard estimated 1,111 characters before the run, against a cap of 1,400.
  - Its own ledger then counted 883, which includes pieces from early translations that were later discarded.
  - ElevenLabs' counter showed 403 right after the run (raw `elevenlabs-credits.txt`) and 445 at a later check (the M5 log). We could not reconcile the two readings, so we quote 403–445 of the 10,000 free monthly credits.
  - The $0.059 per minute shown uses list price on the 883 characters. On ElevenLabs' own count it would be about $0.042–0.044. The free tier bills credits, not dollars.
  - Since then, early translation is off by default when ElevenLabs is the voice (DESIGN A9). That saves credits but gives up finding 3, so expect a slower last-part delay than the 1430 ms measured.
- **ElevenLabs round-trip WER (0.022).** 2 of the 3 sentences with differences are number formatting ("500" vs "quinientos", "850mg" vs "eight hundred fifty milligrams"). The third is one misheard verb.
- **Defaults after the final runs** (DESIGN A10): `gpt-5.4-nano` stays the cascade translator, for speed. Haiku via OpenRouter is the quality option, and fragment merging stays on.
- **Recording** (added by the CTO while this was being written; `config/app.yaml` → `recording`): off by default (`enabled: false`). A session records only if the server allows it and the session asks for it. Audio for each turn (speech in, translation out) is saved on our server, each saved file adds an audit line to the session log, and files older than `retention_days` (default 30) are deleted at startup and on a regular sweep. The benchmark runs above did not use it.
- **Tests.** All automated tests pass. Re-run on 8 Oct 2026: 141 backend and 33 frontend before the recording feature, and 149 backend and 33 frontend with it. Re-run on 9 Oct 2026 after the Review and Experiments tabs (commit fd48fa1): **184 backend (pytest) and 49 frontend (Vitest)**.
- **Model retirement dates.** All are listed as deprecated by OpenAI, and every model ID is a configuration value:

| Model | Retires |
|---|---|
| `gpt-4o-mini-tts` | 6 Jan 2027 |
| `gpt-realtime` and `gpt-realtime-mini` | 20 Jan 2027 (successor `gpt-realtime-2.1`) |
| `gpt-4o-transcribe` | 26 Feb 2027 |
| `gpt-5.4-nano` | 1 Apr 2027 |

## Limitations

- **Small samples:** 48 sentences per setup (96 for cascade-openai), and only 12 for ElevenLabs.
- **Computer-generated test voices,** so speech-recognition error rates are optimistic.
- **One reference translation per sentence,** so valid rewordings lose points. There is no COMET, a learned translation-quality score.
- **One machine, one network and one day.** Vendor speed varies by time and region.
- **Prices are from 8 Oct 2026,** and the voice token rate is assumed.
- **The hands-free figures come from earlier tuning runs** with `gpt-realtime-mini`.
- **Blind human ratings come from one rater** (Andre), 12 sentences per setup (6 per direction), with computer-voiced source audio. They are a sanity check, not a statistically meaningful result.
