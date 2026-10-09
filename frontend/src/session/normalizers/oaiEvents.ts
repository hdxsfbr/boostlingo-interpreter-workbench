/**
 * Normalises OpenAI Realtime GA server events (WebRTC data channel
 * "oai-events", or the WS relay) into the InterpreterSession contract.
 *
 * Turn mapping: the session tells us which turn it committed
 * (`turnCommitted`); the next `input_audio_buffer.committed` item and the next
 * `response.created` belong to it. Transcription and transcript events are
 * then keyed by item_id / response_id (ordering across turns is not
 * guaranteed, R§1.6). Browser marks are arrival times relative to the turn's
 * t_speech_end (one browser clock).
 */
import type { SessionEvent } from "../protocol";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type OaiEvent = { type: string; [k: string]: any };

export type NormalizerHooks = {
  emit: (ev: SessionEvent) => void;
  now?: () => number;
  speechEnd: (turnId: number) => number | undefined;
  /** Output playback started/stopped on the server-managed buffer (WebRTC). */
  onOutputAudio?: (turnId: number, playing: boolean) => void;
  /** Server VAD (VAD mode only). */
  onSpeechStarted?: () => void;
  onSpeechStopped?: () => void;
};

const IGNORED_ERRORS = new Set(["response_cancel_not_active", "conversation_item_not_found"]);

export class OaiNormalizer {
  private itemTurn = new Map<string, number>();
  private respTurn = new Map<string, number>();
  private commitQueue: number[] = [];
  private responseQueue: number[] = [];
  private src = new Map<number, string>();
  private tgt = new Map<number, string>();
  private marked = new Set<string>();
  private hadAudio = new Set<number>();
  private lastTurn: number | null = null;
  private readonly now: () => number;

  constructor(private readonly h: NormalizerHooks) {
    this.now = h.now ?? (() => performance.now());
  }

  /** Called by the transport when it commits a turn (PTT release or server VAD stop). */
  turnCommitted(turnId: number): void {
    this.commitQueue.push(turnId);
    this.responseQueue.push(turnId);
    this.lastTurn = turnId;
  }

  /** The turn was cancelled locally: forget pending mappings for it. */
  turnCancelled(turnId: number): void {
    this.commitQueue = this.commitQueue.filter((t) => t !== turnId);
    this.responseQueue = this.responseQueue.filter((t) => t !== turnId);
  }

  private mark(turnId: number, mark: string): void {
    const key = `${turnId}:${mark}`;
    if (this.marked.has(key)) return;
    const end = this.h.speechEnd(turnId);
    if (end === undefined) return;
    this.marked.add(key);
    this.h.emit({ type: "latency.mark", turn_id: turnId, mark, ms: this.now() - end, clock: "browser" });
  }

  /** Turn a response belongs to (relay audio routing). */
  turnOf(responseId: string | undefined): number | undefined {
    return this.turnForResponse(responseId);
  }

  private turnForResponse(id: string | undefined): number | undefined {
    return id ? this.respTurn.get(id) : undefined;
  }

  handle(ev: OaiEvent): void {
    const emit = this.h.emit;
    switch (ev.type) {
      case "input_audio_buffer.speech_started":
        this.h.onSpeechStarted?.();
        return;
      case "input_audio_buffer.speech_stopped":
        this.h.onSpeechStopped?.();
        return;
      case "input_audio_buffer.committed": {
        const turn = this.commitQueue.shift() ?? this.lastTurn;
        if (turn != null && ev.item_id) this.itemTurn.set(ev.item_id, turn);
        return;
      }
      case "conversation.item.input_audio_transcription.delta": {
        const turn = this.itemTurn.get(ev.item_id);
        if (turn == null) return;
        const text = (this.src.get(turn) ?? "") + (ev.delta ?? "");
        this.src.set(turn, text);
        this.mark(turn, "input_transcript_first");
        emit({ type: "transcript.partial", turn_id: turn, seg: 0, text: text.trim() });
        return;
      }
      case "conversation.item.input_audio_transcription.completed":
      case "conversation.item.input_audio_transcription.failed": {
        const turn = this.itemTurn.get(ev.item_id);
        if (turn == null) return;
        const text = ev.type.endsWith("completed") ? (ev.transcript ?? "").trim() : "";
        emit({ type: "transcript.final", turn_id: turn, seg: 0, text });
        return;
      }
      case "response.created": {
        const turn = this.responseQueue.shift() ?? this.lastTurn;
        if (turn != null && ev.response?.id) this.respTurn.set(ev.response.id, turn);
        if (turn != null) this.mark(turn, "response_created");
        return;
      }
      case "response.output_audio_transcript.delta": {
        const turn = this.turnForResponse(ev.response_id);
        if (turn == null) return;
        const text = (this.tgt.get(turn) ?? "") + (ev.delta ?? ""); // concatenate as-is (R§5.4)
        this.tgt.set(turn, text);
        this.mark(turn, "output_transcript_first");
        emit({ type: "translation.partial", turn_id: turn, seg: 0, text: text.trim() });
        return;
      }
      case "response.output_audio_transcript.done": {
        const turn = this.turnForResponse(ev.response_id);
        if (turn == null) return;
        const text = (ev.transcript ?? this.tgt.get(turn) ?? "").trim();
        this.tgt.set(turn, text);
        emit({ type: "translation.final", turn_id: turn, seg: 0, text });
        return;
      }
      case "response.output_audio.delta": {
        const turn = this.turnForResponse(ev.response_id);
        if (turn != null) {
          this.hadAudio.add(turn);
          this.mark(turn, "output_audio_first_delta");
        }
        return;
      }
      case "output_audio_buffer.started": {
        const turn = this.turnForResponse(ev.response_id) ?? this.lastTurn;
        if (turn == null) return;
        this.hadAudio.add(turn);
        this.mark(turn, "output_audio_started");
        this.h.onOutputAudio?.(turn, true);
        return;
      }
      case "output_audio_buffer.stopped":
      case "output_audio_buffer.cleared": {
        const turn = this.turnForResponse(ev.response_id) ?? this.lastTurn;
        if (turn == null) return;
        this.h.onOutputAudio?.(turn, false);
        emit({ type: "audio.ended", turn_id: turn, at: this.now() });
        return;
      }
      case "response.done": {
        const r = ev.response ?? {};
        const turn = this.turnForResponse(r.id);
        if (turn == null) return;
        const status = r.status as string;
        if (status === "cancelled") {
          emit({ type: "turn.skipped", turn_id: turn, reason: "cancelled" });
        } else if (status === "failed" || status === "incomplete") {
          const err = r.status_details?.error ?? {};
          emit({ type: "error", code: err.code ?? status, stage: "realtime", retryable: false, turn_id: turn,
                 message: `Realtime response ${status}: ${err.message ?? r.status_details?.reason ?? "unknown"}` });
        } else if (!this.hadAudio.has(turn) && !(this.tgt.get(turn) ?? "").trim()) {
          emit({ type: "turn.skipped", turn_id: turn, reason: "no_output" });
        } else {
          emit({ type: "turn.done", turn_id: turn, usage: { realtime: r.usage ?? {}, response_id: r.id } });
        }
        return;
      }
      case "error": {
        const e = ev.error ?? {};
        if (IGNORED_ERRORS.has(e.code)) return;
        if (e.code === "input_audio_buffer_commit_empty") {
          const turn = this.commitQueue.shift();
          if (turn != null) {
            this.responseQueue = this.responseQueue.filter((t) => t !== turn);
            emit({ type: "turn.skipped", turn_id: turn, reason: "empty_audio" });
          }
          return;
        }
        const rate = /rate_limit/.test(e.code ?? e.type ?? "");
        emit({ type: "error", code: rate ? "rate_limited" : (e.code ?? e.type ?? "realtime_error"), stage: "realtime",
               retryable: rate, message: e.message ?? "Realtime error" });
        return;
      }
      default:
        return;
    }
  }
}

/** Keeps the Realtime conversation short (cost + "answering" drift, R§1.4):
 * after each response, all but the newest `keep` items are deleted. */
export class HistoryPruner {
  private items: string[] = [];
  constructor(private readonly keep = 2) {}

  observe(ev: OaiEvent): string[] {
    if (ev.type === "conversation.item.added" && ev.item?.id && !this.items.includes(ev.item.id)) {
      this.items.push(ev.item.id);
    }
    if (ev.type === "conversation.item.deleted") this.items = this.items.filter((i) => i !== ev.item_id);
    if (ev.type !== "response.done") return [];
    const drop = this.items.slice(0, Math.max(0, this.items.length - this.keep));
    this.items = this.items.slice(drop.length);
    return drop;
  }
}
