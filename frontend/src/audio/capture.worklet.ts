/**
 * Mic capture: downsample the context rate to PCM16 mono 24 kHz in 20 ms
 * frames, plus a frame-energy VAD. Every frame is posted with its RMS, a
 * voiced flag and the context time at which its last sample was rendered;
 * the main thread decides what to send (PTT, gating) and keeps the
 * "last voiced frame" that defines t_speech_end in BOTH modes (DESIGN §4).
 */
const OUT_RATE = 24000;
const FRAME = 480; // 20 ms @ 24 kHz

class CaptureProcessor extends AudioWorkletProcessor {
  private ratio = sampleRate / OUT_RATE;
  private pos = 0; // fractional read position into the pending input
  private pending = new Float32Array(0);
  private frame = new Float32Array(FRAME);
  private fill = 0;
  private threshold = 0.012; // RMS (~ -38 dBFS); tunable via message

  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent) => {
      if (e.data?.type === "threshold") this.threshold = e.data.value;
    };
  }

  process(inputs: Float32Array[][]): boolean {
    const ch = inputs[0]?.[0];
    if (!ch) return true;
    // append to pending input
    const merged = new Float32Array(this.pending.length + ch.length);
    merged.set(this.pending);
    merged.set(ch, this.pending.length);
    const blockStart = currentTime - this.pending.length / sampleRate;
    let p = this.pos;
    while (p + 1 < merged.length) {
      const i = Math.floor(p);
      const f = p - i;
      this.frame[this.fill++] = merged[i] * (1 - f) + merged[i + 1] * f;
      p += this.ratio;
      if (this.fill === FRAME) {
        this.emit(blockStart + p / sampleRate);
        this.fill = 0;
      }
    }
    const keep = Math.floor(p);
    this.pending = merged.slice(keep);
    this.pos = p - keep;
    return true;
  }

  private emit(t: number): void {
    const pcm = new Int16Array(FRAME);
    let sum = 0;
    for (let i = 0; i < FRAME; i++) {
      const s = Math.max(-1, Math.min(1, this.frame[i]));
      sum += s * s;
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    const rms = Math.sqrt(sum / FRAME);
    this.port.postMessage({ type: "frame", pcm, rms, voiced: rms >= this.threshold, t }, [pcm.buffer]);
  }
}

registerProcessor("capture-processor", CaptureProcessor);
