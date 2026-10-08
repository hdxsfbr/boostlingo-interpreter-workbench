/**
 * Maps AudioContext render time to performance.now() so speech end (capture
 * worklet) and first audible sample (output tap) share ONE browser clock
 * (NFR-5). Each worklet message carries the render time `t` it was produced
 * at; receipt time minus render time is >= the true offset, so the windowed
 * minimum is a tight estimate that also tracks slow clock drift.
 */
export class RenderClock {
  private samples: number[] = [];
  constructor(private readonly window = 150) {}

  observe(renderTimeS: number, receivedAtMs = performance.now()): void {
    this.samples.push(receivedAtMs - renderTimeS * 1000);
    if (this.samples.length > this.window) this.samples.shift();
  }

  get ready(): boolean {
    return this.samples.length > 0;
  }

  /** Render time (s) -> performance.now() ms at which it was rendered. */
  toPerf(renderTimeS: number): number {
    return renderTimeS * 1000 + Math.min(...this.samples);
  }
}
