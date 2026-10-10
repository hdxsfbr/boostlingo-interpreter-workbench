/** Rolling latency statistics and export (FR-7). */
import type { Mode } from "../session/protocol";
import type { TurnView } from "./reducer";

export function quantile(xs: number[], q: number): number | undefined {
  if (!xs.length) return undefined;
  const s = [...xs].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

export type Stat = { n: number; median?: number; p90?: number };
export const stat = (xs: number[]): Stat => ({ n: xs.length, median: quantile(xs, 0.5), p90: quantile(xs, 0.9) });

export const TARGET_MS: Record<Mode, number> = { realtime: 1500, cascade: 2000 };
export const LIMIT_MS: Record<Mode, number> = { realtime: 1500, cascade: 3000 };

/** A18: a server stage on the speech-end clock = browser commit_sent + the server's
 * duration from commit receipt (an estimate). undefined when the turn has no commit_sent. */
export function stageMs(t: TurnView, mark: string): number | undefined {
  const c = t.browserMarks.commit_sent, v = t.serverMarks[mark];
  return c === undefined || v === undefined ? undefined : c + v;
}

/** A stage that happened before speech end: work started while the speaker was still
 * talking (a speculative translation adopted at the final commit, or an earlier segment
 * committed at an in-turn pause). Shown as "early", never as a negative bar. */
export const isEarly = (ms: number | undefined): boolean => ms !== undefined && ms < 0;

/** Why a turn's stage was early: speculation if the server adopted one (spec_hit), else an earlier segment. */
export const earlyReason = (t: TurnView): "speculative" | "earlier segment" =>
  t.serverMarks.spec_hit !== undefined ? "speculative" : "earlier segment";

export type StageStat = Stat & { early: number };

export function summarize(turns: TurnView[], mode: Mode, window = 50) {
  // headline H = first audible − speech end. Audio is only sent after the final commit
  // (playback policy D8), which is after speech end, so H < 0 would be a measurement bug:
  // such a turn is left out instead of silently pulling p50 down.
  const ts = turns.filter((t) => t.mode === mode && t.latencyMs !== undefined && t.latencyMs >= 0).slice(-window);
  const marks = new Set<string>();
  ts.forEach((t) => Object.keys(t.serverMarks).forEach((m) => marks.add(m)));
  const stages: Record<string, StageStat> = {};
  for (const m of marks) {
    const vs = ts.map((t) => stageMs(t, m)).filter((v): v is number => v !== undefined);
    // stats only over turns where the stage came after speech end; early ones are counted apart
    stages[m] = { ...stat(vs.filter((v) => !isEarly(v))), early: vs.filter(isEarly).length };
  }
  return { headline: stat(ts.map((t) => t.latencyMs!)), stages };
}

export type TurnRecord = {
  turn_id: number; mode: Mode; speaker: string; src: string; tgt: string; status: string; reason?: string;
  latency_ms?: number; browser_marks: Record<string, number>; server_marks: Record<string, number>;
  source_text: string; target_text: string; usage?: Record<string, unknown>;
  recording?: Record<string, string>;
};

export function toRecord(t: TurnView): TurnRecord {
  const txt = (segs: TurnView["source"]) => Object.keys(segs).map(Number).sort((a, b) => a - b).map((k) => segs[k].text).join(" ").trim();
  return {
    turn_id: t.id, mode: t.mode, speaker: t.speaker, src: t.src, tgt: t.tgt, status: t.status, reason: t.reason,
    latency_ms: t.latencyMs, browser_marks: t.browserMarks, server_marks: t.serverMarks,
    source_text: txt(t.source), target_text: txt(t.target), usage: t.usage,
    ...(t.recording ? { recording: t.recording } : {}),
  };
}

const CSV_MARKS = ["commit_sent", "first_audible"];
const CSV_SERVER = ["stt_final", "mt_first_token", "mt_first_chunk", "tts_request", "tts_first_byte", "audio_first_sent", "tail_tts_first_byte"];

export function toCsv(records: TurnRecord[]): string {
  const head = ["turn_id", "mode", "speaker", "src", "tgt", "status", "latency_ms", ...CSV_MARKS.map((m) => `b_${m}`), ...CSV_SERVER.map((m) => `s_${m}`), "source_text", "target_text"];
  const esc = (v: unknown) => {
    if (v === undefined || v === null) return "";
    const s = typeof v === "number" ? v.toFixed(1) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = records.map((r) =>
    [r.turn_id, r.mode, r.speaker, r.src, r.tgt, r.status, r.latency_ms, ...CSV_MARKS.map((m) => r.browser_marks[m]), ...CSV_SERVER.map((m) => r.server_marks[m]), r.source_text, r.target_text].map(esc).join(","),
  );
  return [head.join(","), ...rows].join("\n");
}
