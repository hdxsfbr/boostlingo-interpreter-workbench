/**
 * Pure push-to-talk turn logic driven by capture frames (unit-tested).
 * - t_speech_end = last voiced frame before PTT release (DESIGN §4), so a
 *   late release counts against latency exactly as the user perceives it.
 * - Optional in-turn pause commits (cascade): a pause >= pauseCommitMs after
 *   speech yields one non-final commit, so long turns get segment finals.
 *   A pause only commits once the segment holds >= minSegmentMs of voiced
 *   audio (M5): shorter stretches ("Do you have... any allergies?") are
 *   merged into the next segment instead of being translated as fragments.
 */
import type { Lang, Speaker } from "./protocol";

export type ActiveTurn = {
  id: number;
  speaker: Speaker;
  src: Lang;
  tgt: Lang;
  startedAt: number;
  lastVoiced: number | null;
  pauseCommitted: boolean;
  pauseHinted: boolean;
  voicedFrames: number;
  segVoicedFrames: number;
};

export type FrameAction = { send: boolean; pauseCommit: boolean; pauseHint?: boolean };
export type TurnEnd = { turn: ActiveTurn; tSpeechEnd: number; hadSpeech: boolean };

export class TurnController {
  private nextId = 1;
  active: ActiveTurn | null = null;

  constructor(
    private readonly pair: { a: Lang; b: Lang },
    private readonly pauseCommitMs: number | null = 300,
    private readonly pauseHintMs: number | null = null,
    private readonly minSegmentMs = 1000,
    private readonly frameMs = 20,
  ) {}

  directionFor(speaker: Speaker): { src: Lang; tgt: Lang } {
    return speaker === "A" ? { src: this.pair.a, tgt: this.pair.b } : { src: this.pair.b, tgt: this.pair.a };
  }

  pttDown(speaker: Speaker, now: number): ActiveTurn {
    const { src, tgt } = this.directionFor(speaker);
    this.active = { id: this.nextId++, speaker, src, tgt, startedAt: now, lastVoiced: null, pauseCommitted: true, pauseHinted: true, voicedFrames: 0, segVoicedFrames: 0 };
    return this.active;
  }

  frame(voiced: boolean, tPerf: number): FrameAction {
    const t = this.active;
    if (!t) return { send: false, pauseCommit: false };
    if (voiced) {
      t.lastVoiced = tPerf;
      t.voicedFrames++;
      t.segVoicedFrames++;
      t.pauseCommitted = false;
      t.pauseHinted = false;
      return { send: true, pauseCommit: false };
    }
    if (this.pauseHintMs !== null && !t.pauseHinted && t.lastVoiced !== null && tPerf - t.lastVoiced >= this.pauseHintMs) {
      t.pauseHinted = true;
      return { send: true, pauseCommit: false, pauseHint: true };
    }
    if (this.pauseCommitMs !== null && !t.pauseCommitted && t.lastVoiced !== null && tPerf - t.lastVoiced >= this.pauseCommitMs) {
      t.pauseCommitted = true;
      if (t.segVoicedFrames * this.frameMs < this.minSegmentMs) return { send: true, pauseCommit: false };
      t.segVoicedFrames = 0;
      return { send: true, pauseCommit: true };
    }
    return { send: true, pauseCommit: false };
  }

  pttUp(now: number): TurnEnd | null {
    const t = this.active;
    if (!t) return null;
    this.active = null;
    return { turn: t, tSpeechEnd: t.lastVoiced ?? now, hadSpeech: t.voicedFrames > 0 };
  }
}

export type VadAction = { start: Int16Array[] | null; end: boolean };

/**
 * Cascade VAD mode (FR-2): the browser segments turns with the same frame
 * energy VAD that defines t_speech_end. A turn starts after `minRun`
 * consecutive voiced frames (debounce against clicks) and replays a short
 * pre-roll so the first syllable reaches STT; it ends after `silenceMs` of
 * silence since the last voiced frame, i.e. the same window the Realtime
 * server_vad uses (`silence_duration_ms`), so the two modes are comparable.
 */
export class VadSegmenter {
  private ring: Int16Array[] = [];
  private run = 0;
  private inSpeech = false;
  private lastVoiced = 0;

  constructor(
    public silenceMs = 400,
    private readonly prerollFrames = 15, // 300 ms of 20 ms frames
    private readonly minRun = 3,
  ) {}

  get active(): boolean {
    return this.inSpeech;
  }

  frame(pcm: Int16Array, voiced: boolean, tPerf: number): VadAction {
    if (!this.inSpeech) {
      this.ring.push(pcm);
      if (this.ring.length > this.prerollFrames) this.ring.shift();
      this.run = voiced ? this.run + 1 : 0;
      if (this.run < this.minRun) return { start: null, end: false };
      this.inSpeech = true;
      this.lastVoiced = tPerf;
      const pre = this.ring;
      this.ring = [];
      this.run = 0;
      return { start: pre, end: false };
    }
    if (voiced) {
      this.lastVoiced = tPerf;
      return { start: null, end: false };
    }
    if (tPerf - this.lastVoiced >= this.silenceMs) {
      this.inSpeech = false;
      return { start: null, end: true };
    }
    return { start: null, end: false };
  }

  reset(): void {
    this.ring = [];
    this.run = 0;
    this.inSpeech = false;
  }
}
