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
  first_audible: "The headline number: when you could first hear the translation, measured in your browser.",
  headline: "The delay from speech end to the first audible translation (H), measured in your browser.",
  spec_start: "When the app started translating early (speculatively) from an unfinished transcript, while the speaker was still talking.",
  spec_hit: "When an early (speculative) translation turned out to match the final transcript and was used, so no time was lost redoing it.",
  n: "Number of turns behind the numbers in this row (the last 50 timed turns of this mode).",
  p50: "Typical delay (the median): half the turns were faster than this.",
  p90: "Slower case: 9 in 10 turns were faster than this.",
  early: "Turns where this step happened before speech end (work started while the speaker was still talking). They are counted here, not in p50/p90.",
  estimate: "Server estimate: timed on the server's clock from when it received \"finished\", then placed after the commit sent mark.",
};

const LABEL_TO_KEY: Record<string, string> = {
  "commit sent": "commit_sent", "STT final": "stt_final", "MT 1st token": "mt_first_token", "MT 1st chunk": "mt_first_chunk",
  "TTS request": "tts_request", "TTS 1st byte": "tts_first_byte", "audio sent": "audio_sent", "last seg TTS 1st": "tail_tts_first_byte",
  "first audible": "first_audible",
};

export const definitionFor = (keyOrLabel: string): string | undefined =>
  DEFINITIONS[keyOrLabel] ?? DEFINITIONS[LABEL_TO_KEY[keyOrLabel] ?? ""];
