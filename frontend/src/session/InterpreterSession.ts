/**
 * InterpreterSession: the single mode-agnostic API the UI uses (CQ-1).
 * Owns the AudioEngine, the turn controller and one Transport at a time.
 * Mode switches close the old transport (sockets, peer, nodes) and keep the
 * UI history; the store inserts the switch marker (FR-4).
 */
import { AudioEngine, MicError, requestMic } from "../audio/engine";
import type { InterpreterSessionApi, Lang, Mode, Pipeline, SessionEvent, SessionListener, Speaker, Transport } from "./protocol";
import { TurnController } from "./turnController";
import { CascadeTransport } from "./transports/cascadeWs";

export const GATE_TAIL_MS = 300;

/** Read-only probe for the browser test harness (backend/eval). */
export function harnessHook(): { lastVoiced?: number; state?: unknown } {
  const w = globalThis as unknown as { __wb?: { lastVoiced?: number; state?: unknown } };
  return (w.__wb ??= {});
}

export type SessionConfig = {
  pair: { a: Lang; b: Lang };
  mode: Mode;
  pipeline: Pipeline;
  wsUrl?: string;
  pauseCommitMs?: number | null;
};

type CascadeLike = Transport & { sendAudio?(pcm: Int16Array): void; isOpen?: boolean };

export class InterpreterSession implements InterpreterSessionApi {
  private listeners = new Set<SessionListener>();
  private engine: AudioEngine | null = null;
  private transport: CascadeLike | null = null;
  private turns: TurnController;
  private speechEnd = new Map<number, number>();
  private playingTurn: number | null = null;
  private gateUntil = 0;
  private lastCommittedTurn: number | null = null;
  mode: Mode;
  pipeline: Pipeline;

  constructor(private cfg: SessionConfig) {
    this.mode = cfg.mode;
    this.pipeline = cfg.pipeline;
    this.turns = new TurnController(cfg.pair, cfg.pauseCommitMs ?? 300);
  }

  on(listener: SessionListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit = (ev: SessionEvent): void => {
    for (const l of this.listeners) l(ev);
  };

  get started(): boolean {
    return this.engine !== null;
  }

  /** Call from the Start click: creates/resumes the AudioContext (autoplay). */
  async start(): Promise<void> {
    if (this.engine) return;
    const ctx = new AudioContext({ latencyHint: "interactive" });
    void ctx.resume();
    this.emit({ type: "session.state", state: "connecting", mode: this.mode });
    let mic: MediaStream;
    try {
      mic = await requestMic();
    } catch (e) {
      await ctx.close();
      const err = e instanceof MicError ? e : new MicError("mic_failed", String(e));
      this.emit({ type: "error", code: err.code, stage: "mic", retryable: true, message: err.message });
      this.emit({ type: "session.state", state: "error", mode: this.mode, detail: err.code });
      return;
    }
    const engine = await AudioEngine.create(ctx, mic);
    engine.onFrame = (f) => this.onFrame(f.pcm, f.voiced, f.tPerf);
    engine.onAudible = (turnId, t) => this.onAudible(turnId, t);
    engine.onPlaybackStarted = (turnId) => {
      this.playingTurn = turnId;
    };
    engine.onPlaybackDrained = (turnId) => {
      if (this.playingTurn === turnId) this.playingTurn = null;
      this.gateUntil = performance.now() + GATE_TAIL_MS;
      this.emit({ type: "audio.ended", turn_id: turnId, at: performance.now() });
    };
    this.engine = engine;
    await this.connectTransport();
  }

  private makeTransport(): CascadeLike {
    if (this.mode === "realtime") throw new Error("Realtime mode is not wired yet (milestone M2).");
    const url = this.cfg.wsUrl ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/cascade`;
    return new CascadeTransport({
      url,
      pipeline: this.pipeline,
      src: this.cfg.pair.a,
      tgt: this.cfg.pair.b,
      emit: this.emit,
      onAudio: (turnId, pcm) => this.engine?.play(turnId, pcm),
    });
  }

  private async connectTransport(): Promise<void> {
    this.emit({ type: "session.state", state: "connecting", mode: this.mode });
    try {
      const t = this.makeTransport();
      await t.connect();
      this.transport = t;
      this.emit({ type: "session.state", state: "ready", mode: this.mode });
    } catch (e) {
      this.transport = null;
      this.emit({ type: "error", code: "connect_failed", stage: "transport", retryable: true, message: (e as Error).message });
      this.emit({ type: "session.state", state: "error", mode: this.mode, detail: "connect_failed" });
    }
  }

  async setMode(mode: Mode): Promise<void> {
    if (mode === this.mode) return;
    const from = this.mode;
    await this.teardownTransport();
    this.mode = mode;
    this.emit({ type: "mode.switched", from, to: mode, at: performance.now() });
    if (this.engine) await this.connectTransport();
  }

  async setPipeline(p: Pipeline): Promise<void> {
    if (p === this.pipeline) return;
    this.pipeline = p;
    if (this.engine) {
      await this.teardownTransport();
      await this.connectTransport();
    }
  }

  private async teardownTransport(): Promise<void> {
    this.engine?.flush();
    this.engine?.disarmTap();
    this.engine?.detachRemote();
    const t = this.transport;
    this.transport = null;
    if (t) await t.close();
  }

  pttDown(speaker: Speaker): void {
    if (!this.engine || this.turns.active) return;
    // Barge-in (FR-1.3): a press during playback flushes it and cancels that turn.
    if (this.playingTurn !== null || this.lastCommittedTurn !== null) {
      this.engine.flush();
      this.engine.disarmTap();
      if (this.lastCommittedTurn !== null) this.transport?.cancel(this.lastCommittedTurn);
      this.playingTurn = null;
    }
    this.gateUntil = 0;
    const now = performance.now();
    const turn = this.turns.pttDown(speaker, now);
    if (this.transport && this.transport.isOpen === false) void this.connectTransport();
    this.transport?.turnStart(turn.id, turn.src, turn.tgt);
    this.emit({ type: "turn.started", turn_id: turn.id, src: turn.src, tgt: turn.tgt, speaker, mode: this.mode, at: now });
  }

  pttUp(_speaker: Speaker): void {
    const end = this.turns.pttUp(performance.now());
    if (!end) return;
    const id = end.turn.id;
    this.speechEnd.set(id, end.tSpeechEnd);
    this.emit({ type: "speech.ended", turn_id: id, t_speech_end: end.tSpeechEnd });
    this.engine?.armTap(id);
    this.transport?.commit(id, true);
    this.lastCommittedTurn = id;
    this.emit({ type: "latency.mark", turn_id: id, mark: "commit_sent", ms: performance.now() - end.tSpeechEnd, clock: "browser" });
  }

  private onFrame(pcm: Int16Array, voiced: boolean, tPerf: number): void {
    if (voiced) harnessHook().lastVoiced = tPerf;
    const gated = this.playingTurn !== null || performance.now() < this.gateUntil;
    const act = this.turns.frame(voiced && !gated, tPerf);
    if (!act.send || !this.transport) return;
    this.transport.sendAudio?.(gated ? new Int16Array(pcm.length) : pcm);
    if (act.pauseCommit && this.turns.active) this.transport.commit(this.turns.active.id, false);
  }

  private onAudible(turnId: number, tPerf: number): void {
    const tEnd = this.speechEnd.get(turnId);
    if (tEnd === undefined) return;
    if (this.lastCommittedTurn === turnId) this.lastCommittedTurn = null;
    this.emit({ type: "audio.started", turn_id: turnId, t_first_audible: tPerf });
    this.emit({ type: "latency.mark", turn_id: turnId, mark: "first_audible", ms: tPerf - tEnd, clock: "browser" });
  }

  async stop(): Promise<void> {
    await this.teardownTransport();
    await this.engine?.close();
    this.engine = null;
    this.turns.active = null;
    this.emit({ type: "session.state", state: "closed", mode: this.mode });
  }
}
