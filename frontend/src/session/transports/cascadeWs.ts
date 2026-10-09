/**
 * Cascade transport: WebSocket to FastAPI (/ws/cascade). PCM16 24 kHz frames
 * up, JSON contract events + turn-tagged PCM down. Server events are already
 * in contract shape, so normalisation is a thin mapping.
 */
import type { ClientMessage, Lang, Pipeline, ServerEvent, SessionEvent, Transport } from "../protocol";
import { unpackAudio } from "../protocol";

export type CascadeOptions = {
  url: string;
  pipeline: Pipeline;
  src: Lang;
  tgt: Lang;
  providers?: Record<string, string>;
  emit: (ev: SessionEvent) => void;
  onAudio: (turnId: number, pcm: Int16Array) => void;
  connectTimeoutMs?: number;
};

export function normalizeServerEvent(ev: ServerEvent): SessionEvent | null {
  switch (ev.type) {
    case "session.ready":
      return { type: "session.ready", mode: "cascade", pipeline: ev.pipeline, providers: ev.providers };
    case "latency.mark":
      return { ...ev, clock: "server" };
    case "turn.done":
      return { type: "turn.done", turn_id: ev.turn_id, usage: { ...ev.usage, server_marks: ev.marks } };
    case "turn.started": // the browser already emitted turn.started at PTT press
    case "pong":
      return null;
    default:
      return ev;
  }
}

export class CascadeTransport implements Transport {
  readonly mode = "cascade" as const;
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private closing = false;

  constructor(private readonly opts: CascadeOptions) {}

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  connect(): Promise<void> {
    const { opts } = this;
    this.closing = false;
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(opts.url);
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      const timer = setTimeout(() => {
        reject(new Error("cascade connect timeout"));
        ws.close();
      }, opts.connectTimeoutMs ?? 5000);
      let ready = false;
      ws.onopen = () =>
        this.send({ type: "session.start", pipeline: opts.pipeline, src: opts.src, tgt: opts.tgt, turn_mode: "ptt", providers: opts.providers ?? {} });
      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          const { turnId, pcm } = unpackAudio(e.data);
          opts.onAudio(turnId, pcm);
          return;
        }
        const ev = JSON.parse(e.data as string) as ServerEvent;
        if (!ready && ev.type === "session.ready") {
          ready = true;
          clearTimeout(timer);
          resolve();
        }
        if (!ready && ev.type === "error") {
          clearTimeout(timer);
          reject(Object.assign(new Error(ev.message), { reported: true })); // already shown via emit
        }
        const norm = normalizeServerEvent(ev);
        if (norm) opts.emit(norm);
      };
      ws.onclose = () => {
        clearInterval(this.pingTimer);
        clearTimeout(timer);
        if (!ready) reject(new Error("cascade socket closed during connect"));
        else if (!this.closing)
          opts.emit({ type: "error", code: "provider_disconnected", stage: "transport", retryable: true, message: "Cascade connection dropped; it will reconnect on the next turn." });
      };
      this.pingTimer = setInterval(() => this.send({ type: "ping", t: performance.now() }), 10000);
    });
  }

  private send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  sendAudio(pcm: Int16Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }

  turnStart(turnId: number, src: Lang, tgt: Lang): void {
    this.send({ type: "turn.start", turn_id: turnId, src, tgt });
  }
  commit(turnId: number, final: boolean): void {
    this.send({ type: "commit", turn_id: turnId, final });
  }
  /** M4: short in-turn silence; lets the server start speculative MT early. */
  pauseHint(turnId: number): void {
    this.send({ type: "pause.hint", turn_id: turnId });
  }
  cancel(turnId: number): void {
    this.send({ type: "turn.cancel", turn_id: turnId });
  }

  async close(): Promise<void> {
    this.closing = true;
    clearInterval(this.pingTimer);
    const ws = this.ws;
    this.ws = null;
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close(1000, "client close");
  }
}
