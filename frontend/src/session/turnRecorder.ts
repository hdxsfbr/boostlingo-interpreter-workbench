/**
 * Realtime-mode session recording (A11). WebRTC audio goes browser <-> OpenAI
 * directly, so the server never sees it: the browser records each turn with
 * MediaRecorder and uploads it to POST /api/recordings/<sid>/turns/<n>/<side>.
 *
 * source = the raw mic track, from turn.started until speech.ended (+ tail)
 * target = what the listener hears (output tap), from turn.started until
 *          audio.ended (+ tail), cut short by barge-in, skip or a turn error.
 * Paths are deterministic, so the turn record can reference them up front.
 */
import type { SessionEvent } from "./protocol";

export type Side = "source" | "target";
export type UploadFn = (turn: number, side: Side, blob: Blob, mime: string) => Promise<void>;

export const SOURCE_TAIL_MS = 200;
export const TARGET_TAIL_MS = 500;
export const MAX_TURN_MS = 120_000;

const MIMES: [string, string][] = [
  ["audio/webm;codecs=opus", "webm"],
  ["audio/ogg;codecs=opus", "ogg"],
];

export function pickMime(): { mime: string; ext: string } | null {
  const MR = (globalThis as { MediaRecorder?: { isTypeSupported?(m: string): boolean } }).MediaRecorder;
  if (!MR?.isTypeSupported) return null;
  for (const [mime, ext] of MIMES) if (MR.isTypeSupported(mime)) return { mime, ext };
  return null;
}

export function recordingPaths(sessionId: string, turn: number, ext: string): Record<Side, string> {
  return {
    source: `recordings/${sessionId}/turn-${turn}-source.${ext}`,
    target: `recordings/${sessionId}/turn-${turn}-target.${ext}`,
  };
}

export function uploadUrl(sessionId: string, turn: number, side: Side): string {
  return `/api/recordings/${encodeURIComponent(sessionId)}/turns/${turn}/${side}`;
}

export function httpUpload(sessionId: string, onError: (msg: string) => void): UploadFn {
  return async (turn, side, blob, mime) => {
    try {
      const r = await fetch(uploadUrl(sessionId, turn, side), { method: "POST", headers: { "Content-Type": mime.split(";")[0] }, body: blob });
      if (!r.ok) onError(`turn ${turn} ${side}: HTTP ${r.status} ${(await r.text()).slice(0, 200)}`);
    } catch (e) {
      onError(`turn ${turn} ${side}: ${(e as Error).message}`);
    }
  };
}

type Rec = { rec: MediaRecorder; chunks: Blob[]; timer?: ReturnType<typeof setTimeout>; cap: ReturnType<typeof setTimeout> };

export class BrowserTurnRecorder {
  private live = new Map<string, Rec>();
  /** Fired with the expected paths when a turn starts recording. */
  onPaths: (turn: number, paths: Record<Side, string>) => void = () => {};
  uploads: Promise<void>[] = [];
  private stopped: Promise<void>[] = [];

  constructor(
    private readonly streams: Record<Side, MediaStream>,
    private readonly sessionId: string,
    private readonly upload: UploadFn,
    private readonly format: { mime: string; ext: string },
  ) {}

  onEvent(ev: SessionEvent): void {
    switch (ev.type) {
      case "turn.started":
        // Barge-in / overlap: an older turn's output ends when a new turn starts.
        for (const key of [...this.live.keys()]) if (key.endsWith(":target")) this.stop(Number(key.split(":")[0]), "target");
        this.start(ev.turn_id, "source");
        this.start(ev.turn_id, "target");
        this.onPaths(ev.turn_id, recordingPaths(this.sessionId, ev.turn_id, this.format.ext));
        break;
      case "speech.ended":
        this.stop(ev.turn_id, "source", SOURCE_TAIL_MS);
        break;
      case "audio.ended":
        this.stop(ev.turn_id, "target", TARGET_TAIL_MS);
        break;
      case "turn.skipped":
        this.stop(ev.turn_id, "source");
        this.stop(ev.turn_id, "target");
        break;
      case "error":
        if (ev.turn_id != null && !ev.retryable) {
          this.stop(ev.turn_id, "source");
          this.stop(ev.turn_id, "target");
        }
        break;
      default:
    }
  }

  get active(): number {
    return this.live.size;
  }

  private start(turn: number, side: Side): void {
    const key = `${turn}:${side}`;
    if (this.live.has(key)) return;
    const rec = new MediaRecorder(this.streams[side], { mimeType: this.format.mime });
    const r: Rec = { rec, chunks: [], cap: setTimeout(() => this.stop(turn, side), MAX_TURN_MS) };
    rec.ondataavailable = (e) => {
      if (e.data.size) r.chunks.push(e.data);
    };
    this.stopped.push(
      new Promise<void>((res) => {
        rec.onstop = () => {
          const blob = new Blob(r.chunks, { type: this.format.mime });
          if (blob.size) this.uploads.push(this.upload(turn, side, blob, this.format.mime));
          res();
        };
      }),
    );
    rec.start();
    this.live.set(key, r);
  }

  private stop(turn: number, side: Side, delayMs = 0): void {
    const key = `${turn}:${side}`;
    const r = this.live.get(key);
    if (!r || r.timer) return;
    const fin = () => {
      clearTimeout(r.cap);
      this.live.delete(key);
      if (r.rec.state !== "inactive") r.rec.stop();
    };
    if (delayMs > 0) r.timer = setTimeout(fin, delayMs);
    else fin();
  }

  /** Session end / mode switch: flush everything still recording and wait for uploads. */
  async close(): Promise<void> {
    for (const key of [...this.live.keys()]) {
      const [t, side] = key.split(":");
      const r = this.live.get(key)!;
      clearTimeout(r.timer);
      r.timer = undefined;
      this.stop(Number(t), side as Side);
    }
    await Promise.race([Promise.allSettled(this.stopped), new Promise((res) => setTimeout(res, 2000))]);
    await Promise.allSettled(this.uploads);
  }
}
