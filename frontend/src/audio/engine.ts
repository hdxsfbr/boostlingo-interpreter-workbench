/**
 * AudioEngine: one AudioContext shared by both modes.
 *
 *   mic -> capture worklet (24 kHz PCM16 frames + VAD) -> (muted sink)
 *   playback worklet (cascade PCM) --\
 *   remote WebRTC track (realtime) ---+-> output tap -> destination
 *
 * Both modes therefore measure speech end and first audible sample with the
 * same detectors on the same clock (DESIGN §4).
 */
import captureUrl from "./capture.worklet.ts?worker&url";
import playbackUrl from "./playback.worklet.ts?worker&url";
import tapUrl from "./outputTap.worklet.ts?worker&url";
import { RenderClock } from "./clock";

export type Frame = { pcm: Int16Array; rms: number; voiced: boolean; tPerf: number };

export class MicError extends Error {
  constructor(public readonly code: "mic_denied" | "mic_missing" | "mic_timeout" | "insecure_context" | "mic_failed", message: string) {
    super(message);
  }
}

export const MIC_PROMPT_TIMEOUT_MS = 15000;

export async function requestMic(timeoutMs = MIC_PROMPT_TIMEOUT_MS): Promise<MediaStream> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new MicError("insecure_context", "Microphone needs a secure context. Open the app via http://localhost (SSH port-forward) or HTTPS.");
  }
  const gum = navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, rej) => {
    timer = setTimeout(() => rej(new MicError("mic_timeout", "No answer to the microphone prompt. Allow microphone access and retry.")), timeoutMs);
  });
  try {
    return await Promise.race([gum, timeout]);
  } catch (e) {
    if (e instanceof MicError) throw e;
    const name = (e as DOMException)?.name;
    if (name === "NotAllowedError" || name === "SecurityError")
      throw new MicError("mic_denied", "Microphone permission was denied. Allow it in the browser's site settings, then press Retry.");
    if (name === "NotFoundError" || name === "OverconstrainedError")
      throw new MicError("mic_missing", "No microphone found. Plug in a headset and press Retry.");
    throw new MicError("mic_failed", `Could not open the microphone (${name ?? "unknown error"}).`);
  } finally {
    clearTimeout(timer);
  }
}

export class AudioEngine {
  readonly ctx: AudioContext;
  readonly clock = new RenderClock();
  readonly micStream: MediaStream;
  private capture!: AudioWorkletNode;
  private playback!: AudioWorkletNode;
  private tap!: AudioWorkletNode;
  private nodes: AudioNode[] = [];
  private remote: { src: MediaStreamAudioSourceNode; el: HTMLAudioElement } | null = null;

  onFrame: (f: Frame) => void = () => {};
  onAudible: (turnId: number, tPerf: number) => void = () => {};
  onPlaybackStarted: (turnId: number) => void = () => {};
  onPlaybackDrained: (turnId: number) => void = () => {};

  private constructor(ctx: AudioContext, mic: MediaStream) {
    this.ctx = ctx;
    this.micStream = mic;
  }

  /** Must be called from a user gesture (autoplay policy, R§5.4). */
  static async create(ctx: AudioContext, mic: MediaStream): Promise<AudioEngine> {
    const eng = new AudioEngine(ctx, mic);
    await eng.init();
    return eng;
  }

  private async init(): Promise<void> {
    const { ctx } = this;
    await Promise.all([captureUrl, playbackUrl, tapUrl].map((u) => ctx.audioWorklet.addModule(u)));
    const mic = ctx.createMediaStreamSource(this.micStream);
    this.capture = new AudioWorkletNode(ctx, "capture-processor", { numberOfOutputs: 1 });
    const sink = ctx.createGain();
    sink.gain.value = 0;
    mic.connect(this.capture).connect(sink).connect(ctx.destination);
    this.playback = new AudioWorkletNode(ctx, "playback-processor", { numberOfInputs: 0, outputChannelCount: [1] });
    this.tap = new AudioWorkletNode(ctx, "output-tap-processor");
    this.playback.connect(this.tap).connect(ctx.destination);
    this.nodes = [mic, this.capture, sink, this.playback, this.tap];

    this.capture.port.onmessage = (e) => {
      const m = e.data;
      if (m.type !== "frame") return;
      this.clock.observe(m.t);
      this.onFrame({ pcm: m.pcm, rms: m.rms, voiced: m.voiced, tPerf: this.clock.toPerf(m.t) });
    };
    this.tap.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "audible") this.onAudible(m.turnId, this.renderToAudiblePerf(m.t));
    };
    this.playback.port.onmessage = (e) => {
      const m = e.data;
      if (m.type === "started") this.onPlaybackStarted(m.turnId);
      else if (m.type === "drained") this.onPlaybackDrained(m.turnId);
    };
  }

  /** Render time -> perf time the sample reaches the speakers/headphones. */
  private renderToAudiblePerf(t: number): number {
    const outLat = (this.ctx as AudioContext & { outputLatency?: number }).outputLatency ?? this.ctx.baseLatency ?? 0;
    return this.clock.toPerf(t) + outLat * 1000;
  }

  setVadThreshold(rms: number): void {
    this.capture.port.postMessage({ type: "threshold", value: rms });
  }
  play(turnId: number, pcm: Int16Array): void {
    this.playback.port.postMessage({ type: "push", turnId, pcm }, [pcm.buffer]);
  }
  flush(): void {
    this.playback.port.postMessage({ type: "flush" });
  }
  armTap(turnId: number): void {
    this.tap.port.postMessage({ type: "arm", turnId });
  }
  disarmTap(): void {
    this.tap.port.postMessage({ type: "disarm" });
  }

  /** Realtime (M2): route the remote WebRTC track through the same tap.
   * Chrome only pulls remote audio into Web Audio if a (muted) media element
   * also consumes the stream. */
  attachRemote(stream: MediaStream): void {
    this.detachRemote();
    const el = new Audio();
    el.muted = true;
    el.srcObject = stream;
    void el.play().catch(() => {});
    const src = this.ctx.createMediaStreamSource(stream);
    src.connect(this.tap);
    this.remote = { src, el };
  }
  detachRemote(): void {
    if (!this.remote) return;
    this.remote.src.disconnect();
    this.remote.el.srcObject = null;
    this.remote = null;
  }

  /** Number of live audio nodes owned by the engine (leak checks, FR-4). */
  get liveNodes(): number {
    return this.nodes.length + (this.remote ? 1 : 0);
  }

  async close(): Promise<void> {
    this.detachRemote();
    for (const n of this.nodes) n.disconnect();
    this.nodes = [];
    this.micStream.getTracks().forEach((t) => t.stop());
    if (this.ctx.state !== "closed") await this.ctx.close();
  }
}
