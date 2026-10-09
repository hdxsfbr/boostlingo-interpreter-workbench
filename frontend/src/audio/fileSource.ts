/**
 * File source for the benchmark harness (DESIGN §9, `?source=file`): plays a
 * fixture WAV into a MediaStreamAudioDestinationNode whose track replaces the
 * microphone for BOTH transports (cascade capture worklet, Realtime WebRTC
 * uplink). Between files it outputs silence, like a quiet room. No browser
 * audio processing is applied, so both modes get identical input.
 */
export class FileSource {
  readonly ctx: AudioContext;
  private dest: MediaStreamAudioDestinationNode;
  private current: AudioBufferSourceNode | null = null;
  private cache = new Map<string, AudioBuffer>();

  constructor() {
    this.ctx = new AudioContext({ latencyHint: "interactive" });
    this.dest = this.ctx.createMediaStreamDestination();
    void this.ctx.resume();
  }

  get stream(): MediaStream {
    return this.dest.stream;
  }

  async load(url: string): Promise<AudioBuffer> {
    let buf = this.cache.get(url);
    if (!buf) {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`fixture ${url}: HTTP ${res.status}`);
      buf = await this.ctx.decodeAudioData(await res.arrayBuffer());
      this.cache.set(url, buf);
    }
    return buf;
  }

  /** Starts playback; resolves when the file has finished playing. */
  async play(url: string): Promise<{ durationMs: number }> {
    const buf = await this.load(url);
    this.stop();
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.dest);
    this.current = src;
    const ended = new Promise<void>((resolve) => (src.onended = () => resolve()));
    src.start();
    await ended;
    if (this.current === src) this.current = null;
    return { durationMs: buf.duration * 1000 };
  }

  stop(): void {
    try {
      this.current?.stop();
    } catch {
      /* not started */
    }
    this.current?.disconnect();
    this.current = null;
  }

  async close(): Promise<void> {
    this.stop();
    this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx.state !== "closed") await this.ctx.close();
  }
}
