/**
 * Realtime via the FastAPI WebSocket relay (/ws/realtime): the fallback when
 * WebRTC is unavailable (D1 / R4). Same OaiNormalizer and pruning as WebRTC;
 * audio is PCM16 both ways and plays through the cascade playback worklet and
 * output tap, so t_first_audible is measured the same way.
 */
import type { Lang, SessionEvent, Transport } from "../protocol";
import { unpackAudio } from "../protocol";
import { HistoryPruner, OaiNormalizer, type OaiEvent } from "../normalizers/oaiEvents";
import { turnInstructions } from "../realtimePrompt";
import type { TurnMode } from "./realtimeWebrtc";

export type RelayOptions = {
  url: string;
  pair: { a: Lang; b: Lang };
  turnMode?: TurnMode;
  silenceDurationMs?: number;
  /** PTT: send per-turn direction instructions with response.create (default on). */
  directionHint?: boolean;
  emit: (ev: SessionEvent) => void;
  speechEnd: (turnId: number) => number | undefined;
  onAudio: (turnId: number, pcm: Int16Array) => void;
  onSpeechStarted?: () => void;
  onSpeechStopped?: () => void;
  connectTimeoutMs?: number;
};

export class RealtimeRelayTransport implements Transport {
  readonly mode = "realtime" as const;
  readonly kind = "relay" as const;
  private ws: WebSocket | null = null;
  private normalizer: OaiNormalizer;
  private direction: { src: Lang; tgt: Lang } | null = null;
  private pruner = new HistoryPruner(2);
  private responseIds: string[] = [];
  private cancelled = new Set<number>();
  private closing = false;
  model = "";
  readonly recorded: OaiEvent[] = [];

  constructor(private readonly opts: RelayOptions) {
    this.normalizer = new OaiNormalizer({
      emit: opts.emit,
      speechEnd: opts.speechEnd,
      onSpeechStarted: opts.onSpeechStarted,
      onSpeechStopped: opts.onSpeechStopped,
    });
  }

  get turnMode(): TurnMode {
    return this.opts.turnMode ?? "ptt";
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    const o = this.opts;
    this.closing = false;
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(o.url);
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      let ready = false;
      const timer = setTimeout(() => {
        reject(new Error("realtime relay connect timeout"));
        ws.close();
      }, o.connectTimeoutMs ?? 8000);
      ws.onopen = () =>
        ws.send(JSON.stringify({ type: "relay.start", a: o.pair.a, b: o.pair.b, turn_mode: this.turnMode, silence_duration_ms: o.silenceDurationMs ?? 400 }));
      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          const { turnId: respIdx, pcm } = unpackAudio(e.data);
          const turn = this.normalizer.turnOf(this.responseIds[respIdx - 1]);
          if (turn != null && !this.cancelled.has(turn)) o.onAudio(turn, pcm); // drop audio still in flight after a barge-in
          return;
        }
        const ev = JSON.parse(e.data as string) as OaiEvent;
        if (ev.type === "relay.ready") {
          ready = true;
          this.model = ev.model;
          clearTimeout(timer);
          o.emit({ type: "session.ready", mode: "realtime", pipeline: "relay", providers: { realtime: ev.model, transport: "ws-relay" } });
          resolve();
          return;
        }
        if (ev.type === "error" && typeof ev.code === "string") {
          // relay-level contract error (not an OpenAI event)
          if (!ready) {
            clearTimeout(timer);
            reject(new Error(ev.message));
          }
          o.emit({ type: "error", code: ev.code, stage: ev.stage ?? "realtime", retryable: !!ev.retryable, message: ev.message });
          return;
        }
        if (ev.type === "response.created" && ev.response?.id) this.responseIds.push(ev.response.id);
        if (this.recorded.length < 2000) this.recorded.push(ev);
        this.normalizer.handle(ev);
        for (const id of this.pruner.observe(ev)) this.oai({ type: "conversation.item.delete", item_id: id });
      };
      ws.onclose = () => {
        clearTimeout(timer);
        if (!ready) reject(new Error("realtime relay closed during connect"));
        else if (!this.closing)
          o.emit({ type: "error", code: "provider_disconnected", stage: "transport", retryable: true, message: "Realtime relay dropped; it will reconnect on the next turn." });
      };
    });
  }

  private oai(event: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "oai", event }));
  }

  sendAudio(pcm: Int16Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }

  turnStart(_turnId: number, src: Lang, tgt: Lang): void {
    this.direction = { src, tgt };
    if (this.turnMode === "ptt") this.oai({ type: "input_audio_buffer.clear" });
  }

  vadTurn(turnId: number): void {
    this.normalizer.turnCommitted(turnId);
  }

  commit(turnId: number, final: boolean): void {
    if (!final || this.turnMode !== "ptt") return;
    this.normalizer.turnCommitted(turnId);
    this.oai({ type: "input_audio_buffer.commit" });
    this.oai(this.responseCreate());
  }

  private responseCreate(): Record<string, unknown> {
    const d = this.direction;
    if (!d || this.opts.directionHint === false) return { type: "response.create" };
    return { type: "response.create", response: { instructions: turnInstructions(d.src, d.tgt) } };
  }

  cancel(turnId: number): void {
    this.cancelled.add(turnId);
    this.normalizer.turnCancelled(turnId);
    this.oai({ type: "response.cancel" });
  }

  async close(): Promise<void> {
    this.closing = true;
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close(1000, "client close");
  }

  get liveResources(): { ws: boolean } {
    return { ws: this.ws !== null };
  }
}
