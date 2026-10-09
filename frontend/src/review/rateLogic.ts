/** Pure rating-screen logic (keyboard + resume), unit-tested without a DOM. */
import { DIMS, type Rating, type ReviewItem } from "./api";

export const EMPTY: Rating = { adequacy: null, fluency: null, naturalness: null, notes: "" };

export const isComplete = (r: Rating | undefined): boolean => !!r && DIMS.every((d) => r[d] != null);

/** Resume where the rater left off: the first item without all three scores. */
export function resumeIndex(items: ReviewItem[], ratings: Record<string, Rating>): number {
  const i = items.findIndex((it) => !isComplete(ratings[it.item_id]));
  return i < 0 ? 0 : i;
}

export type Draft = { cur: Rating; focus: number };
export type KeyAction = { draft: Draft; action?: "toggle-play" | "save-next"; handled: boolean };

/** 1-5 scores the focused row and moves to the next row; Tab cycles rows; Space plays/pauses; Enter saves. */
export function applyKey(d: Draft, key: string, shift = false): KeyAction {
  if (key >= "1" && key <= "5" && key.length === 1) {
    const cur = { ...d.cur, [DIMS[d.focus]]: Number(key) };
    return { draft: { cur, focus: Math.min(DIMS.length - 1, d.focus + 1) }, handled: true };
  }
  if (key === "Tab") return { draft: { ...d, focus: (d.focus + (shift ? DIMS.length - 1 : 1)) % DIMS.length }, handled: true };
  if (key === " ") return { draft: d, action: "toggle-play", handled: true };
  if (key === "Enter") return { draft: d, action: "save-next", handled: true };
  return { draft: d, handled: false };
}

export const fmtStat = (s: { mean: number | null; median: number | null; sd: number | null; min: number | null; max: number | null }): string =>
  s.mean == null ? "–" : `${s.mean.toFixed(2)} / ${s.median} (${(s.sd ?? 0).toFixed(2)}, ${s.min}-${s.max})`;
