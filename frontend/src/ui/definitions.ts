/** A18: one plain-language definition per latency term, worded like
 * docs/user-guide/05-understanding-the-numbers.md and 02-interpreter.md ("What each row means").
 * Keys are the server/browser mark names; DEF_BY_LABEL maps the on-screen labels. */
export const DEFINITIONS: Record<string, string> = {
  commit_sent: "When the app told the interpreter \"the speaker has finished\". With push-to-talk, about when you let go of the button.",
  stt_final: "When speech-to-text delivered its finished transcript.",
  mt_first_token: "When the translation model produced its first piece of text (a token: a small chunk of text, often part of a word).",
  mt_first_chunk: "When the first piece of translation big enough to speak (a phrase or sentence) was ready.",
  tts_request: "When that first chunk was sent to text-to-speech.",
  tts_first_byte: "When the first bit of synthesised audio came back from text-to-speech.",
  audio_sent: "When the server started sending that audio to your browser.",
  audio_first_sent: "When the server started sending that audio to your browser.",
  tail_tts_first_byte: "For multi-sentence turns: when audio for the last sentence began arriving.",
  first_audible: "When you could first hear the translation, measured in your browser. On a turn split into several sentences this is the first sentence (translated while you were still talking and held until you let go), so it is not the headline there.",
  last_sentence_audible: "The headline on a split turn: when audio for the last sentence started (speech end to first audio of the last sentence). Server estimate: commit sent + when that sentence's audio began arriving, without ~50 ms of network and playback.",
  headline: "The delay from speech end to the first audio of the last sentence (H). Single-sentence turns: measured in your browser at first audible. Split turns: the last sentence's audio start (estimate).",
  first_audible_stat: "Literal first audible: speech end to the first sound of the turn. On split turns that is the held first sentence (about 0.5 s, mostly the push-to-talk release), so it flatters the cascade; shown for reference.",
  spec_start: "When the app started translating early (speculatively) from an unfinished transcript, while the speaker was still talking.",
  spec_hit: "When an early (speculative) translation turned out to match the final transcript and was used, so no time was lost redoing it.",
  mt_hedge_fired: "The first translation request was slow, so a backup request was sent; whichever answers first is used.",
  tts_hedge_fired: "The first text-to-speech request was slow, so a backup request was sent; whichever answers first is used.",
  n: "Number of turns behind the numbers in this row (the last 50 timed turns of this mode).",
  p50: "Typical delay (the median): half the turns were faster than this.",
  p90: "Slower case: 9 in 10 turns were faster than this.",
  early: "Turns where this step happened before speech end: an earlier sentence of a long turn, or a speculative translation, was processed while the speaker was still talking. Counted here, not in p50/p90.",
  estimate: "Server estimate: timed on the server's clock from when it received \"finished\", then placed after the commit sent mark.",
};

const LABEL_TO_KEY: Record<string, string> = {
  "commit sent": "commit_sent", "STT final": "stt_final", "MT 1st token": "mt_first_token", "MT 1st chunk": "mt_first_chunk",
  "TTS request": "tts_request", "TTS 1st byte": "tts_first_byte", "audio sent": "audio_sent", "last seg TTS 1st": "tail_tts_first_byte",
  "first audible": "first_audible", "last sentence audible": "last_sentence_audible",
};

export const definitionFor = (keyOrLabel: string): string | undefined =>
  DEFINITIONS[keyOrLabel] ?? DEFINITIONS[LABEL_TO_KEY[keyOrLabel] ?? ""];
