/**
 * Realtime transport (D1): browser <-> OpenAI over WebRTC with an ephemeral
 * client secret minted by FastAPI (/api/realtime/session). The standard API
 * key never reaches the browser.
 *
 * - Uplink: a *clone* of the mic track, so gating (`enabled = false`) never
 *   silences the local capture worklet / VAD that measures t_speech_end.
 * - Downlink: the remote track goes through AudioEngine.attachRemote, i.e. the
 *   same output tap as cascade playback (one t_first_audible definition).
 * - Control: JSON events on the "oai-events" data channel, normalised by
 *   OaiNormalizer into the shared SessionEvent contract.
 */
import type { Lang, SessionEvent, Transport } from "../protocol";
import { HistoryPruner, OaiNormalizer, type OaiEvent } from "../normalizers/oaiEvents";

export const CALLS_URL = "https://api.openai.com/v1/realtime/calls";

export type TurnMode = "ptt" | "vad";

export type RealtimeHooks = {
  emit: (ev: SessionEvent) => void;
  speechEnd: (turnId: number) => number | undefined;
  /** Remote audio track arrived (route it through the output tap). */
  onRemoteStream: (stream: MediaStream) => void;
  onRemoteGone: () => void;
  /** Server-side output playback state, for mic gating + barge-in. */
  onPlaying: (turnId: number, playing: boolean) => void;
  /** VAD mode: server detected speech start / stop. */
  onSpeechStarted?: () => void;
  onSpeechStopped?: () => void;
};

export type RealtimeOptions = RealtimeHooks & {
  pair: { a: Lang; b: Lang };
  micStream: MediaStream;
  turnMode?: TurnMode;
  silenceDurationMs?: number;
  model?: string;
  mintUrl?: string;
  connectTimeoutMs?: number;
  /** Injectable for tests. */
  fetchFn?: typeof fetch;
  createPeer?: () => RTCPeerConnection;
};

export type MintResponse = { value: string; expires_at: number; model: string; turn_mode: TurnMode };

export class MintError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string, public readonly retryAfter?: number) {
    super(message);
  }
}

/** POST /api/realtime/session -> ephemeral secret. Maps 429 and auth errors. */
export async function mintSecret(fetchFn: typeof fetch, url: string, body: Record<string, unknown>): Promise<MintResponse> {
  const res = await fetchFn(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail: { code?: string; message?: string } = {};
    try {
      const j = await res.json();
      detail = (j.detail ?? j) as typeof detail;
    } catch {
      /* non-JSON */
    }
    const ra = Number(res.headers.get("Retry-After") ?? "");
    const code = res.status === 429 ? "rate_limited" : (detail.code ?? `http_${res.status}`);
    throw new MintError(res.status, code, detail.message ?? `secret mint failed (${res.status})`, Number.isFinite(ra) && ra > 0 ? ra : undefined);
  }
  return (await res.json()) as MintResponse;
}

export class RealtimeTransport implements Transport {
  readonly mode = "realtime" as const;
  readonly kind = "webrtc" as const;
  private pc: RTCPeerConnection | null = null;
  private dc: RTCDataChannel | null = null;
  private uplink: MediaStreamTrack | null = null;
  private normalizer: OaiNormalizer;
  private pruner = new HistoryPruner(2);
  private activeTurn: number | null = null;
  private playing = false;
  private closed = false;
  model = "";
  /** Raw data-channel events (harness fixture recording; bounded). */
  readonly recorded: OaiEvent[] = [];

  constructor(private readonly opts: RealtimeOptions) {
    this.normalizer = new OaiNormalizer({
      emit: opts.emit,
      speechEnd: opts.speechEnd,
      onOutputAudio: (turn, playing) => {
        this.playing = playing;
        this.updateGate();
        opts.onPlaying(turn, playing);
      },
      onSpeechStarted: opts.onSpeechStarted,
      onSpeechStopped: opts.onSpeechStopped,
    });
  }

  get turnMode(): TurnMode {
    return this.opts.turnMode ?? "ptt";
  }

  get isOpen(): boolean {
    return this.dc?.readyState === "open";
  }

  async connect(): Promise<void> {
    const o = this.opts;
    const fetchFn = o.fetchFn ?? fetch.bind(globalThis);
    const secret = await mintSecret(fetchFn, o.mintUrl ?? "/api/realtime/session", {
      a: o.pair.a,
      b: o.pair.b,
      turn_mode: this.turnMode,
      silence_duration_ms: o.silenceDurationMs ?? 400,
      ...(o.model ? { model: o.model } : {}),
    });
    this.model = secret.model;
    if (this.closed) throw new Error("transport closed during connect");

    const pc = (o.createPeer ?? (() => new RTCPeerConnection()))();
    this.pc = pc;
    const mic = o.micStream.getAudioTracks()[0];
    if (!mic) throw new Error("no microphone track");
    this.uplink = mic.clone();
    this.updateGate();
    pc.addTrack(this.uplink);
    pc.ontrack = (e) => o.onRemoteStream(e.streams[0] ?? new MediaStream([e.track]));
    pc.onconnectionstatechange = () => {
      if (!this.closed && (pc.connectionState === "failed" || pc.connectionState === "disconnected")) {
        o.emit({ type: "error", code: "webrtc_" + pc.connectionState, stage: "transport", retryable: true, message: `WebRTC connection ${pc.connectionState}` });
      }
    };
    const dc = pc.createDataChannel("oai-events");
    this.dc = dc;
    dc.onmessage = (e) => this.onEvent(JSON.parse(e.data as string) as OaiEvent);

    const opened = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("realtime data channel open timeout")), o.connectTimeoutMs ?? 8000);
      dc.onopen = () => {
        clearTimeout(timer);
        resolve();
      };
      dc.onclose = () => {
        clearTimeout(timer);
        if (!this.closed) {
          reject(new Error("realtime data channel closed"));
          o.emit({ type: "error", code: "disconnected", stage: "transport", retryable: true, message: "Realtime data channel closed" });
        }
      };
    });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), o.connectTimeoutMs ?? 8000);
    let res: Response;
    try {
      res = await fetchFn(CALLS_URL, {
        method: "POST",
        body: offer.sdp,
        headers: { Authorization: `Bearer ${secret.value}`, "Content-Type": "application/sdp" },
        signal: ctrl.signal,
      });
    } catch (e) {
      throw new Error(ctrl.signal.aborted ? "realtime SDP exchange timeout" : `realtime SDP exchange failed: ${(e as Error).message}`);
    } finally {
      clearTimeout(t);
    }
    if (!res.ok) throw new MintError(res.status, res.status === 429 ? "rate_limited" : `sdp_${res.status}`, `realtime SDP exchange failed (${res.status})`);
    await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
    await opened;
    o.emit({ type: "session.ready", mode: "realtime", pipeline: "webrtc", providers: { realtime: secret.model, transport: "webrtc" } });
  }

  private send(ev: Record<string, unknown>): void {
    if (this.dc?.readyState === "open") this.dc.send(JSON.stringify(ev));
  }

  private onEvent(ev: OaiEvent): void {
    if (this.recorded.length < 2000) this.recorded.push(ev);
    this.normalizer.handle(ev);
    for (const id of this.pruner.observe(ev)) this.send({ type: "conversation.item.delete", item_id: id });
  }

  /** Mic gating: the uplink is live only inside a PTT turn (PTT) or when the
   * model is not speaking (VAD), so the model never hears its own output. */
  private updateGate(): void {
    if (!this.uplink) return;
    this.uplink.enabled = this.turnMode === "vad" ? !this.playing : this.activeTurn !== null;
  }

  /** VAD mode: tail gate after playback, controlled by the session. */
  setUplinkEnabled(on: boolean): void {
    if (this.uplink && this.turnMode === "vad") this.uplink.enabled = on && !this.playing;
  }

  turnStart(turnId: number, _src: Lang, _tgt: Lang): void {
    this.activeTurn = turnId;
    if (this.turnMode === "ptt") this.send({ type: "input_audio_buffer.clear" });
    this.updateGate();
  }

  /** VAD mode: the server committed on its own; just bind the turn id. */
  vadTurn(turnId: number): void {
    this.normalizer.turnCommitted(turnId);
  }

  commit(turnId: number, final: boolean): void {
    if (!final || this.turnMode !== "ptt") return; // in-turn pauses are a cascade concept
    this.activeTurn = null;
    this.updateGate();
    this.normalizer.turnCommitted(turnId);
    this.send({ type: "input_audio_buffer.commit" });
    this.send({ type: "response.create" });
  }

  cancel(turnId: number): void {
    this.normalizer.turnCancelled(turnId);
    this.send({ type: "response.cancel" });
    this.send({ type: "output_audio_buffer.clear" });
  }

  async close(): Promise<void> {
    this.closed = true;
    this.activeTurn = null;
    try {
      this.dc?.close();
    } catch {
      /* already closed */
    }
    this.pc?.getSenders().forEach((s) => s.track?.stop());
    this.pc?.close();
    this.uplink?.stop();
    this.opts.onRemoteGone();
    this.dc = null;
    this.pc = null;
    this.uplink = null;
  }

  /** Leak probe for the harness. */
  get liveResources(): { pc: boolean; dc: boolean; uplink: boolean } {
    return { pc: this.pc !== null, dc: this.dc !== null, uplink: this.uplink?.readyState === "live" };
  }
}
