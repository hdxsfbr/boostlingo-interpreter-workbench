# Demo video script: Interpreter Workbench

Target **3:00**, hard max **4:00**. Built for the Boostlingo AI Interpreter assignment; not a Boostlingo product.
Narration: first person (Andre), about **455 words ≈ 3:00 at 150 wpm**. Live audio playback adds roughly 15–25 s, so expect 3:15–3:30 total.
All numbers come from [comparison.md](comparison.md) and [KEY_METRICS.md](KEY_METRICS.md) (M5 runs, 8 Oct 2026).

## Before you hit record

- **Headphones on** (guide 01). Record system audio too, so viewers hear the translations.
- **Logged in** on the Railway app in a fresh window; close other tabs and notifications.
- **Browser zoom 110–125%** at 1280 px wide, so the latency bars and labels are readable.
- **Warm-up turn** in each mode before recording (one short sentence), so the first on-camera turn isn't a cold start.
- Pair set to **English ↔ Spanish**, Pipeline **STT → MT → TTS**, Turn taking **Push-to-talk**, Record **off**.
- Hold **F** (Speaker A, EN→ES) or **J** (Speaker B, ES→EN). Let go about half a second after your last word.
- Have Review (a revealed result), Experiments (History with the M5 baseline) and Docs loaded in mind so glimpses are one click each.
- If a live turn misbehaves, keep going: say "live demo" and do the next line. Re-record only if a mode fails entirely.

## Lines to speak

| Turn | Key | Line |
|---|---|---|
| Realtime A | F | "I've had chest pain since this morning, and I'm allergic to penicillin." |
| Realtime B | J | "¿El dolor se extiende al brazo izquierdo?" |
| Cascade A | F | "I've had chest pain since this morning, and I'm allergic to penicillin." |
| Cascade B | J | "Le vamos a hacer un electrocardiograma ahora mismo." |

## Scenes

### 1. The problem — 0:00–0:20
**Screen:** Interpreter tab, idle, header with logo visible.
**Narration:** "Hi, I'm Andre. In a hospital or a courtroom, a language barrier isn't an inconvenience; it can mean a missed diagnosis. This is the Interpreter Workbench, which I built for the Boostlingo assignment. It answers one question: should a live AI interpreter use one voice-to-voice model, or a chain of three services?"

### 2. Realtime live — 0:20–0:55
**Screen/click:** Mode toggle → **Realtime**. Start session. Hold F for line A, then J for line B. Point the cursor at the latency card.
**Narration (before turns):** "First, Realtime: one OpenAI model hears me and speaks the translation."
*(speak Realtime A and B; let playback finish)*
**Narration (after):** "That latency bar is the delay from when I stop talking to when the listener first hears Spanish. Across our tests, Realtime was about one second typical, 1.4 in slower cases, under the 1.5 second target."

### 3. Cascade live — 0:55–1:35
**Screen/click:** Stop session → toggle **Cascade** → Start. Hold F for line A, J for line B. Hover a latency row to show a tooltip; point at an "early" label if one appears.
**Narration (before):** "Now the cascade: speech-to-text, then a translation model, then text-to-speech."
*(speak Cascade A and B)*
**Narration (after):** "Every step gets its own bar, and hovering explains it. On long turns it starts translating the first sentence while I'm still talking, so those steps show as early. On short sentences it's 1.8 seconds with the OpenAI translator and 2.3 with Claude Haiku: under three seconds, but slower."

### 4. Quality and cost — 1:35–2:05
**Screen/click:** Review tab → revealed results table.
**Narration:** "Quality: Haiku had the best automatic translation scores. But in my blind ratings, where I didn't know which setup I was hearing, Realtime scored five out of five for accuracy and fluency, and the cascade's OpenAI voice sounded least natural. One rater is a sanity check, not proof. Cost: Realtime is about eighteen cents a minute, roughly 3.7 times the cascade's five cents. The smaller realtime-mini matches that five cents."

### 5. Recommendation and trade-offs — 2:05–2:35
**Screen:** docs/comparison.md recommendation table (Docs tab or repo), or stay on Review.
**Narration:** "My recommendation: Realtime for live medical and legal calls; it's fastest, steadiest, and after I told it every turn to translate only, it never answered instead of translating. Choose the cascade when terminology, an audit trail or keeping data in-house matter more than a second, because audio and text pass through our server and we see every step. That cuts both ways for compliance: recordings of medical calls are protected health information. So recording is opt-in, off by default, and deleted after thirty days, and it added no measurable delay."

### 6. Experiments and Docs — 2:35–2:55
**Screen/click:** Experiments tab → show cost estimate, then History/compare with the M5 baseline. Then Docs tab → open a guide page.
**Narration:** "The Experiments tab reruns the same benchmark from the browser, with a cost estimate before you run and side-by-side comparisons against my baseline. And the Docs tab has a plain-language guide to every screen and number."

### 7. Close — 2:55–3:05
**Screen:** Back to Interpreter tab.
**Narration:** "So: Realtime when speed matters most, the cascade when control matters most. It's live on Railway, and the code and full write-up are in the repo. Thanks for watching."

## Word count

| Scene | Words |
|---|---|
| 1 | 62 |
| 2 | 60 |
| 3 | 72 |
| 4 | 75 |
| 5 | 94 |
| 6 | 44 |
| 7 | 33 |
| **Total** | **~440 words ≈ 2:56 narration**, plus ~15–25 s of live audio |
