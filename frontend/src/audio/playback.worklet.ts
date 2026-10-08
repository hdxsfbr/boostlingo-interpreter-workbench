/**
 * Gapless playback queue for PCM16 mono 24 kHz chunks, resampled to the
 * context rate. Chunks play strictly in arrival order (no overlap, FR-1.3);
 * `flush` drops everything (barge-in / mode switch). Because samples are
 * pulled by the audio clock, the queue cannot drift (NFR-3).
 */
const IN_RATE = 24000;

type Chunk = { turnId: number; data: Float32Array; off: number };

class PlaybackProcessor extends AudioWorkletProcessor {
  private queue: Chunk[] = [];
  private step = IN_RATE / sampleRate;
  private carry: { turnId: number; last: number; pos: number } | null = null;
  private playing: number | null = null;

  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent) => {
      const m = e.data;
      if (m.type === "push") this.push(m.turnId, m.pcm as Int16Array);
      else if (m.type === "flush") {
        this.queue = [];
        this.carry = null;
        if (this.playing !== null) this.port.postMessage({ type: "drained", turnId: this.playing, flushed: true });
        this.playing = null;
      }
    };
  }

  /** Linear-interpolation resample 24 kHz -> context rate, stateful per turn. */
  private push(turnId: number, pcm: Int16Array): void {
    const src = new Float32Array(pcm.length + 1);
    const c = this.carry && this.carry.turnId === turnId ? this.carry : null;
    src[0] = c ? c.last : pcm.length ? pcm[0] / 0x8000 : 0;
    for (let i = 0; i < pcm.length; i++) src[i + 1] = pcm[i] / 0x8000;
    let pos = c ? c.pos : 1;
    const out: number[] = [];
    while (pos <= src.length - 1) {
      const i = Math.floor(pos);
      const f = pos - i;
      out.push(i + 1 < src.length ? src[i] * (1 - f) + src[i + 1] * f : src[i]);
      pos += this.step;
    }
    this.carry = { turnId, last: src[src.length - 1], pos: pos - (src.length - 1) };
    this.queue.push({ turnId, data: Float32Array.from(out), off: 0 });
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const out = outputs[0][0];
    let w = 0;
    while (w < out.length && this.queue.length) {
      const c = this.queue[0];
      if (this.playing !== c.turnId) {
        if (this.playing !== null) this.port.postMessage({ type: "drained", turnId: this.playing });
        this.playing = c.turnId;
        this.port.postMessage({ type: "started", turnId: c.turnId, t: currentTime + w / sampleRate });
      }
      const n = Math.min(out.length - w, c.data.length - c.off);
      out.set(c.data.subarray(c.off, c.off + n), w);
      w += n;
      c.off += n;
      if (c.off >= c.data.length) this.queue.shift();
    }
    for (let i = w; i < out.length; i++) out[i] = 0;
    for (let ch = 1; ch < outputs[0].length; ch++) outputs[0][ch].set(out);
    if (!this.queue.length && this.playing !== null) {
      this.port.postMessage({ type: "drained", turnId: this.playing });
      this.playing = null;
    }
    return true;
  }
}

registerProcessor("playback-processor", PlaybackProcessor);
