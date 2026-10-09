# Blind rating kit (M5)

48 clips: 12 utterances x 4 interpreter profiles, shuffled. Each clip is the
interpreter's spoken output for one source utterance, exactly as the listener heard it
(leading/trailing silence trimmed).

How to rate (per clip, 1 = very poor, 5 = excellent):
- **Adequacy**: does the audio convey the full meaning of the source text (numbers, names, negations)?
- **Fluency**: is it grammatical, natural target-language speech?
- **Naturalness**: does the voice sound natural (prosody, pronunciation, no glitches)?

Use `rating_sheet.csv` (source text and direction are given; the reference translation is
one acceptable rendering, not the only one). Do **not** open `key.csv` until all ratings
are in. Report the number of raters honestly (DESIGN D3); one rater is a smoke test, not a
statistically meaningful result.
