/**
 * InterpreterSession event contract (client side).
 *
 * `ServerEvent` mirrors backend/app/core/events.py (validated against the
 * shared fixtures in contract/fixtures/). `SessionEvent` is what the UI
 * consumes: server events from either transport, normalised, plus events the
 * browser itself produces (speech end, first audible sample). The UI depends
 * only on SessionEvent, never on a transport (CQ-1).
 */

export type Lang = string;
export type Mode = "cascade" | "realtime";
export type Pipeline = "loopback" | "cascade";
export type Speaker = "A" | "B";

// ---------- wire: server -> client (cascade WS) ----------
export type ServerEvent =
  | { type: "session.ready"; pipeline: string; providers: Record<string, string> }
  | { type: "turn.started"; turn_id: number; src: Lang; tgt: Lang }
  | { type: "transcript.partial" | "transcript.final"; turn_id: number; seg: number; text: string }
  | { type: "translation.partial" | "translation.final"; turn_id: number; seg: number; text: string }
  | { type: "latency.mark"; turn_id: number; mark: string; ms: number }
  | { type: "turn.done"; turn_id: number; marks: Record<string, number>; usage: Record<string, unknown> }
  | { type: "turn.skipped"; turn_id: number; reason: string }
  | { type: "error"; code: string; stage: string; retryable: boolean; message: string; turn_id?: number | null }
  | { type: "pong"; t?: number | null };

// ---------- wire: client -> server ----------
export type ClientMessage =
  | { type: "session.start"; pipeline: Pipeline; src: Lang; tgt: Lang; turn_mode: "ptt" | "vad"; providers: Record<string, string> }
  | { type: "turn.start"; turn_id: number; src: Lang; tgt: Lang }
  | { type: "commit"; turn_id: number; final: boolean }
  | { type: "turn.cancel"; turn_id: number }
  | { type: "ping"; t?: number | null };

/** Binary downlink frame: 4-byte LE uint32 turn_id + PCM16 LE mono 24 kHz. */
export const AUDIO_HEADER_BYTES = 4;
export const PCM_RATE = 24000;

export function unpackAudio(buf: ArrayBuffer): { turnId: number; pcm: Int16Array } {
  const turnId = new DataView(buf).getUint32(0, true);
  return { turnId, pcm: new Int16Array(buf.slice(AUDIO_HEADER_BYTES)) };
}

// ---------- normalised events consumed by the UI ----------
/** Where a latency mark's clock lives. Browser marks are ms after t_speech_end
 * on performance.now(); server marks are durations on the server clock from
 * the final commit (NFR-5: shown, never subtracted from browser times). */
export type MarkClock = "browser" | "server";

export type SessionState = "idle" | "connecting" | "ready" | "error" | "closed";

export type SessionEvent =
  | { type: "session.state"; state: SessionState; mode: Mode; detail?: string }
  | { type: "session.ready"; mode: Mode; pipeline: string; providers: Record<string, string> }
  | { type: "mode.switched"; from: Mode; to: Mode; at: number }
  | { type: "turn.started"; turn_id: number; src: Lang; tgt: Lang; speaker: Speaker; mode: Mode; at: number }
  | { type: "speech.ended"; turn_id: number; t_speech_end: number }
  | { type: "transcript.partial" | "transcript.final"; turn_id: number; seg: number; text: string }
  | { type: "translation.partial" | "translation.final"; turn_id: number; seg: number; text: string }
  | { type: "latency.mark"; turn_id: number; mark: string; ms: number; clock: MarkClock }
  | { type: "audio.started"; turn_id: number; t_first_audible: number }
  | { type: "audio.ended"; turn_id: number; at: number }
  | { type: "turn.done"; turn_id: number; usage: Record<string, unknown> }
  | { type: "turn.skipped"; turn_id: number; reason: string }
  | { type: "error"; code: string; stage: string; retryable: boolean; message: string; turn_id?: number | null };

export type SessionListener = (ev: SessionEvent) => void;

/** Mode-agnostic session API the UI talks to. */
export interface InterpreterSessionApi {
  start(): Promise<void>;
  stop(): Promise<void>;
  setMode(mode: Mode): Promise<void>;
  pttDown(speaker: Speaker): void;
  pttUp(speaker: Speaker): void;
  on(listener: SessionListener): () => void;
}

/** What a mode-specific transport must implement. */
export interface Transport {
  readonly mode: Mode;
  connect(): Promise<void>;
  turnStart(turnId: number, src: Lang, tgt: Lang): void;
  /** In-turn pause (final=false) or end of turn (final=true). */
  commit(turnId: number, final: boolean): void;
  cancel(turnId: number): void;
  /** Must release sockets / peer connections / audio nodes (FR-4). */
  close(): Promise<void>;
}
