# 5. Understanding the numbers

## Latency (delay)

**Latency** is the delay from the moment the speaker stops talking to the moment the listener first hears the translation. In the app it is often labelled **H** or "speech end → first audio".

### How it is measured

- Everything is measured **in your browser, on one clock**, the same way in both modes, so Realtime and Cascade can be compared fairly.
- **Start:** the last moment the microphone picked up voice.
- **End:** the first audible sound of the translation's **last sentence**, detected by a small audio monitor in the page's playback path (not when the data arrived, but when it actually started to sound). On a Cascade turn split into several sentences, the first sentence was translated while you were still talking and is heard almost as soon as you let go; that literal **first audible** (about 0.5 s, mostly the button release) is shown as a secondary number, and the headline uses the server's estimate of when the last sentence's audio started (marked \*).
- With **push-to-talk**, the delay includes the short pause between your last word and letting go of the button. In benchmarks and experiments, the test robot always lets go **0.45 s** (450 ms) after the last word, like a person would. **H−gap** is the same delay with that 0.45 s subtracted.
- Server step times (rows marked \* in the Interpreter) are estimates from the server's own clock; see [Reading the latency bars](02-interpreter.md#reading-the-latency-bars).

### Targets

| Mode | Target | Limit |
|---|---|---|
| Realtime | under 1.5 s | 1.5 s |
| Cascade | under 2 s (ideal) | 3 s |

### Short vs long turns

On a long turn, the Cascade translates and voices the first sentence while the person is still talking, and plays it as soon as they stop, so its delay can look very small. Compare **short, single sentences** for a fair picture.

### Early (speculative) steps

All step times are counted from **speech end**, the same reference as the headline. A step that happened *before* speech end (an earlier sentence of a long turn, or a speculative translation started from the unfinished transcript) is shown as **early** with how long before, for example "3.6 s before speech end", never as a negative number. In the per-step p50/p90 table, early turns are left out of p50/p90 and counted in a separate **early** column. The headline itself can't be early: the translation is only played after the speaker has finished.

## Typical and slower case: p50 and p90

A single turn can be fast or slow by chance, so we summarise many turns:

- **p50 (typical):** the median. Half of the turns were faster than this.
- **p90 (slower case):** 9 in 10 turns were faster than this. It shows how bad the slower turns get.

## WER (word error rate)

**WER** is the share of words the speech-to-text step got wrong compared with what was actually said. 0.01 means 1 word in 100. **Lower is better.**

- In the Workbench it is calculated against the known script of each test sentence, so it is only available for benchmark runs and experiments, not for free conversation.
- For Realtime, it scores the separate transcription model that writes the on-screen transcript, not what the interpreting model itself heard.

## chrF (translation score)

**chrF** (character F-score) is a 0–100 score of how closely a translation matches a reference translation, comparing short runs of characters. **Higher is better.**

- Each test sentence has only one reference, so a valid rewording also loses points. Use chrF to compare setups with each other, not as an absolute grade.
- Automatic scores and human ratings can disagree. In the benchmark, the Haiku translator scored highest on chrF but was rated last by the human rater, mostly because of its voice.

## Cost per minute

**Cost per minute** is what the AI vendors charge per minute of **speech** (the voiced part only, not silence).

- Each service reports its usage per turn: seconds of audio, **tokens** (the small chunks of text or audio that AI services bill by) or characters.
- That usage is multiplied by dated list prices (shown as "prices as of …" in the Experiments tab) and divided by the minutes of speech.
- In the final benchmark (8 Oct 2026) Realtime with `gpt-realtime` cost about $0.18 per minute, `gpt-realtime-mini` about $0.05, and the Cascade setups about $0.05–0.06.
- Hosting the Workbench itself is not included.

## Benchmark terms you will see

- **M5:** the final benchmark run of 8 Oct 2026. Its numbers appear as the "M5 baseline" in Experiments and next to the ratings in Review.
- **Setup / variant:** one interpreter configuration, for example `cascade-openai`.
- **Failures:** turns that did not complete, for example because a provider timed out.
