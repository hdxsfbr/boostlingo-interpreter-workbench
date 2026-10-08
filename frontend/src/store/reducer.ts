/** UI state derived purely from SessionEvents (mode-agnostic). */
import type { Mode, SessionEvent, SessionState, Speaker } from "../session/protocol";

export type Segment = { text: string; final: boolean };
export type TurnStatus = "listening" | "processing" | "playing" | "done" | "skipped" | "failed";

export type TurnView = {
  id: number;
  mode: Mode;
  speaker: Speaker;
  src: string;
  tgt: string;
  startedAt: number;
  source: Record<number, Segment>;
  target: Record<number, Segment>;
  tSpeechEnd?: number;
  tFirstAudible?: number;
  /** headline H = t_first_audible - t_speech_end (browser clock) */
  latencyMs?: number;
  browserMarks: Record<string, number>;
  serverMarks: Record<string, number>;
  status: TurnStatus;
  reason?: string;
  usage?: Record<string, unknown>;
  serverDone: boolean;
  audioEnded: boolean;
};

export type TimelineItem = { kind: "turn"; id: number } | { kind: "switch"; from: Mode; to: Mode; at: number };
export type ErrorView = { id: number; code: string; stage: string; message: string; retryable: boolean; turn_id?: number | null };

export type State = {
  sessionState: SessionState;
  mode: Mode;
  pipeline?: string;
  providers: Record<string, string>;
  turns: Record<number, TurnView>;
  timeline: TimelineItem[];
  errors: ErrorView[];
  nextErrorId: number;
};

export const initialState = (mode: Mode = "cascade"): State => ({
  sessionState: "idle",
  mode,
  providers: {},
  turns: {},
  timeline: [],
  errors: [],
  nextErrorId: 1,
});

function patchTurn(s: State, id: number, f: (t: TurnView) => Partial<TurnView>): State {
  const t = s.turns[id];
  if (!t) return s;
  return { ...s, turns: { ...s.turns, [id]: { ...t, ...f(t) } } };
}

function settle(t: TurnView): Partial<TurnView> {
  if (t.status === "skipped" || t.status === "failed") return {};
  return t.serverDone && (t.audioEnded || t.tFirstAudible === undefined) && t.status !== "listening" ? { status: "done" } : {};
}

export function reduce(s: State, ev: SessionEvent): State {
  switch (ev.type) {
    case "session.state":
      return { ...s, sessionState: ev.state, mode: ev.mode };
    case "session.ready":
      return { ...s, pipeline: ev.pipeline, providers: ev.providers };
    case "mode.switched":
      return { ...s, mode: ev.to, timeline: [...s.timeline, { kind: "switch", from: ev.from, to: ev.to, at: ev.at }] };
    case "turn.started": {
      const t: TurnView = {
        id: ev.turn_id, mode: ev.mode, speaker: ev.speaker, src: ev.src, tgt: ev.tgt, startedAt: ev.at,
        source: {}, target: {}, browserMarks: {}, serverMarks: {}, status: "listening", serverDone: false, audioEnded: false,
      };
      return { ...s, turns: { ...s.turns, [t.id]: t }, timeline: [...s.timeline, { kind: "turn", id: t.id }] };
    }
    case "speech.ended":
      return patchTurn(s, ev.turn_id, () => ({ tSpeechEnd: ev.t_speech_end, status: "processing" }));
    case "transcript.partial":
    case "transcript.final": {
      const final = ev.type === "transcript.final";
      return patchTurn(s, ev.turn_id, (t) => {
        if (t.source[ev.seg]?.final && !final) return {}; // never regress a final
        return { source: { ...t.source, [ev.seg]: { text: ev.text, final } } };
      });
    }
    case "translation.partial":
    case "translation.final": {
      const final = ev.type === "translation.final";
      return patchTurn(s, ev.turn_id, (t) => {
        if (t.target[ev.seg]?.final && !final) return {};
        return { target: { ...t.target, [ev.seg]: { text: ev.text, final } } };
      });
    }
    case "latency.mark":
      return patchTurn(s, ev.turn_id, (t) =>
        ev.clock === "browser"
          ? { browserMarks: { ...t.browserMarks, [ev.mark]: ev.ms }, ...(ev.mark === "first_audible" ? { latencyMs: ev.ms } : {}) }
          : { serverMarks: { ...t.serverMarks, [ev.mark]: ev.ms } },
      );
    case "audio.started":
      return patchTurn(s, ev.turn_id, (t) => ({
        tFirstAudible: ev.t_first_audible,
        status: t.status === "done" ? "done" : "playing",
      }));
    case "audio.ended": {
      const s2 = patchTurn(s, ev.turn_id, () => ({ audioEnded: true }));
      return patchTurn(s2, ev.turn_id, settle);
    }
    case "turn.done": {
      const s2 = patchTurn(s, ev.turn_id, () => ({ serverDone: true, usage: ev.usage }));
      return patchTurn(s2, ev.turn_id, settle);
    }
    case "turn.skipped":
      return patchTurn(s, ev.turn_id, () => ({ status: "skipped", reason: ev.reason }));
    case "error": {
      const err: ErrorView = { id: s.nextErrorId, code: ev.code, stage: ev.stage, message: ev.message, retryable: ev.retryable, turn_id: ev.turn_id };
      let s2: State = { ...s, errors: [...s.errors.slice(-4), err], nextErrorId: s.nextErrorId + 1 };
      if (ev.turn_id != null && !ev.retryable) s2 = patchTurn(s2, ev.turn_id, () => ({ status: "failed", reason: `${ev.stage}: ${ev.code}` }));
      return s2;
    }
    default:
      return s;
  }
}

export function dismissError(s: State, id: number): State {
  return { ...s, errors: s.errors.filter((e) => e.id !== id) };
}

export const joinSegments = (segs: Record<number, Segment>): { text: string; final: boolean }[] =>
  Object.keys(segs)
    .map(Number)
    .sort((a, b) => a - b)
    .map((k) => segs[k]);
