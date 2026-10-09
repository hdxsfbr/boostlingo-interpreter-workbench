/**
 * InterpreterSession: the single mode-agnostic API the UI uses (CQ-1).
 * Owns the AudioEngine, the turn controller and one Transport at a time.
 * Mode switches close the old transport (sockets, peer, nodes) and keep the
 * UI history; the store inserts the switch marker (FR-4).
 */
import { AudioEngine, MicError, requestMic } from "../audio/engine";
import { FileSource } from "../audio/fileSource";
import type { InterpreterSessionApi, Lang, Mode, Pipeline, SessionEvent, SessionListener, Speaker, Transport } from "./protocol";
import { TurnController, VadSegmenter } from "./turnController";
import { CascadeTransport } from "./transports/cascadeWs";
import { RealtimeRelayTransport } from "./transports/realtimeRelay";
import { RealtimeTransport, type TurnMode } from "./transports/realtimeWebrtc";

export const GATE_TAIL_MS = 300;

/** Read-only probe for the browser test harness (backend/eval). */
export type HarnessHook = {
  lastVoiced?: number;
  state?: unknown;
  /** Leak probe (FR-4): open transports + live engine nodes. */
  diag?: () => Diag;
  /** Raw OpenAI events of the current realtime transport (fixture capture). */
  oaiEvents?: () => unknown[];
  /** `?source=file`: play a fixture as the microphone; resolves when it ends. */
  playFile?: (url: string) => Promise<{ durationMs: number }>;
  fileStartedAt?: () => number | null;
  /** VAD mode: label/direction for the next detected turns (harness). */
  setVadSpeaker?: (s: Speaker) => void;
  /** Record the output audio (what the listener hears); stop returns base64 webm. */
  recStart?: () => void;
  recStop?: () => Promise<string | null>;
};
export type Diag = {
  transport: string | null;
  openTransports: number;
  created: number;
  engineNodes: number;
  micLive: boolean;
  /** Mic gating probe: is output playing, and is the uplink currently live? */
  playing: boolean;
  uplinkLive: boolean | null;
};

export function harnessHook(): HarnessHook {
  const w = globalThis as unknown as { __wb?: HarnessHook };
  return (w.__wb ??= {});
}

export type RealtimeKind = "webrtc" | "relay" | "auto";

export type SessionConfig = {
  pair: { a: Lang; b: Lang };
  mode: Mode;
  pipeline: Pipeline;
  wsUrl?: string;
  pauseCommitMs?: number | null;
  turnMode?: TurnMode;
  /** Realtime transport: WebRTC (default), WS relay, or WebRTC with relay fallback. */
  realtime?: RealtimeKind;
  silenceDurationMs?: number;
  /** Cascade provider overrides per session (FR-9), e.g. {mt: "anthropic", tts: "elevenlabs"}. */
  providers?: Record<string, string>;
  /** Cascade: in-turn silence that triggers a speculative-MT hint (ms; null = off). */
  pauseHintMs?: number | null;
  /** min voiced ms before an in-turn pause commits (shorter stretches merge forward) */
  minSegmentMs?: number;
  /** "file" = benchmark harness input (DESIGN §9); default "mic". */
  source?: "mic" | "file";
  /** VAD mode: which speaker label/direction new turns get in the UI. */
  vadSpeaker?: Speaker;
};

type AnyTransport = Transport & {
  kind?: string;
  sendAudio?(pcm: Int16Array): void;
  isOpen?: boolean;
  vadTurn?(turnId: number): void;
  setUplinkEnabled?(on: boolean): void;
  liveResources?: Record<string, boolean>;
  recorded?: unknown[];
  uplinkLive?: boolean;
};

export class InterpreterSession implements InterpreterSessionApi {
  private listeners = new Set<SessionListener>();
  private engine: AudioEngine | null = null;
  private transport: AnyTransport | null = null;
  private created: AnyTransport[] = [];
  private fileSource: FileSource | null = null;
  private gateTimer: ReturnType<typeof setTimeout> | undefined;
  private turns: TurnController;
  private vadSeg: VadSegmenter;
  private speechEnd = new Map<number, number>();
  private playingTurn: number | null = null;
  private gateUntil = 0;
  private lastCommittedTurn: number | null = null;
  mode: Mode;
  pipeline: Pipeline;
  turnMode: TurnMode;
  providers: Record<string, string>;

  constructor(private cfg: SessionConfig) {
    this.mode = cfg.mode;
    this.pipeline = cfg.pipeline;
    this.turnMode = cfg.turnMode ?? "ptt";
    this.providers = { ...(cfg.providers ?? {}) };
    this.turns = new TurnController(cfg.pair, cfg.pauseCommitMs ?? 300, cfg.pauseHintMs ?? null, cfg.minSegmentMs ?? 1000);
    this.vadSeg = new VadSegmenter(cfg.silenceDurationMs ?? 400);
    const hook = harnessHook();
    hook.setVadSpeaker = (sp) => this.setVadSpeaker(sp);
    hook.diag = () => this.diag();
    hook.oaiEvents = () => this.transport?.recorded ?? [];
    hook.recStart = () => this.engine?.startRecording();
    hook.recStop = async () => {
      const blob = await this.engine?.stopRecording();
      if (!blob) return null;
      const url = await new Promise<string>((res) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result));
        r.readAsDataURL(blob);
      });
      return url.slice(url.indexOf(",") + 1);
    };
  }

  diag(): Diag {
    const open = (t: AnyTransport) => t.isOpen === true || Object.values(t.liveResources ?? {}).some(Boolean);
    return {
      transport: this.transport ? `${this.transport.mode}:${this.transport.kind ?? "ws"}` : null,
      openTransports: this.created.filter(open).length,
      created: this.created.length,
      engineNodes: this.engine?.liveNodes ?? 0,
      micLive: this.engine?.micStream.getAudioTracks().some((t) => t.readyState === "live") ?? false,
      playing: this.playingTurn !== null,
      uplinkLive: this.transport?.uplinkLive ?? null,
    };
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
      if (this.cfg.source === "file") {
        this.fileSource = new FileSource();
        const fs = this.fileSource;
        harnessHook().playFile = (url: string) => fs.play(url);
        harnessHook().fileStartedAt = () => fs.startedAt;
        mic = fs.stream;
      } else {
        mic = await requestMic();
      }
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

  private wsBase(): string {
    return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
  }

  private realtimeHooks() {
    return {
      emit: this.emit,
      speechEnd: (id: number) => this.speechEnd.get(id),
      onSpeechStarted: () => this.vadSpeechStarted(),
      onSpeechStopped: () => this.vadSpeechStopped(),
    };
  }

  private makeTransport(kind: "webrtc" | "relay" | null = null): AnyTransport {
    if (this.mode === "realtime") {
      const common = { pair: this.cfg.pair, turnMode: this.turnMode, silenceDurationMs: this.cfg.silenceDurationMs ?? 400, ...this.realtimeHooks() };
      if ((kind ?? this.cfg.realtime ?? "webrtc") === "relay") {
        return new RealtimeRelayTransport({ ...common, url: `${this.wsBase()}/ws/realtime`, onAudio: (turnId, pcm) => this.engine?.play(turnId, pcm) });
      }
      return new RealtimeTransport({
        ...common,
        micStream: this.engine!.micStream,
        onRemoteStream: (stream) => this.engine?.attachRemote(stream),
        onRemoteGone: () => this.engine?.detachRemote(),
        onPlaying: (turnId, playing) => this.onRemotePlaying(turnId, playing),
      });
    }
    const url = this.cfg.wsUrl ?? `${this.wsBase()}/ws/cascade`;
    return new CascadeTransport({
      url,
      pipeline: this.pipeline,
      src: this.cfg.pair.a,
      tgt: this.cfg.pair.b,
      providers: this.providers,
      emit: this.emit,
      onAudio: (turnId, pcm) => this.engine?.play(turnId, pcm),
    });
  }

  private async connectTransport(): Promise<void> {
    this.emit({ type: "session.state", state: "connecting", mode: this.mode });
    const auto = this.mode === "realtime" && this.cfg.realtime === "auto";
    try {
      let t = this.track(this.makeTransport(auto ? "webrtc" : null));
      try {
        await t.connect();
      } catch (e) {
        if (!auto) throw e;
        await t.close();
        this.emit({ type: "error", code: "webrtc_fallback", stage: "transport", retryable: false, message: `WebRTC failed (${(e as Error).message}); using the WebSocket relay.` });
        t = this.track(this.makeTransport("relay"));
        await t.connect();
      }
      this.transport = t;
      this.emit({ type: "session.state", state: "ready", mode: this.mode });
    } catch (e) {
      await this.transport?.close();
      for (const t of this.created) if (t !== this.transport) void t.close();
      this.transport = null;
      if (!(e as Error & { reported?: boolean }).reported)
        this.emit({ type: "error", code: "connect_failed", stage: "transport", retryable: true, message: (e as Error).message });
      this.emit({ type: "session.state", state: "error", mode: this.mode, detail: "connect_failed" });
    }
  }

  private track(t: AnyTransport): AnyTransport {
    this.created.push(t);
    if (this.created.length > 50) this.created.shift();
    return t;
  }

  setVadSpeaker(sp: Speaker): void {
    this.cfg = { ...this.cfg, vadSpeaker: sp };
  }

  async setTurnMode(m: TurnMode): Promise<void> {
    if (m === this.turnMode) return;
    this.turnMode = m;
    this.vadSeg.reset();
    this.turns.active = null;
    if (this.engine) {
      await this.teardownTransport();
      await this.connectTransport();
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

  /** Swap cascade providers by config (FR-9): reconnects the cascade transport only. */
  async setProviders(p: Record<string, string>): Promise<void> {
    this.providers = { ...this.providers, ...p };
    if (this.engine && this.mode === "cascade") {
      await this.teardownTransport();
      await this.connectTransport();
    }
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
    clearTimeout(this.gateTimer);
    this.playingTurn = null;
    this.lastCommittedTurn = null;
    this.turns.active = null;
    this.engine?.flush();
    this.engine?.disarmTap();
    this.engine?.detachRemote();
    const t = this.transport;
    this.transport = null;
    if (t) await t.close();
  }

  pttDown(speaker: Speaker): void {
    if (!this.engine || this.turns.active || this.turnMode === "vad") return;
    // Barge-in (FR-1.3): a press during playback flushes it and cancels that turn.
    if (this.playingTurn !== null || this.lastCommittedTurn !== null) {
      this.engine.flush();
      this.engine.disarmTap();
      const victim = this.playingTurn ?? this.lastCommittedTurn;
      if (victim !== null) this.transport?.cancel(victim);
      this.lastCommittedTurn = null;
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
    if (this.turnMode === "vad") return;
    this.endTurn();
  }

  /** PTT release, or the cascade VAD silence window elapsing: final commit. */
  private endTurn(): void {
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

  // ----- realtime VAD mode: the server detects turns; the browser still owns
  // t_speech_end (last voiced capture frame, same detector as PTT).
  private vadSpeechStarted(): void {
    if (this.turnMode !== "vad" || !this.engine || this.turns.active) return;
    const speaker = this.cfg.vadSpeaker ?? "A";
    const now = performance.now();
    const turn = this.turns.pttDown(speaker, now);
    this.emit({ type: "turn.started", turn_id: turn.id, src: turn.src, tgt: turn.tgt, speaker, mode: this.mode, at: now });
  }

  private vadSpeechStopped(): void {
    if (this.turnMode !== "vad") return;
    const end = this.turns.pttUp(performance.now());
    if (!end) return;
    const id = end.turn.id;
    this.speechEnd.set(id, end.tSpeechEnd);
    this.emit({ type: "speech.ended", turn_id: id, t_speech_end: end.tSpeechEnd });
    this.engine?.armTap(id);
    this.transport?.vadTurn?.(id);
    this.lastCommittedTurn = id;
    this.emit({ type: "latency.mark", turn_id: id, mark: "server_vad_stop", ms: performance.now() - end.tSpeechEnd, clock: "browser" });
  }

  /** WebRTC output buffer started/stopped (server-side playback state). */
  private onRemotePlaying(turnId: number, playing: boolean): void {
    clearTimeout(this.gateTimer);
    if (playing) {
      this.playingTurn = turnId;
      return;
    }
    if (this.playingTurn === turnId) this.playingTurn = null;
    this.gateUntil = performance.now() + GATE_TAIL_MS;
    const t = this.transport;
    t?.setUplinkEnabled?.(false);
    this.gateTimer = setTimeout(() => t?.setUplinkEnabled?.(true), GATE_TAIL_MS);
  }

  private onFrame(pcm: Int16Array, voiced: boolean, tPerf: number): void {
    if (voiced) harnessHook().lastVoiced = tPerf;
    const gated = this.playingTurn !== null || performance.now() < this.gateUntil;
    if (this.turnMode === "vad" && this.mode === "realtime") {
      // Server VAD needs a continuous stream (relay); WebRTC sends the track itself.
      if (voiced && !gated && this.turns.active) this.turns.frame(true, tPerf);
      this.transport?.sendAudio?.(gated ? new Int16Array(pcm.length) : pcm);
      return;
    }
    if (this.turnMode === "vad" && this.mode === "cascade") {
      this.cascadeVadFrame(pcm, voiced && !gated, tPerf);
      return;
    }
    const act = this.turns.frame(voiced && !gated, tPerf);
    if (!act.send || !this.transport) return;
    this.transport.sendAudio?.(gated ? new Int16Array(pcm.length) : pcm);
    if (act.pauseHint && this.turns.active) this.transport.pauseHint?.(this.turns.active.id);
    if (act.pauseCommit && this.turns.active) this.transport.commit(this.turns.active.id, false);
  }

  /** Cascade VAD mode: local segmentation with the Realtime-matched silence window. */
  private cascadeVadFrame(pcm: Int16Array, voiced: boolean, tPerf: number): void {
    if (!this.transport || this.transport.isOpen === false) return;
    const act = this.vadSeg.frame(pcm, voiced, tPerf);
    if (act.start) {
      if (this.turns.active) return;
      const speaker = this.cfg.vadSpeaker ?? "A";
      const now = performance.now();
      const turn = this.turns.pttDown(speaker, now);
      this.transport.turnStart(turn.id, turn.src, turn.tgt);
      this.emit({ type: "turn.started", turn_id: turn.id, src: turn.src, tgt: turn.tgt, speaker, mode: this.mode, at: now });
      for (const f of act.start) this.transport.sendAudio?.(f); // pre-roll incl. this frame
      this.turns.frame(true, tPerf);
      return;
    }
    if (!this.turns.active) return;
    const fa = this.turns.frame(voiced, tPerf);
    this.transport.sendAudio?.(pcm);
    if (act.end) {
      this.endTurn();
      return;
    }
    if (fa.pauseHint) this.transport.pauseHint?.(this.turns.active.id);
    if (fa.pauseCommit) this.transport.commit(this.turns.active.id, false);
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
    await Promise.all(this.created.map((t) => t.close()));
    await this.engine?.close();
    this.engine = null;
    await this.fileSource?.close();
    this.fileSource = null;
    this.turns.active = null;
    this.emit({ type: "session.state", state: "closed", mode: this.mode });
  }
}
