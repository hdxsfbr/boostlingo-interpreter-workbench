/**
 * Output tap: a pass-through node placed right before the destination in
 * BOTH modes (cascade playback graph; Realtime remote WebRTC track). After
 * `arm`, it reports the context time of the first sample above threshold:
 * that is t_first_audible (before adding outputLatency on the main thread).
 */
class OutputTapProcessor extends AudioWorkletProcessor {
  private armed: number | null = null;
  private threshold = 0.004;

  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent) => {
      const m = e.data;
      if (m.type === "arm") this.armed = m.turnId;
      else if (m.type === "disarm") this.armed = null;
      else if (m.type === "threshold") this.threshold = m.value;
    };
  }

  process(inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const input = inputs[0];
    const output = outputs[0];
    for (let ch = 0; ch < output.length; ch++) {
      const src = input[ch] ?? input[0];
      if (src) output[ch].set(src);
      else output[ch].fill(0);
    }
    const ch0 = input[0];
    if (this.armed !== null && ch0) {
      for (let i = 0; i < ch0.length; i++) {
        if (Math.abs(ch0[i]) >= this.threshold) {
          this.port.postMessage({ type: "audible", turnId: this.armed, t: currentTime + i / sampleRate });
          this.armed = null;
          break;
        }
      }
    }
    return true;
  }
}

registerProcessor("output-tap-processor", OutputTapProcessor);
