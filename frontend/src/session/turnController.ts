/**
 * Pure push-to-talk turn logic driven by capture frames (unit-tested).
 * - t_speech_end = last voiced frame before PTT release (DESIGN §4), so a
 *   late release counts against latency exactly as the user perceives it.
 * - Optional in-turn pause commits (cascade): a pause >= pauseCommitMs after
 *   speech yields one non-final commit, so long turns get segment finals.
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
  voicedFrames: number;
};

export type FrameAction = { send: boolean; pauseCommit: boolean };
export type TurnEnd = { turn: ActiveTurn; tSpeechEnd: number; hadSpeech: boolean };

export class TurnController {
  private nextId = 1;
  active: ActiveTurn | null = null;

  constructor(
    private readonly pair: { a: Lang; b: Lang },
    private readonly pauseCommitMs: number | null = 300,
  ) {}

  directionFor(speaker: Speaker): { src: Lang; tgt: Lang } {
    return speaker === "A" ? { src: this.pair.a, tgt: this.pair.b } : { src: this.pair.b, tgt: this.pair.a };
  }

  pttDown(speaker: Speaker, now: number): ActiveTurn {
    const { src, tgt } = this.directionFor(speaker);
    this.active = { id: this.nextId++, speaker, src, tgt, startedAt: now, lastVoiced: null, pauseCommitted: true, voicedFrames: 0 };
    return this.active;
  }

  frame(voiced: boolean, tPerf: number): FrameAction {
    const t = this.active;
    if (!t) return { send: false, pauseCommit: false };
    if (voiced) {
      t.lastVoiced = tPerf;
      t.voicedFrames++;
      t.pauseCommitted = false;
      return { send: true, pauseCommit: false };
    }
    if (this.pauseCommitMs !== null && !t.pauseCommitted && t.lastVoiced !== null && tPerf - t.lastVoiced >= this.pauseCommitMs) {
      t.pauseCommitted = true;
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
